#!/bin/bash
# Behavioural test for the pg-backup CronJob script (manifests/backup/cronjob.yaml, review AR-11).
# Extracts the script from the manifest, runs it in postgres:16-alpine (same alpine/pg16 client tools as the
# timescaledb image) with a stub pg_dump that serves a real dump, against a scratch /backups dir.
# Needs docker and one real dump in out/backups/ (gitignored); otherwise it skips. Touches no cluster.
set -u
cd "$(git rev-parse --show-toplevel)"
SRC=$(ls out/backups/marketdata-*.dump 2>/dev/null | head -1)
if ! command -v docker >/dev/null || [ -z "$SRC" ]; then echo "SKIP: needs docker and a real dump in out/backups/"; exit 0; fi
IMG=postgres:16-alpine
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
mkdir "$W/backups" "$W/stub"
python3 - "$W" <<'PY'
import sys, yaml
doc = yaml.safe_load(open("manifests/backup/cronjob.yaml"))
c = doc["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
open(sys.argv[1] + "/job.sh", "w").write(c["command"][2])
PY
cat > "$W/stub/pg_dump" <<'EOF'
#!/bin/sh
while [ $# -gt 0 ]; do [ "$1" = "-f" ] && OUT=$2; shift; done
case "$STUB_MODE" in
  good)      cp /src/dump "$OUT" ;;
  empty)     : > "$OUT" ;;
  truncated) head -c "$(( $(wc -c < /src/dump) * 3 / 10 ))" /src/dump > "$OUT" ;;
  garbage)   head -c "$(wc -c < /src/dump)" /dev/zero > "$OUT" ;;
  crash)     head -c 1000 /src/dump > "$OUT"; exit 1 ;;
esac
EOF
chmod +x "$W/stub/pg_dump" "$W/job.sh"
pass=0; fail=0
check() { if [ "$2" = "$3" ]; then echo "  ok    $1"; pass=$((pass+1)); else echo "  FAIL  $1 (got '$2', want '$3')"; fail=$((fail+1)); fi; }
run() { # $1 = STUB_MODE ; output in $OUT, exit code in $RC
  OUT=$(docker run --rm --user "$(id -u):$(id -g)" -e STUB_MODE="$1" -e PGPASSWORD=x -e PATH=/stub:/usr/local/bin:/usr/bin:/bin \
    -v "$W/backups":/backups -v "$W/stub":/stub:ro -v "$W/job.sh":/job.sh:ro -v "$PWD/$SRC":/src/dump:ro \
    "$IMG" sh /job.sh 2>&1); RC=$?; }
count() { ls "$W/backups" | grep -c "$1"; }
TODAY=marketdata-$(date -u +%F).dump
age() { touch -d "$1 days ago" "$W/backups/$2" 2>/dev/null || true; }

echo "== first run on an empty directory"
run good;   check "good dump -> BACKUP-OK"            "$(grep -c '^BACKUP-OK' <<<"$OUT")" 1; check "exit 0" "$RC" 0
check "final file present"                            "$(count "^$TODAY\$")" 1
check "sha256 sidecar matches"                        "$(cd "$W/backups" && sha256sum -c "$TODAY.sha256" >/dev/null 2>&1; echo $?)" 0
check "no temp file left"                             "$(ls -A "$W/backups" | grep -c '\.tmp$')" 0

echo "== failures never replace or prune good dumps"
rm -f "$W/backups/$TODAY" "$W/backups/$TODAY.sha256"
for i in 1 2 3; do cp "$SRC" "$W/backups/marketdata-2026-01-0$i.dump"; age $((10-i)) "marketdata-2026-01-0$i.dump"; done
before=$(ls "$W/backups" | md5sum)
for m in empty truncated garbage crash; do
  run $m; check "$m dump -> failure exit"             "$([ "$RC" -ne 0 ] && echo 1 || echo 0)" 1
  check "$m: no final file, no temp"                   "$(ls -A "$W/backups" | grep -c "$TODAY\|\.tmp")" 0
done
check "directory untouched after 4 failures"          "$(ls "$W/backups" | md5sum)" "$before"

echo "== retention: keep newest 7 readable, remove empties, keep unreadable"
rm -f "$W/backups"/*
for i in 1 2 3 4 5 6 7 8 9; do cp "$SRC" "$W/backups/marketdata-2026-01-0$i.dump"; age $((30-i)) "marketdata-2026-01-0$i.dump"; echo x > "$W/backups/marketdata-2026-01-0$i.dump.sha256"; done
: > "$W/backups/marketdata-2026-01-10.dump"; age 1 marketdata-2026-01-10.dump         # newest by mtime, empty
head -c 5000 /dev/urandom > "$W/backups/marketdata-2026-01-11.dump"; age 2 marketdata-2026-01-11.dump  # unreadable, kept
run good
check "success"                                       "$RC" 0
check "empty file removed"                            "$(count '^marketdata-2026-01-10.dump$')" 0
check "unreadable file kept + warned"                 "$(count '^marketdata-2026-01-11.dump$')$(grep -c 'WARN: unreadable' <<<"$OUT")" 11
check "readable dumps = 7 (today + 6 newest)"         "$(cd "$W/backups" && for f in marketdata-*.dump; do [ -s "$f" ] && echo "$f"; done | grep -vc 'marketdata-2026-01-11')" 7
check "oldest readable pruned"                        "$(count '^marketdata-2026-01-01.dump$')$(count '^marketdata-2026-01-03.dump$')" 00
check "2026-01-04 kept (7th newest)"                  "$(count '^marketdata-2026-01-04.dump$')" 1
check "sidecars pruned with their dump"               "$(ls "$W/backups" | grep -c '2026-01-0[123].dump.sha256')" 0

echo; echo "result: $pass passed, $fail failed"; [ $fail -eq 0 ]
