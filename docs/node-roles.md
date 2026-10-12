# Node roles — who runs what, and who is responsible for what

> **Purpose:** one place that answers "what does each machine do, what breaks if it dies, and what must I
> never do to it". Detail stays in the linked docs; this file is the index per node.
> **Last verified: 2026-10-11** (live `kubectl` + SSH to pi0; pi1/pi2/pi3/TX2 host-level facts are from the ops
> manual and earlier sessions, marked where not re-checked today).
> No IP addresses here (AGENTS.md rule 8): node names only; real values live in the gitignored `.hosts.env`.

## 1. At a glance

| Node | Hardware | In k3s? | Primary job | Pinned workloads | If it dies |
|---|---|---|---|---|---|
| **pi0** | Pi 1 B+, 512 MB, SD | **No** | LAN DNS (Pi-hole + unbound), out-of-cluster watcher | none (not a k8s node) | LAN ad-block DNS gone; the dead-man's switch goes silent |
| **pi1** | Pi 3 B, 1 GB, 233 GB SSD | Worker | Telegram bot host; general ingestion pool | `telegram-bot`, `telegram-digest`, `telegram-alerts` | Bot stops answering; digest/alerts not sent; unpinned jobs land on pi3 only |
| **pi2** | Pi 3 B+, 1 GB | **Control plane** | k3s server (API, scheduler, datastore, CoreDNS, Traefik) | none (**cordoned**) | Whole cluster loses its API; nothing new schedules (see §4) |
| **pi3** | Pi 3 B, 1 GB, SSD | Worker | Grafana, backups, general ingestion pool | `grafana`, `pg-backup`, `restore-drill` (Job) | No dashboards, no nightly dump; unpinned jobs land on pi1 only |
| **tx2** (`ahytx2-desktop`) | Jetson TX2, 7.7 GB, eMMC + 224 GB SSD | Worker (GPU, tainted) | **The database**, NLP jobs, image build host | `timescaledb`, `sentiment-scorer`, `headline-ner` | **Every pipeline write fails** (DB down); data is safe on the Retain PV |

## 2. Per node

### pi0 — DNS + watcher (not a cluster node)
- **Does:** Pi-hole v6 + unbound for the LAN (DNS on :53, admin web on :80/:443); Tailscale (joined 2026-10-11,
  `--accept-dns=false --accept-routes=false` so it never rewrites its own resolver).
- **Host jobs (root cron, every 5 min):**
  - `/usr/local/bin/node-stats-log.sh` → `/var/log/node-stats/stats.csv` (ADR 0011). Fixed 2026-10-11 — the crontab was empty.
  - `/usr/local/bin/nodewatch.sh` → pings all 5 nodes + TCP-probes the k3s API, Telegram message only on state change
    (6 h reminder). Deployed 2026-10-11; uses its own dedicated bot; secrets in `/etc/nodewatch.secrets` (mode 600).
    It is the only alert path that does not live inside the cluster it watches.
- **Not responsible for:** anything in k3s. It does not run an agent.
- **Watch:** 512 MB RAM — keep it lean (no extra daemons). Past throttle flags `0x50000` seen before 2026-10-11;
  `0x0` since the reboot. Power: shares the multiport charger (tracker §1).
- **Open:** DNS over the tailnet (Pi-hole `listeningMode` is `LOCAL`), dedicated PSU, router UDP 51820 forward.

### pi1 — Telegram + ingestion worker
- **Pinned (nodeSelector `kubernetes.io/hostname: pi1`):** `telegram-bot` Deployment (long-poll listener, owner + `bot_users`
  allow-list — ADR 0012), CronJobs `telegram-digest` (08:00 IST — the only job with an explicit timeZone) and `telegram-alerts` (02:45).
  Pinned so image imports are needed on one node only.
- **Unpinned jobs:** eligible for any of the 18 unpinned CronJobs (§3.1) — **only if the image is imported on pi1** (no registry).
  The earlier image gap is closed: `yfinance-fetcher:v5`, `nse-fetcher:v4` and `screener:v9` are imported on **both** pi1 and
  pi3 (verified with `ctr images ls` 2026-10-12 08:22 UTC) — and since then most floating jobs run here (§3.1).
