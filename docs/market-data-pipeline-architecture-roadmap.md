# Market Data Pipeline — Architecture Review & Hardening Roadmap

> **Status:** Review notes / roadmap only.  
> **Current architecture:** Keep the existing production setup unchanged unless an item is explicitly promoted and tested.

## 1. Current Status

The Market Data Pipeline is live on the home k3s cluster.

### Completed

- TX2 DHCP reservation is **complete and user-confirmed (2026-10-03)**; host remains a
  DHCP client by design with the lease pinned to <tx2-ip>.
- TX2 remains at `<tx2-ip>`; the k3s agent continues to use `--node-ip <tx2-ip>`.
- Daily PostgreSQL backups are configured **and restore-verified**: timed drill
  2026-10-03 = `pg_restore` 2 s @ 388 KB dump, row counts matched (9076 = 9076).
  Reusable drill manifest: `manifests/timescaledb/restore-drill-job.yaml`.
- Unique constraints on all natural keys **applied 2026-10-03** (8 indexes incl.
  intraday_prices; see §3.3).
- Pipeline heartbeat **deployed 2026-10-03, v2 2026-10-03**: `pipeline-health`
  CronJob (01:45 UTC) writes per-feed freshness into `pipeline_heartbeat`
  (10 feeds incl. intraday).
- **Intraday fast-movers deployed 2026-10-03** (user request: gold/USDINR and
  similar more frequent): hourly `intraday-fetcher` — FX → `fx_rates`,
  gold/silver/oil/DXY → new `intraday_prices` hypertable; `ticker_names`
  reference table ships names for dashboard labels ("Nifty 50 (^NSEI)" style,
  browser-validated via Playwright).
- TimescaleDB remains on the TX2 SSD; Grafana remains pinned to pi3; Tailscale remains
  the remote-access mechanism; daily batch architecture unchanged.
- Note: commodities are **served by design** via the yfinance batch (GC=F/SI=F/CL=F →
  `index_prices`); `commodity_prices` stays empty intentionally. No separate commodity
  fetcher exists or is planned. Grafana alert rules are NOT drafted — they are the next
  step now that `pipeline_heartbeat` provides the alert source (need a notification
  channel decision first, e.g. Telegram).

## 2. Documentation Corrections Recommended

These are documentation-quality corrections and do not require an architecture redesign.

### 2.1 Idempotency wording — ✅ RESOLVED 2026-10-03

The wording concern was valid; the stronger guarantee has since been implemented.
Unique indexes now enforce every natural key at the DB level (§3.3), so even
concurrent double-writes cannot persist duplicates. Docs updated to:
"Logically idempotent via DELETE+INSERT, enforced by unique indexes."

### 2.2 Storage capacity wording — ✅ RESOLVED 2026-10-03

Docs now attribute capacity to the PV: "decades of headroom *within the 30 GiB PV*
(the binding constraint; sda4 has 148 GiB free if ever expanded)." For the record,
the "decades" claim survives the correction: at <100 KB/day of writes, even 30 GiB
outlasts the hardware.

### 2.3 CronJob health wording — ✅ RESOLVED (wording adopted)

Hedged wording adopted in the docs. A live example of why it matters: rates-fetcher's
CronJob object was recreated 2026-10-03 and had no scheduled fire at review time
(a manual validation job had run); blanket "all recent runs verified" would have
been wrong for that job until its first scheduled fire (23:20 UTC).

### 2.4 Node scheduling wording — ✅ RESOLVED (wording adopted)

Docs now state: ingestion jobs unpinned across pi1/pi2/pi3, pi2 kept light by policy,
workloads that must avoid pi2 use explicit node selection/toleration.

### 2.5 Grafana state — ✅ RESOLVED (wording adopted)

Docs corrected: Grafana is "configuration-provisioned with persistent local state on
pi3" (hostPath holds Grafana's sqlite — dashboard versions, users, future alerting
state). The earlier "stateless by design" phrasing overstated it.

### 2.6 Backup RTO — ✅ RESOLVED (measured, 2026-10-03)

No longer a target: the timed restore drill measured `pg_restore` at **2 seconds**
for the current 388 KB dump, with row counts verified against live (**stale as of 2026-10-10: dumps are ~165 MB — re-run the drill**). End-to-end
recovery remains bounded by human steps (<15 min). Re-run the drill quarterly or
after schema/backup changes (`manifests/timescaledb/restore-drill-job.yaml`).

