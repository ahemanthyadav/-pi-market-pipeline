# Market Data Pipeline — Agent Guide

k3s homelab market-data pipeline: 5-node Pi/Jetson cluster ingesting daily market
data (indices, FX, yields, rates, news, sentiment, FII/DII flows, technicals)
into TimescaleDB, with Grafana dashboards. Git repo (since 2026-10-10, remote
`origin` on GitHub, `main`) — conventional commits (see the `commit-and-changelog`
skill); never commit credentials or IPs (rules 7–8; run the audit before any push).
`docs/` stays the record of truth — update it deliberately.

**Read before cluster mutations:** `docs/market-data-pipeline-operations-manual.md`
(§5 DB queries, §6 image rebuild cycle, §7 daily checklist, §8 failure runbook,
§9 backup/restore, §12 known gaps).

## Ground rules

1. **Working directory** — run everything from `marketdata/`. Set
   `export KUBECONFIG=~/.kube/pi-cluster.yaml` before kubectl in any new shell.
2. **pi2 is fragile** (1 GB RAM control-plane). Never restart more than one
   agent at a time; if load > 3 sustained, follow §8 cool-down before anything else.
3. **TX2 fixed config is load-bearing** (agent flags, containerd fragment,
   iptables wrappers — §2). Never "clean up" or apt-upgrade these without the §8
   re-verification steps.
4. **Data invariants:** fetchers DELETE+INSERT only their own (key, ts) rows —
   re-runs must be idempotent, never duplicate. `index_prices` stays pure-daily
   (intraday goes to `intraday_prices`). Timestamps are UTC. `stock_prices.ts` is
   `00:00 UTC` on the trade date for every row (ADR 0013) — a new writer or backfill must keep it.
5. **PV `timescaledb-tx2-ssd` is Retain** — deleting the PVC does not delete the
   data on sda4, but never delete the `timescaledb` StatefulSet/PVC/PV casually.
   (The permission config denies it anyway.)
6. **No registry by design**: images are `local/*` with `imagePullPolicy: Never`,
   built on TX2, distributed as tarballs via `ops-tools/` SSH helpers (§6). Any
   fetcher code change = bump the tag in `cronjob.yaml` + the full §6 cycle, and save
   the tarball to the TX2 store (`/mnt/tx2-ssd/image-tarballs/`, `SHA256SUMS.all`).
   **Never `crictl rmi --prune` / `ctr images prune` on a node** — it deletes every
   CronJob image, which `Never` pull cannot recover (incident 2026-10-18, ops manual §8).
   Remove old tags one by one, by name.
7. **Secrets never enter tracked files, code, docs, or chat output.** The only
   local store is the gitignored `.secrets.env` (template: `.secrets.env.example`);
   `ops-tools/*.py` read it themselves and remote commands use the `@@PW@@` token —
   never write a password on a command line. Any `@@KEY@@` from the credentials file expands
   the same way — only in commands that CONSUME the value; never echo/cat one back (that prints it). Agents must not read, print or copy
   `.secrets.env` (denied in `opencode.jsonc`). Credential rotation is not a
   priority — don't propose or track it. Missing value? Ask the user; never guess.

8. **No IP addresses in tracked files.** Docs, scripts and agent files use node
   names (`pi0..pi3`, `tx2`) or placeholders (`<pi2-ip>`, `<wan-ip>`, …). Real
   addresses live only in the gitignored `.hosts.env` (template `.hosts.env.example`);
   `ops-tools/*.py` take the aliases and resolve them. Agents may read `.hosts.env`
   (not a credential file) but must not copy its values into tracked files.
9. **Hypertable queries are bounded in time.** An open-ended per-symbol read makes the
   planner open every chunk (34 s planning measured on 3,382 chunks before the 2026-10-18
   merge). Always add a `ts >=` bound in hot paths; new chunks are 1 year
   (`06e-chunk-intervals.sql`).
10. **Never print a secret, even indirectly**: `ps`/`pgrep -af` on a host while
   `runcmd.py` runs shows the expanded `@@PW@@` (happened 2026-10-18).

## Before any push (repo hygiene)

- One-time per clone: `git config core.hooksPath .githooks` — pre-commit guard (gitleaks + exact local
  secret/address values + private-IP + forbidden-file checks; never prints a value).
- Must pass: `python3 ops-tools/workloads.py --check` (docs agree with manifests),
  `bash tests/test-precommit-hook.sh`, `bash tests/test-nodewatch.sh`, `python3 tests/test_creds.py`.