- **Host jobs:** node-stats logger — root cron added 2026-10-11 (the crontab was empty; AR-12).
- **Power (2026-10-12):** the only Pi that **failed** the early power review — live undervolt + throttle (`0x50005`) at 04:35 and
  04:50 UTC under image-import load (CPU 58–73 %), even after the move to separate supplies; pi0/pi2/pi3 passed. Suspect its own
  supply/cable. No bulk imports/transfers to it until the swap-test ladder is done (tracker §1).
- **Also holds:** a leftover `screener:v9` tarball in the SSH user's home (tracker §1). Planned second copy of DB dumps (AR-11) — not done.
- **Watch:** accumulates undervolt events; was NotReady during the 2026-10-10 wedge. Agent runs with
  `--disable-apiserver-lb` (direct to the control plane).

### pi2 — control plane (fragile)
- **Does:** k3s server — API on :6443, scheduler, controllers, datastore (`state.db`, no backup yet — AR-10), CoreDNS,
  Traefik, metrics-server, local-path-provisioner.
- **Scheduling:** **cordoned (`SchedulingDisabled`)** — no workload pods run on it. The `node.kubernetes.io/unschedulable`
  taint carries `timeAdded` **2026-10-10 06:11:25 UTC**, i.e. during the 2026-10-09→10 outage recovery (agents being
  rejoined), so it was most likely set then to keep workloads off the 1 GB control plane. The *reason* is inferred from
  timing, not recorded; confirm with the owner. Keep it cordoned: 1 GB RAM, and it has wedged under load twice.
- **Rules (AGENTS.md rule 2):** never restart more than one agent at a time; if load > 3 sustained, follow ops manual §8
  cool-down first. This node's health gates everything else.
- **Power:** the node that showed live undervolt + throttle (`0xd0005`) and wedged ~16 h on 2026-10-09→10. Its dedicated
  PSU/cable is the first item of the power fix.
- **Host jobs:** node-stats logger — root cron added 2026-10-11 (crontab was empty; AR-12). Throttle flags `0xd0000` on
  2026-10-11 (undervolt, throttle and soft-temp limit since boot, none live); 133 MB RAM available, 77 MB swap used.
- **Watch:** desktop session idling on the control plane (ADR 0011 finding); SSH auth can be slow under load —
  `runcmd.py` uses 30 s timeouts for that reason (ops manual §12.8).

### pi3 — Grafana + backups + ingestion worker
- **Pinned:** `grafana` Deployment (tailnet-only; dashboards + the Telegram alert rules), CronJob `pg-backup`
  (01:30; dumps to a hostPath on pi3's SSD), the `restore-drill` Job (backups live on pi3's SSD).
- **Unpinned jobs:** in practice runs most of them today — it holds the newest images (`screener:v9`, `yfinance-fetcher:v5`,
  `nse-fetcher:v4`); the live pods on 2026-10-11 (intraday, rbi, stock-fundamentals, schema Job) all ran here.
- **Responsibility:** the **only** copy of the DB dumps. The newest dump (`marketdata-2026-10-10.dump`) is 0 bytes; copy
  the good ones off-node (tracker §1, AR-11).
- **Host jobs:** node-stats logger — was broken (empty `stats.csv`, empty crontab); root cron added 2026-10-11 (AR-12).
  Throttle flags `0x50000` (since boot, none live) on 2026-10-11.
- **Power:** its own supply; clean `0x0` for ~18 h after the 10-10 reboot, then undervolt events returned (tracker §1).

### tx2 — database, NLP, build host
- **Pinned:** `timescaledb-0` StatefulSet (PV `timescaledb-tx2-ssd` on `sda4`, **Retain** — never delete casually),
  CronJobs `sentiment-scorer` (00:15, FinBERT on CPU) and `headline-ner` (00:45, gazetteer matching → `headline_entities`
  and `headline_events`). Also the GPU smoke-test Pod (manual).
- **Scheduling:** label `hardware=gpu`, taint `gpu=true:NoSchedule` — only jobs that tolerate it land here, so unpinned
  CronJobs never do.
- **Build host:** all `local/*` images are built here (Docker, data-root on the SSD) and shipped as tarballs to the Pis
  (`/mnt/tx2-ssd/image-tarballs/`; the §6 cycle, `/rebuild`).
- **Fixed config — do not "clean up"** (ops manual §2): agent flags, containerd fragment, `/sbin/*tables-restore` wrappers,
  k3s pinned `v1.35.3+k3s1` (cgroup v1 ceiling), Docker `RequiresMountsFor=/mnt/tx2-ssd`, k3s containerd bind-mounted from
  the SSD. The node cannot run any pod without the USB SSD. Re-verify after ANY apt work.