## 3. Low-Risk Hardening

These can be introduced incrementally without changing the overall architecture.

### 3.1 Pipeline heartbeat — ✅ V1 DEPLOYED 2026-10-03

`pipeline_heartbeat(feed PK, last_check, last_data_ts, fresh, rows_total,
max_age_hours)` live. Written by the new `pipeline-health` CronJob (01:45 UTC,
after all jobs + backup): per-FEED freshness checks over 9 feeds; first validated
run 9/9 fresh. Detects missed CronJobs, stale feeds, dead sources; `fresh=false`
is the Grafana-alertable signal. Manifests: `manifests/health/`.

**v2 (per-JOB last_ok/rows_written/duration written by each fetcher):** deferred to
the next fetcher image rebuilds — v1 covers the detection goals without touching 9
working images.

### 3.2 Upstream guards — 🔶 V1 via health monitor

Staleness detection now runs daily (3.1). Two flavors remain for the next fetcher
rebuild cycle: (a) downstream jobs self-checking source freshness before computing
(sentiment/TA), and (b) input validation guards rejecting empty/short/malformed
upstream responses before destructive replacement. Alert-side, "no data" vs "real
zero" is distinguishable already via `last_data_ts` + `fresh`.

### 3.3 Database unique constraints — ✅ APPLIED 2026-10-03

All natural keys enforced (each index includes the hypertable partition column):
`(ticker, ts)` index_prices · `(pair, ts)` fx_rates · `(instrument, ts)` bond_yields
· `(rate_name, ts)` interest_rates · `(ticker, ts, indicator_name)`
technical_indicators · `(flow_type, segment, ts)` capital_flows ·
`(commodity, ts)` commodity_prices. Verified 0 pre-existing duplicates before
creation; schema applied via the ConfigMap-driven schema Job (`02-constraints.sql`).

**Deliberately excluded:** `news_sentiment` + `raw_headlines` — their writers are
INSERT-only (no DELETE), so a unique index would turn benign crash-recovery reruns
into job failures. Add together with ON CONFLICT clauses at the next scorer/fetcher
image rebuild.

## 4. Feed Improvements

After hardening:

1. ~~Deploy commodity fetcher when desired~~ **Resolved by design**: commodities ride
   in the yfinance batch (GC=F/SI=F/CL=F → `index_prices`, live since 2026-10-02);
   `commodity_prices` stays empty intentionally.
2. Complete/verify RBI manual data workflow.
3. Revisit India 10Y yield source.
4. Revisit Nifty 500 source.
5. Revisit stale Auto/FMCG index symbols.
6. Decide whether FDI/TIC remain manual/deferred.

No separate commodity fetcher exists; if a dedicated metals feed is ever wanted,
note the no-registry tax (build → tarball → import). Under `imagePullPolicy: Never`
+ unpinned scheduling, any new image must be imported on **all** schedulable workers
(pi1/pi2/pi3) — pinning to one node actually *reduces* the import burden.

## 5. Grafana Improvements

Alert rules are NOT drafted yet — but the prerequisite now exists: `pipeline_heartbeat`
(fresh flags per feed) is the alert source. Remaining work: pick a notification channel
(Telegram candidate; treat as deployment config, not code), then provision rules as
ConfigMap additions (no image rebuild needed).

Potential alerts:

- VIX threshold.
- Sentiment threshold.
- Large FII outflow.
- Stale index data.
- Missed pipeline heartbeat.
- Failed/missing daily feed.

Telegram contact-point configuration should be treated as deployment configuration rather than hard-coded application logic.

## 6. Data Model Evolution

### 6.1 Raw data layer

A raw/staging layer can eventually preserve upstream responses before normalization.

Benefits:

- Reprocessing.
- Debugging upstream changes.
- Auditing.
- Rebuilding derived datasets.

This is appropriately deferred for the current daily-batch workload.

### 6.2 Data classification

Future documentation should distinguish:

**Observed/source data**
- Index prices.
- FX.
- Commodities.
- Bond yields.
- Interest rates.
- Capital flows.
- Raw headlines.

**Derived data**
- News sentiment.
- Technical indicators.
- Derived gold/INR metrics.
- Future alert metrics.

This distinction will become increasingly useful as the data model grows.

## 7. AI / Intelligence Roadmap

Keep AI workloads separate from the TX2 data/edge role.

