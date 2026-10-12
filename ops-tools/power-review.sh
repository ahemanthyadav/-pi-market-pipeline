#!/bin/bash
# power-review.sh — apply the Pi power acceptance rule to the node-local stats CSVs.
#
# Rule (docs/pending-tasks.md §1, skill node-power-health): over the review window every Pi shows
#   - NO live throttle bit in throttle_hex (0x1 undervolt now, 0x2 freq-capped now, 0x4 throttled now), and
#   - NO NEW "since boot" undervolt bit (0x10000) on a Pi that did not already have it at the window start, and
#   - samples actually exist for the whole window (a gap is a FAIL: a wedged or rebooted node logs nothing).
# 0x8 (soft-temp limit now) and 0x80000 (since boot) are heat, not power: reported as a WARN, never a power FAIL.
# An idle window proves nothing — read the load column in the output too.
#
# Usage:  bash ops-tools/power-review.sh [--since 2026-10-12T02:59:00Z] [--until <ISO>] [--no-collect]
# Pulls fresh CSVs with collect-node-stats.sh (unless --no-collect). Read-only. Exit 0 = PASS, 1 = FAIL, 2 = usage.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(cd "$HERE/.." && pwd)"
SINCE="2026-10-12T02:59:00Z"; UNTIL="$(date -u +%FT%TZ)"; COLLECT=1
while [ $# -gt 0 ]; do
  case "$1" in
    --since) SINCE="$2"; shift 2;;
    --until) UNTIL="$2"; shift 2;;
    --no-collect) COLLECT=0; shift;;
    *) echo "usage: power-review.sh [--since ISO] [--until ISO] [--no-collect]" >&2; exit 2;;
  esac
done
[ "$COLLECT" = 1 ] && { bash "$HERE/collect-node-stats.sh" >/dev/null 2>&1 || echo "warning: collect-node-stats.sh reported errors" >&2; }

fail=0
printf 'Window: %s -> %s\n\n' "$SINCE" "$UNTIL"
printf '%-5s %7s %9s %9s %10s %9s  %s\n' node samples liveHits maxTemp maxLoad1 firstHex verdict
for h in pi0 pi1 pi2 pi3; do
  f="$REPO/out/node-stats/$h.csv"
  [ -f "$f" ] || { printf '%-5s no CSV — FAIL\n' "$h"; fail=1; continue; }
  # columns: 1 ts, 4 load1, 12 temp_c, 13 throttle_hex
  read -r n live maxt maxl firsthex lasthex gap newuv < <(awk -F, -v s="$SINCE" -v u="$UNTIL" '
    function hex(x,  i,c,v,d){ x=tolower(x); sub(/^0x/,"",x); v=0; for(i=1;i<=length(x);i++){c=substr(x,i,1); d=index("0123456789abcdef",c)-1; v=v*16+d} return v }
    function ep(t,  cmd,r){ cmd="date -u -d \"" t "\" +%s"; cmd | getline r; close(cmd); return r+0 }
    BEGIN{ES=ep(s); EU=ep(u)}
    $1 ~ /^[0-9]{4}-/ {
      t=ep($1); if (t<ES || t>EU) next
      n++; v=hex($13)
      if (n==1) { first=$13; fv=v } ; last=$13; lv=v
      if (v%8>0) live++
      if ($12+0>mt) mt=$12+0
      if ($4+0>ml) ml=$4+0
      if (pt>0 && t-pt>900) gap=1      # > 15 min between 5-min samples
      pt=t
    }
    END{ nu=(int(lv/65536)%2==1 && int(fv/65536)%2==0)?1:0
         if (n==0) {print 0,0,0,0,"-","-",1,0; exit}
         print n+0, live+0, mt+0, ml+0, first, last, gap+0, nu }' "$f")
  v="PASS"; note=""
  [ "${n:-0}" -ge 1 ] || { v="FAIL"; note="no samples in window"; }
  [ "${live:-0}" -eq 0 ] || { v="FAIL"; note="$note live throttle/undervolt bit in ${live} sample(s);"; }
  [ "${gap:-0}" -eq 0 ] || { v="FAIL"; note="$note gap >15 min in samples (node down/wedged?);"; }
  [ "${newuv:-0}" -eq 0 ] || { v="FAIL"; note="$note new since-boot undervolt bit;"; }
  awk -v t="${maxt:-0}" 'BEGIN{exit !(t>=60)}' && note="$note WARN soft-temp threshold reached (heat);"
  [ "$v" = FAIL ] && fail=1
  printf '%-5s %7s %9s %9s %10s %9s  %s %s\n' "$h" "${n:-0}" "${live:-0}" "${maxt:-0}" "${maxl:-0}" "${firsthex:--}" "$v" "$note"
done
echo
echo "last hex per node: $(for h in pi0 pi1 pi2 pi3; do printf '%s=%s ' $h "$(tail -1 "$REPO/out/node-stats/$h.csv" 2>/dev/null | cut -d, -f13)"; done)"
echo "Also check by hand: dmesg 'Undervoltage' count per Pi (runcmd.py … 'dmesg | grep -aci undervoltage') vs the tracker baseline."
[ "$fail" = 0 ] && { echo "RESULT: PASS (power-wise, over the window above)"; exit 0; } || { echo "RESULT: FAIL"; exit 1; }