- **Host jobs:** node-stats logger (also records `db_procs`, the DB-up signal) — root cron added 2026-10-11 (crontab was
  empty; AR-12).
- **Watch:** eMMC alert at > 85 % (54 % after the 2026-10-10 move); DB + 4 Gi scorer share 7.7 GB RAM.

## 3. Every scheduled job, by node

Two kinds of scheduled work exist: **Kubernetes CronJobs** (23, all in namespace `market-data`) and **host-level cron**
(on the machines themselves, outside k3s). *Verified live 2026-10-11.* CronJob schedules are **node-local PDT, not UTC**
(ops manual §3); "last scheduled" below is the controller's `lastScheduleTime` in UTC. Suspended 2026-10-10 ~17:44 UTC,
**all 23 active again since 2026-10-12** (staggered un-suspend 03:04–03:27 UTC; `nse-fetcher` was the last and is active now —
verified 08:22 UTC, no CronJob has `spec.suspend: true`). Jobs dated 10-09/10-10 below simply have not come due yet today
(their PDT slot falls later in the UTC day). Refreshed 2026-10-12 08:25 UTC.

### 3.1 Kubernetes CronJobs — which node runs each

A CronJob is *pinned* when its manifest has a `nodeSelector`; otherwise the scheduler picks **pi1 or pi3** (pi2 is
cordoned, tx2 is tainted `gpu=true:NoSchedule`). Images are node-local, so a floating job only works on a node that has
its image (tracker §3).

| Node | CronJobs it runs | How |
|---|---|---|
| **tx2** | `sentiment-scorer` `15 0 * * *`, `headline-ner` `45 0 * * *` | pinned (`hardware: gpu` + toleration) |
| **pi3** | `pg-backup` `30 1 * * *` | pinned (`kubernetes.io/hostname: pi3`; dumps live on its SSD) |
| **pi1** | `telegram-digest` `0 8 * * *` (IST), `telegram-alerts` `45 2 * * *` | pinned (`pi1`) |
| **pi1 or pi3** | the 18 floating jobs below | scheduler's choice |
| **pi2** | none | cordoned control plane |
| **pi0** | none | not a k3s node |

Pinned jobs, last scheduled (UTC): sentiment-scorer 10-12 07:15 · headline-ner 10-12 07:45 · pg-backup 10-10 08:30 (next due
10-12 08:30) · telegram-digest 10-12 02:30 · **telegram-alerts: never scheduled yet** (`lastScheduleTime` empty — only its canary
Job ran; first scheduled run is due 10-12 09:45 UTC).

**Floating jobs (18).** "Seen on" = the node of the retained pods (including refire/canary/validation runs). Since the
re-activation almost everything has landed on **pi1**, not pi3 — so pi1 now carries most of the daily load (and is the node that
logged undervolt events during bulk imports; tracker §1).

| CronJob | Schedule (PDT) | Last scheduled (UTC) | Seen on |
|---|---|---|---|
| yfinance-fetcher | `30 22 * * *` | 10-12 05:30 | pi1 |
| fx-fetcher | `0 23 * * *` | 10-12 06:00 | pi1 |
| yields-fetcher | `15 23 * * *` | 10-12 06:15 | pi1 |
| rates-fetcher | `20 23 * * *` | 10-12 06:20 | pi1 |
| stock-prices | `30 23 * * *` | 10-12 06:30 | pi1 |
| news-fetcher | `45 23 * * *` | 10-12 06:45 | pi1, pi3 |
| ta-compute | `30 0 * * *` | 10-12 07:30 | pi1 |
| pipeline-health | `45 1 * * *` | 10-10 08:45 (due 10-12 08:45) | pi1 |
| stock-metrics | `0 2 * * *` | 10-10 09:00 (due 10-12 09:00) | unknown |
| stock-screener | `15 2 * * *` | 10-10 09:15 (due 10-12 09:15) | pi1 (canary) |
| stock-report | `30 2 * * *` | 10-10 09:30 (due 10-12 09:30) | pi1 (canary) |
| rbi-fetcher | `0 7 * * *` | 10-10 14:00 (due 10-12 14:00) | pi1 |
| nse-fetcher | `15 11 * * *` | 10-09 18:15 (due 10-12 18:15) | pi1 (validation run) |
| fiidii-fetcher | `0 14 * * *` | 10-09 21:00 (due 10-12 21:00) | pi1 |
| intraday-fetcher | `10 * * * *` (hourly) | 10-12 08:10 | pi1, pi3 |
| stock-fundamentals | `0 6 * * 6` (Sat) | 10-10 13:00 (next Sat 10-17 13:00) | pi3 |
| universe-refresh | `0 9 * * 0` (Sun) | 10-04 16:00 (refire ran 10-12) | pi1 |
| fdi-watch | `0 9 1 * *` (monthly) | 10-01 16:00 (next 11-01) | unknown |

