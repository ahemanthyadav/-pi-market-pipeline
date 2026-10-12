#!/bin/sh
# node-stats-log.sh — node-local stats logger for the marketdata homelab
# (added 2026-10-10, ADR 0011). Appends ONE CSV line per invocation.
#
# WHY THIS EXISTS: in-cluster monitoring dies with the control plane. During
# the 2026-10-09/10 outage (pi2 wedged ~16h, DB down, whole pipeline dark)
# there was no node-level record of load/temp/swap — post-mortems depended on
# journal spelunking. This script runs from ROOT CRON every 5 minutes, writes
# to a local file, and keeps logging while k3s is dead. It is deliberately
# dependency-free (procps + coreutils only) so it runs on Pi + TX2 alike.
#
# Columns:
#   ts_utc               ISO-8601 UTC timestamp of the sample
#   host                 hostname
#   uptime_s             seconds since boot
#   load1/5/15           /proc/loadavg
#   cpu_pct              100 - idle over a 1s vmstat window (includes iowait)
#   mem_used_mb          MemTotal - MemAvailable (the honest "used")
#   mem_avail_mb         MemAvailable
#   swap_used_mb         SwapTotal - SwapFree
#   swap_total_mb        SwapTotal
#   temp_c               hottest /sys/class/thermal zone (deg C)
#   throttle_hex         Pi vcgencmd get_throttled raw hex (0x0 = clean;
#                        bit0 uv-now bit1 cap-now bit2 throttle-now,
#                        bit16 uv-since-boot bit17 cap-since-boot
#                        bit18 throttle-since-boot; "" on TX2)
#   k3s_state            systemctl is-active of k3s or k3s-agent
#   db_procs             postgres processes visible (0 = DB down; only
#                        meaningful on TX2 where timescaledb runs)
#   disk_root_used_pct   df / used %
#   disk_data_used_pct   df /mnt/tx2-ssd used % (TX2 only; DB volume)
#
# Managed by the marketdata project:
#   docs/market-data-pipeline-operations-manual.md (§7 checklist)
#   docs/adr/0011-node-local-stats-logging.md
# Remove: delete the root crontab line, this file, /etc/logrotate.d/node-stats,
# and /var/log/node-stats/.
OUT=/var/log/node-stats/stats.csv
mkdir -p /var/log/node-stats
[ -s "$OUT" ] || printf '%s\n' 'ts_utc,host,uptime_s,load1,load5,load15,cpu_pct,mem_used_mb,mem_avail_mb,swap_used_mb,swap_total_mb,temp_c,throttle_hex,k3s_state,db_procs,disk_root_used_pct,disk_data_used_pct' > "$OUT"

ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
host=$(hostname)
ups=$(cut -d. -f1 /proc/uptime)
read -r l1 l5 l15 _rest < /proc/loadavg
idle=$(vmstat 1 2 2>/dev/null | tail -1 | awk '{print $15}')
cpu=$(awk -v i="${idle:-100}" 'BEGIN{printf "%.0f", 100-i}')
mem_used=$(awk '/^MemTotal:/{t=$2}/^MemAvailable:/{a=$2}END{printf "%.0f",(t-a)/1024}' /proc/meminfo)
mem_avail=$(awk '/^MemAvailable:/{printf "%.0f",$2/1024}' /proc/meminfo)
swap_used=$(awk '/^SwapTotal:/{t=$2}/^SwapFree:/{f=$2}END{printf "%.0f",(t-f)/1024}' /proc/meminfo)
swap_total=$(awk '/^SwapTotal:/{printf "%.0f",$2/1024}' /proc/meminfo)
temp=$(cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | awk 'BEGIN{m=-9999}{v=$1/1000;if(v>m)m=v}END{if(m>-9999)printf "%.1f",m;else print ""}')
if command -v vcgencmd >/dev/null 2>&1; then
  thr=$(vcgencmd get_throttled 2>/dev/null | cut -d= -f2)
else
  thr=""
fi
k3=$(systemctl is-active k3s 2>/dev/null)
if [ "$k3" != "active" ]; then
  k3=$(systemctl is-active k3s-agent 2>/dev/null)
fi
dbp=$(pgrep -c -x postgres 2>/dev/null)
[ -n "$dbp" ] || dbp=0
droot=$(df -P / | awk 'NR==2{gsub(/%/,"");print $5}')
if [ -d /mnt/tx2-ssd ]; then
  ddata=$(df -P /mnt/tx2-ssd | awk 'NR==2{gsub(/%/,"");print $5}')
else
  ddata=""
fi
printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
  "$ts" "$host" "$ups" "$l1" "$l5" "$l15" "$cpu" "$mem_used" "$mem_avail" \
  "$swap_used" "$swap_total" "$temp" "${thr:-}" "${k3:-unknown}" "$dbp" \
  "$droot" "${ddata:-}" >> "$OUT"