### TX2

Continue using TX2 for:

- TimescaleDB.
- CPU sentiment at current volume.
- Lightweight scheduled processing.
- k3s GPU runtime experiments where useful.
- Gazetteer headline extraction (shipped 2026-10-09, ADR 0010: `headline-ner`
  at 00:45 PDT — regex/psycopg only, no model).

### RTX 3090 workstation

Use a separate AI layer for future:

- Larger language models.
- Embeddings.
- News extraction.
- Event/entity extraction (the MODEL-based layer — v1 gazetteer extraction
  already runs on TX2, ADR 0010; this is spaCy/LLM-grade NER writing into the
  same tables with provenance).
- RAG.
- GraphRAG experimentation.
- Heavier batch inference.

Avoid moving large-model workloads onto the TX2.

## 8. GraphRAG

GraphRAG should remain deferred until there are actual relationship-oriented questions that justify it.

Potential future relationships:

```text
Company
  -> sector
  -> index
  -> news event
  -> sentiment
  -> capital flow
  -> price movement
```

First establish reliable historical data and useful entity/event extraction before introducing a graph layer.

## 9. Reliability / Operations Roadmap

Recommended order:

1. **TX2 DHCP reservation — ✅ DONE & user-confirmed 2026-10-03**
2. **Restore-test verification — ✅ DONE 2026-10-03** (timed drill: 2 s restore,
   counts verified; reusable `restore-drill-job.yaml`; re-run quarterly)
3. **Pipeline heartbeat — ✅ V1 DONE 2026-10-03** (`pipeline-health` CronJob, 9 feeds;
   per-job v2 lands with next fetcher rebuilds)
4. **Upstream guards — 🔶 V1 via health monitor** (fetcher-internal guards next rebuild)
5. **Database unique constraints — ✅ DONE 2026-10-03** (7 indexes; sentiment/headlines
   deferred to scorer rebuild with ON CONFLICT)
6. Feed improvements.
7. Grafana alerts (unblocked: heartbeat source exists; needs notification channel).
8. Raw-data layer.
9. Richer asset/data model.
10. News/event intelligence.
11. Historical analysis.
12. AI layer on RTX 3090.
13. GraphRAG where justified.
14. Streaming only if requirements emerge.
15. Hardware scaling only when capacity requires it.

## 10. Explicitly Do Not Change Yet

Keep the following architecture unchanged for the current workload:

- k3s.
- CronJobs.
- TimescaleDB.
- Grafana.
- Tailscale.
- TX2 as the database host.
- Pi workers.
- CPU FinBERT sentiment.
- Native ARM64 builds.
- Tarball-based image distribution.
- Lightweight k3s control plane.
- Daily batch scheduling.

Avoid introducing solely for theoretical scalability:

- Kafka.
- Airflow.
- Argo/Tekton.
- Longhorn/OpenEBS.
- Loki.
- Citus.
- Distributed PostgreSQL.
- Large Kubernetes operators.

## 11. Security Follow-ups

The current tailnet-only design and lack of inbound port exposure should remain.

Future hardening:

- Remove stale router UDP/51820 forwarding.
- Avoid exposing Grafana directly to the public Internet.
- Consider off-site encrypted backups.

Credentials live in the gitignored `.secrets.env` (ops manual §10); rotating them is
not a priority. Keep services inside the trusted LAN/tailnet environment.

## 12. Overall Assessment

The current architecture is appropriate for the present workload:

- Daily market-data batch processing.
- Approximately 9k index rows.
- Hundreds of headlines per day.
- CPU sentiment processing.
- Single-user Grafana.
- Small k3s cluster.
- TX2-backed TimescaleDB.
- Tailscale-only remote access.

The recommended path is **incremental hardening rather than architectural replacement**.

Status after the 2026-10-03 hardening pass: TX2 DHCP reservation confirmed; restore
path measured (2 s); unique constraints enforcing all natural keys; heartbeat v2
monitoring all 10 feeds. **Intraday deploy (same day):** hourly fast-movers
(gold/silver/oil/DXY + 10 FX pairs) via `intraday-fetcher`, with a `ticker_names`
reference table giving dashboards named ticker labels — all browser-validated.
Next practical items: Grafana alert rules (notification channel decision), RBI
feed hunt, fetcher-internal guards + per-job heartbeat at the next image
rebuilds, and the standing security items (pi0 → tailnet, dead port-forward).
