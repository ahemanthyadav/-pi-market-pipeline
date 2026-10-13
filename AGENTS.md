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
   fetcher code change = bump the tag in `cronjob.yaml` + the full §6 cycle.
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

Tables: `index_prices`, `fx_rates`, `bond_yields`, `interest_rates`,
`news_sentiment`, `technical_indicators`, `capital_flows`, `intraday_prices`,
`raw_headlines`, `pipeline_heartbeat`, `ticker_names`, plus the stock-screener
layer (2026-10-04): `universe_constituents`, `stock_prices`, `stock_fundamentals`,
`stock_metrics_daily`, `stock_scores`, `stock_reports`, `screening_runs`,
`job_state`; plus the Telegram bot layer (2026-10-12, ADR 0012): `watchlist` (per `chat_id`) and `bot_users`.
Non-SELECT SQL: propose it first and get approval before running.

## Analysis work

- Local CSV/Parquet/JSON → the DuckDB MCP server (in-memory, `uvx`).
- Cluster DB → the pattern above, or enable the disabled `postgres` MCP server
  (port-forward + `DATABASE_URI` — see `opencode.jsonc`).
- Save generated plots and tables to `out/`.
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
