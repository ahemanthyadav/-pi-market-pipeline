# 0011. Node-local stats logging: root-cron CSV on every host

- Date: 2026-10-10
- Status: accepted — deployed and first-sample-verified on pi0/pi1/pi2/pi3/TX2
  on 2026-10-10

## Context
The 2026-10-09→10 outage (pi2 wedged ~16 h; agents failed cluster-wide; the
DB — and therefore every pipeline write — down the whole window; ~14
scheduled runs missed) left **no node-level telemetry to diagnose from**.
In-cluster monitoring dies with the control plane by construction, so the
post-mortem depended on per-node journal spelunking over SSH. Within ten
minutes of deployment, the new logger found what pi2 had been hiding all
day: **live undervoltage + CPU-throttle flags** (`vcgencmd get_throttled` =
0xd0005 at 62 °C) — throttled CPU → slow API → agent retry storms → 1 GB RAM
swap-thrash → the wedge cascade. pi0 showed past uv/throttle flags (0x50000)
too, so the Pis' power delivery deserves a physical check.

## Decision
1. **Node-local, not in-cluster.** Each host appends one CSV line every
   5 minutes via **root cron** to `/var/log/node-stats/stats.csv`
   (`/usr/local/bin/node-stats-log.sh`). It keeps recording while k3s is
   dead — precisely the failure mode we need visibility into.
2. **One dependency-free POSIX-sh script, identical on all 5 hosts**
   (procps + coreutils only; works on Debian Pi and Jetson alike):
   UTC timestamp, uptime, load 1/5/15, cpu% (100−idle over a 1 s vmstat
   window), mem_used/avail, swap used/total, hottest thermal zone (°C),
   Pi throttle/undervolt hex, k3s/k3s-agent service state, postgres process
   count (DB up/down — meaningful on TX2), root + data-disk used %.
3. **No k8s objects, no images, no §6 cycle.** Deploy/remove is SSH +
   crontab (+ `/etc/logrotate.d/node-stats`, weekly × 8 compressed).
4. **Collection is pull-based on demand** — `ops-tools/collect-node-stats.sh`
   fetches all nodes' CSVs into `out/node-stats/`. Ingesting into
   TimescaleDB/Grafana is a deliberate non-goal for now: it would reintroduce
   the control-plane dependency; revisit via the roadmap if dashboards are
   wanted.

## Consequences
- Post-mortems get a uniform 5-minute record across all hosts, including
  through total cluster outages.
- `throttle_hex` decodes (Pi only): bit0/1/2 = uv/freq-cap/throttle **now**,
  bits 16/17/18/19 = uv/cap/throttle/soft-temp **since boot**; `0x0` clean.
  Non-zero on pi2 → suspect the PSU/cable before blaming software.
- `db_procs > 0` is expected only on TX2 (timescaledb container processes
  are visible from the host); 0 elsewhere is normal.
- Files are tiny (~30 KB/week/node uncompressed); logrotate caps growth.
- Reimaged host = logger gone; redeploy per ops-manual §7 step 8 pointers.
- The 2026-10-10 first samples also flagged: pi2's desktop session idling
  RAM on the control-plane node, and root-disk 84% on TX2 (watch, not act).

## Amendment 2026-10-11
- **The "deployed on all 5 hosts" claim was wrong for cron:** every host had an empty root crontab, so only the first
  manual sample existed and `stats.csv` was empty after the first logrotate. Cron entry
  `*/5 * * * * /usr/local/bin/node-stats-log.sh` installed on pi0/pi1/pi2/pi3/TX2 and a 23:10 UTC sample verified on each
  (`ops-tools/collect-node-stats.sh`). Lesson: "first-sample-verified" is not "scheduled" — verify the second sample.
- **Header bug:** the script wrote the header only when the file was missing; logrotate leaves an empty file, so every
  rotated file would lack a header. Test changed from `-f` to `-s` (non-empty), header restored on the four Pi files, rotation
  case tested. The script now also lives in the repo: `ops-tools/node-stats-log.sh` (the hosts' copy is the same file).
