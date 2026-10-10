---
description: Daily pipeline health check (operations manual §7) — nodes, CronJobs, recent jobs, WARN scan, pi2 load, backup, TX2 disk, DB freshness
---
Run the daily operations checklist (`docs/market-data-pipeline-operations-manual.md` §7) and report a pass/fail table, then a one-line verdict: `HEALTHY` or `ISSUES: <list>`.

Current cluster state:

!`export KUBECONFIG=~/.kube/pi-cluster.yaml; kubectl get nodes`

!`export KUBECONFIG=~/.kube/pi-cluster.yaml; kubectl get cronjobs -n market-data`

!`export KUBECONFIG=~/.kube/pi-cluster.yaml; kubectl get jobs -n market-data | tail -12`

Then complete the checklist:
1. Scan the latest run of each CronJob for WARN lines (`kubectl logs job/<latest>`) — summarize per feed, don't paste walls of logs.
2. pi2 load via the ops-tools SSH helper (`uptime; free -m | head -2`) — flag sustained load > 3. Ask me for the Pi SSH password when you need it.
3. Today's backup on pi3: `ls -lh /var/lib/market-data/backups/ | tail -3` — expect `marketdata-<today>.dump`.
4. TX2 disk: `df -h / /mnt/tx2-ssd` — alert if eMMC (`/`) is above 85%.
5. DB row counts + `pipeline_heartbeat` freshness (§5, Option A) — flag any feed older than its cadence × 2.