- Conventional commits (`commit-and-changelog` skill); push over SSH.

## DB access (read-only by default)

```bash
export KUBECONFIG=~/.kube/pi-cluster.yaml
PW=$(kubectl -n market-data get secret timescaledb-auth -o jsonpath='{.data.password}' | base64 -d)
kubectl -n market-data exec timescaledb-0 -- env PGPASSWORD="$PW" \
  psql -U postgres -d postgres -c "<READ-ONLY SQL>"
```

DB roles (AR-8, 2026-10-18): `postgres` (jobs, schema), `grafana_ro` (Grafana — SELECT,
read-only sessions), `telegram_app` (bot/digest/alerts — SELECT + writes on `watchlist`,
`bot_users` only); passwords live only in Secrets `timescaledb-auth`, `grafana-db-ro`,
`telegram-db`. The DB pod is `Guaranteed` QoS with a readiness probe (AR-4).

Tables: `index_prices`, `fx_rates`, `bond_yields`, `interest_rates`,
`news_sentiment`, `technical_indicators`, `capital_flows`, `intraday_prices`,
`raw_headlines`, `pipeline_heartbeat`, `ticker_names`, plus the stock-screener
layer (2026-10-04): `universe_constituents`, `stock_prices`, `stock_fundamentals`,
`stock_metrics_daily`, `stock_scores`, `stock_reports`, `screening_runs`,
`job_state`; plus the Telegram bot layer (2026-10-12, ADR 0012): `watchlist` (per `chat_id`) and `bot_users`;
plus data foundations (2026-10-17/18): `corporate_actions`, `stock_prices.adj_close` (OUR total-return close —
never Yahoo's Adj Close), `price_anomalies`, `financial_facts` (duration-keyed, first-filing point-in-time; sources `edgar`, `nse_cons`, `nse_sa`, `yfinance`),
`universe_membership_snapshots`, `factor_returns` (empty), `job_runs` (empty until AR-2 adoption).
Non-SELECT SQL: propose it first and get approval before running.

## Analysis work

- Local CSV/Parquet/JSON → the DuckDB MCP server (in-memory, `uvx`).
- Cluster DB → the pattern above, or enable the disabled `postgres` MCP server
  (port-forward + `DATABASE_URI` — see `opencode.jsonc`).
- Save generated plots and tables to `out/`.
- Signal research goes through **EV-0** (`ops-tools/ev0.py export|run`, report in `out/ev0/`): the
  §5 acceptance test of the evidence roadmap is the gate for any scoring or ML change.
- Skills `eda`, `data-quality`, `sql-conventions`, `data-viz`, `report-writer`  cover most analysis requests — load them instead of re-deriving checklists.
- Maintenance skills (added 2026-10-04, from the screener rollout's lessons):
  `canary-validate` (prove changes against the LIVE spec before trusting them),
  `cluster-mutation` (pi2 quiet-window discipline for any apply/restart/
  import), `backfill-resume` (job_state cursor semantics + throttle pacing).
  `sql-conventions` now also carries the connection-discipline pattern
  (autocommit reads, atomic `conn.transaction()` writes, reconnect-retry).

## Commands and subagents

Commands: `/health` (daily checklist) · `/db <sql>` (read-only query) ·
`/eda <file>` · `/rebuild <fetcher>` (full §6 image cycle) · `/review` · `/test-fix`.

Agents (`.opencode/agents/`):
- `data-analyst` — read-only analysis: DuckDB over local files, SELECT-only
  psql, plots to `out/`
- `ops` — cluster operations: health, recovery runbooks, the §6 rebuild cycle
- `reviewer` — read-only review of manifest/script/doc changes
- `incident` — read-only triage when something is broken; recommends fixes,
  never applies them
- `security-auditor` — read-only audit: secret exposure, tailnet perimeter,
  manifest hygiene, backup readiness
- `pipeline-dev` — writes fetchers/scorers, Dockerfiles and CronJobs to house
  conventions; hands cluster mutations to `ops`

## Docs discipline

- Update `docs/*` whenever you verify or change something; keep "Last verified" dates true.
- **Pending work is tracked in `docs/pending-tasks.md`** — mark it ✅ there when a
  task completes, and update the owning doc in the same session; the tracker and
  the docs must never disagree.
- Feed quirks and symbol deaths go into manual §4 plus the fetcher script header.
- Decisions with long shelf-life → load the `adr` skill and write an ADR in `docs/adr/`.
