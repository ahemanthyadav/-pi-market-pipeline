#!/bin/bash
# Behavioural test for ops-tools/power-review.sh's PASS/FAIL verdict logic (the awk).
#
#   bash tests/test-power-review.sh        # exit 0 = all checks passed
#
# Hermetic: no SSH, no cluster. power-review.sh resolves the repo root from its
# own location and reads out/node-stats/<node>.csv relative to that, so the
# script is copied VERBATIM (cmp-verified) into a scratch "repo" and fed
# synthetic CSVs; --no-collect keeps collect-node-stats.sh (and the network)
# out of the picture. Proves, per the acceptance rule in the script header:
#   - clean window           -> PASS, exit 0
#   - live throttle bits     -> FAIL           (0x1/0x2/0x4 in any sample)
#   - NEW since-boot 0x10000 -> FAIL; pre-existing 0x10000 -> PASS
#   - >15 min sample gap     -> FAIL
#   - missing CSV / no samples in window -> FAIL
#   - temp >= 60C            -> WARN only, never a power FAIL
set -u
cd "$(git rev-parse --show-toplevel)"
SANDBOX="$(mktemp -d)"; trap 'rm -rf "$SANDBOX"' EXIT
mkdir -p "$SANDBOX/ops-tools" "$SANDBOX/out/node-stats"
cp ops-tools/power-review.sh "$SANDBOX/ops-tools/power-review.sh"
cmp -s ops-tools/power-review.sh "$SANDBOX/ops-tools/power-review.sh" \
  || { echo "FAIL: sandbox copy differs from the real script"; exit 1; }

SINCE=2026-10-20T00:00:00Z
UNTIL=2026-10-20T01:00:00Z
STATS="$SANDBOX/out/node-stats"

# CSV columns the awk reads: 1=ts, 4=load1, 12=temp_c, 13=throttle_hex
row()   { printf '%s,0,0,%s,0,0,0,0,0,0,0,%s,%s\n' "$2" "$3" "$4" "$5" >> "$STATS/$1.csv"; }
# clean_node <node> <hex> <temp> [date]: 12 samples, 5-min cadence, inside the window
clean_node() {
  local h=$1 hex=$2 temp=$3 d=${4:-2026-10-20} m
  for m in 00 05 10 15 20 25 30 35 40 45 50 55; do
    row "$h" "${d}T00:${m}:00Z" 1.2 "$temp" "$hex"
  done
}
reset() { rm -f "$STATS"/*.csv; }
run()   { bash "$SANDBOX/ops-tools/power-review.sh" --no-collect --since "$SINCE" --until "$UNTIL" 2>&1; }

pass=0; fail=0
check() { if [ "$2" = "$3" ]; then echo "  ok    $1"; pass=$((pass+1)); else echo "  FAIL  $1 (got '$2', want '$3')"; fail=$((fail+1)); fi; }
has()   { grep -c "$2" <<<"$1"; }

echo "== clean window passes (heat is a WARN, pre-existing since-boot UV is not new)"
reset
clean_node pi0 0x0 48.0
clean_node pi1 0x0 48.0
clean_node pi2 0x0 65.0        # soft-temp territory: WARN, not a power FAIL
clean_node pi3 0x10000 48.0    # since-boot undervolt present from the FIRST sample
out=$(run); rc=$?
check "exit code 0"                           "$rc" 0
check "RESULT: PASS printed"                  "$(has "$out" 'RESULT: PASS')" 1
check "all four nodes PASS"                   "$(grep -cE '^pi[0-3] .* PASS' <<<"$out")" 4
check "hot node carries the soft-temp WARN"   "$(has "$out" 'WARN soft-temp')" 1
check "no FAIL rows"                          "$(grep -cE '^pi[0-3] .* FAIL' <<<"$out")" 0

echo "== every power-fail condition flips the verdict"
reset
clean_node pi0 0x5 48.0        # live undervolt-now + throttled-now bits
clean_node pi1 0x0 48.0        # ...but a NEW since-boot undervolt on the last sample
sed -i '$d' "$STATS/pi1.csv"; row pi1 2026-10-20T00:55:00Z 1.2 48.0 0x10000
row pi2 2026-10-20T00:00:00Z 1.2 48.0 0x0   # 30-min hole between samples
row pi2 2026-10-20T00:30:00Z 1.2 48.0 0x0
row pi2 2026-10-20T00:35:00Z 1.2 48.0 0x0
clean_node pi3 0x0 48.0        # one healthy node to prove FAILs are per-node
out=$(run); rc=$?
check "exit code 1"                           "$rc" 1
check "RESULT: FAIL printed"                  "$(has "$out" 'RESULT: FAIL')" 1
check "live bits -> pi0 FAIL"                 "$(grep -cE '^pi0 .* FAIL.*live throttle/undervolt bit' <<<"$out")" 1
check "live-hit sample count reported"        "$(grep -cE '^pi0 +12 +12 ' <<<"$out")" 1
check "new since-boot UV -> pi1 FAIL"         "$(grep -cE '^pi1 .* FAIL.*new since-boot undervolt' <<<"$out")" 1
check "sample gap -> pi2 FAIL"                "$(grep -cE '^pi2 .* FAIL.*gap >15 min' <<<"$out")" 1
check "healthy pi3 still PASS"                "$(grep -cE '^pi3 .* PASS' <<<"$out")" 1

echo "== missing data is a FAIL, never a silent PASS"
reset                           # pi0: no CSV at all
clean_node pi1 0x0 48.0 2026-10-19   # samples exist, all BEFORE the window
clean_node pi2 0x0 48.0
clean_node pi3 0x0 48.0
out=$(run); rc=$?
check "exit code 1"                           "$rc" 1
check "missing CSV -> FAIL"                   "$(has "$out" 'no CSV — FAIL')" 1
check "empty window -> FAIL (no samples)"     "$(grep -cE '^pi1 .* FAIL.*no samples in window' <<<"$out")" 1
check "nodes with data still PASS"            "$(grep -cE '^pi[23] .* PASS' <<<"$out")" 2

echo "== usage guard"
out=$(bash "$SANDBOX/ops-tools/power-review.sh" --bogus 2>&1); rc=$?
check "unknown flag exits 2"                  "$rc" 2
check "prints usage"                          "$(has "$out" 'usage:')" 1

echo; echo "result: $pass passed, $fail failed"; [ $fail -eq 0 ]