Non-CronJob workloads: `timescaledb` StatefulSet (tx2), `grafana` Deployment (pi3), `telegram-bot` Deployment (pi1).
One-off Jobs (manual): `restore-drill` (pi3), `timescaledb-schema` (floating), backfills (floating), GPU smoke test (tx2).

### 3.2 Host-level cron and timers — outside k3s (root crontab unless noted)

| Node | Scheduled work |
|---|---|
| **pi0** | root cron `*/5`: `node-stats-log.sh` (stats CSV) and `nodewatch.sh` (liveness watcher → Telegram). `/etc/cron.d/pihole`: weekly `pihole updateGravity` (Sun, early morning) + daily log flush at 00:00. `/etc/cron.d/e2scrub_all`. |
| **pi1** | root cron `*/5`: `node-stats-log.sh`. `/etc/cron.d/e2scrub_all`. |
| **pi2** | root cron `*/5`: `node-stats-log.sh`. `/etc/cron.d/e2scrub_all`. |
| **pi3** | root cron `*/5`: `node-stats-log.sh`. `/etc/cron.d/e2scrub_all`. |
| **tx2** | root cron `*/5`: `node-stats-log.sh`. `/etc/cron.d/anacron` (+ Ubuntu daily/weekly: apport, update-notifier, etc.). |

All five also run the distro's daily jobs (logrotate — which rotates `stats.csv` weekly — man-db, dpkg) and systemd
timers (apt-daily, fstrim, e2scrub, tmpfiles). **Unattended upgrades are not installed** (checked on tx2 and pi2): the
apt timers only refresh package lists, so nothing upgrades itself — consistent with AGENTS.md rule 3.
**Root-crontab history:** until 2026-10-11 every host's root crontab was empty (the stats logger had never been
scheduled); fixed that day on all five (ADR 0011 amendment).

## 4. Dependencies and blast radius

- **DB (tx2) down** → every fetcher, the screener chain, Grafana panels, the bot's data commands all fail; data is safe.
- **Control plane (pi2) down** → no API, no scheduling, CoreDNS gone; running pods keep running but nothing recovers.
- **pi3 down** → no dashboards, no nightly dump, no restore drill.
- **pi0 down** → LAN DNS gone *and* the out-of-cluster alert path is silent (this is why a second watcher host is an open question — AR-12).
- **Shared charger:** pi1/pi2/pi3 dropped together on 2026-10-10 while pi0 stayed up — the power supply is a single
  point of failure across all of them (tracker §1).
- **No registry:** an image missing on a node gives `ErrImageNeverPull`; keep the "which node has which image" list true.

## 5. Current state (2026-10-11 live check)

- Nodes: pi1, pi3, tx2 Ready; pi2 Ready but **cordoned**. (The tracker had pi1 NotReady — it has since come back.)
- **CronJobs (08:22 UTC 2026-10-12): all 23 active, none suspended.** All jobs since the re-activation Completed; no failed or
  pending pods. `nse-fetcher:v4` is imported on both pi1 and pi3, so floating jobs can run on either.
- Running: `timescaledb-0` (tx2), `telegram-bot` (pi1), `grafana` (pi3).
- Host-level on 2026-10-11 (all five nodes now run the 5-min stats logger): throttle `0x0` pi0, `0x50000` pi1/pi3,
  `0xd0000` pi2, n/a TX2 — none live. Not re-verified today: the TX2 fixed config, the Telegram v6 command check.

## 6. Keeping this file true

Update when: a pin changes (manifest `nodeSelector`), a node is cordoned/un-cordoned, a host job is added to a Pi, an image
is imported on a new node, or hardware changes. `python3 ops-tools/workloads.py --check` covers CronJob/doc agreement but
not placement, so placement edits are manual.

See also: ops manual §2 (inventory + TX2 fixed config), §3 (workloads), §8 (failure runbook); ADR 0011; skill `node-power-health`.
