# Stock Screener & Daily Analysis — Implementation Plan
### Universe: Nifty 500 + S&P 500 · maximum-history fundamentals · balanced screening · mixed sources · AI reports for the shortlist

> **Status:** proposed / not started (2026-10-03). Everything below is designed against the
> live architecture in `market-data-architecture.md` — no existing table, CronJob or
> pattern is replaced; all changes are additive and staged with canaries.
> Companion docs: ops manual (runbooks + image build cycle), roadmap (hardening),
> finds & projects (capacity facts this plan relies on).
> Repo root for all paths: `projects/marketdata/`.
> **Role:** this is the **v1 build order**. Target architecture for the full
> fundamental-analysis layer (security master, sector-relative 6-component scoring,
> style lenses, market-regime layer): `nifty500_sp500_fundamental_analysis_implementation_plan.md`.
> v1 adopts that document's key decisions up front: security-master fields
> (ISIN/CIK + membership dates), point-in-time fundamentals (`filing_published_at`),
> **SEC EDGAR company-facts as the US fundamentals source** (yfinance = NSE leg /
> interim), and **maximum history — no 10-year cap** (backfill as deep as each source
> reaches; see §2.7 and §10).

---

## 1. Goal & scope

Daily end-of-day analysis of every constituent of **Nifty 500 (~500)** and
**S&P 500 (~503)**: ingest prices + fundamentals, compute derived metrics, score each
stock with a **balanced multi-factor screen**, rank, and generate an **AI-assisted report
for the shortlist only**.

In scope: universe management, daily price ingestion, weekly fundamentals ingestion,
maximum-history backfill (prices as deep as Yahoo holds; fundamentals as deep as
EDGAR/yfinance reach), metrics, scoring,
shortlist reports, health monitoring, validation. Out of scope (unchanged): existing
index/FX/yields/news/sentiment pipeline, dashboards for existing feeds, any streaming.

## 2. Design constraints (what this plan must not break)

1. **pi2 fragility** — additive CronJobs only, tiny job-history limits, staggered
   schedules, no API-watch controllers. New pods ≤ 1 Gi RAM, run on pi1/pi3.
2. **TX2 as sole DB host** — all new tables live in the existing TimescaleDB
   (30 GiB PV, decades of headroom at this write rate). No new DB, no HA ambition.
3. **`index_prices` is off-limits for stocks** — ta-compute iterates every ticker in it
   (find F16); 1000 stocks would explode its daily compute on a 1 GB Pi. Stocks get
   their own hypertables.
4. **No registry** — every new image follows the established TX2-native build →
   tarball → `ctr import` (pi2 detached) → `apply` → `create-job` validate cycle.
5. **Idempotency everywhere** — row-level DELETE+INSERT keyed on natural keys +
   unique indexes; reruns and crashes never duplicate (design rule §1 of the
   architecture doc).
6. **Yahoo rate limits are real** — chunked fetches with sleeps, WARN-tolerant
   per-symbol failure, resumable state, no intraday ambitions.
7. **Honest sourcing, maximum history** — no fixed-year cap: backfill as deep as each
   source's structured data reaches (EDGAR ~2009→, older US history = unstructured
   parsing = future project; yfinance statements ~4-6y; NSE shallower). The schema holds
   whatever arrives; history accumulates forward. Paid depth (FMP/SIMFIN) is an
   optional plug-in, not a dependency.

## 3. Universe management

### 3.1 Sources

| Universe | Source | Fallback |
|---|---|---|
| S&P 500 | Wikipedia "List of S&P 500 companies" table (stable URL, updated promptly; includes **SEC CIK** — captured for the EDGAR adapter) | committed CSV `manifests/stock-screener/data/sp500.csv` (manual refresh) |
| Nifty 500 | **NSE archives CSV** (2026-10-04: niftyindices.com now serves a JS HTML shell at the old CSV path): `https://archives.nseindia.com/content/indices/ind_nifty500list.csv` — carries Company Name, Industry, Symbol, Series, ISIN | committed CSV `manifests/stock-screener/data/nifty500.csv` (manual refresh) |

Yahoo symbol mapping: S&P = native (`AAPL`); NSE = `SYMBOL.NS` (`RELIANCE.NS`).
Known trap (find F11): some Yahoo NSE symbols die silently — the validator treats
"no data for symbol" as WARN, and 3 consecutive misses auto-deactivates the symbol
(see §11).

### 3.2 Refresh & churn

- Weekly **Sundays 09:00 UTC** (`universe-refresh`, one job, both lists, ~1 min).
- Upsert into `universe_constituents`; symbols leaving the index flip `active=false`
  (rows stay — historical analysis continues, no deletes).
- Each run also upserts symbol → `ticker_names` (names everywhere, consistent with
  the Indices dashboard pattern).

## 4. Data sources — "mixed"

| Data | Primary | Secondary/depth | Cadence |
|---|---|---|---|
| Daily OHLCV | Yahoo via `yfinance` (chunked, `interval=1d`) | — | daily |
| Constituents | Wikipedia + NiftyIndices CSV | committed CSVs | weekly |
| Fundamentals (statements + ratios) | **US: SEC EDGAR company-facts XBRL** (CIK from constituents; structured history ~2009→, official + free — adopted from the target architecture). NSE / interim: `yfinance` statements + `ticker.info` ratios | optional later: FMP/SIMFIN depth via the `source` column | weekly rolling |
| Macro context | existing FRED feed (DFF, DGS) | — | existing |
| News sentiment for reports | existing `raw_headlines` → FinBERT `news_sentiment` | — | existing |

Fundamentals metric strings ingested (long/narrow — resilient to mixed sources):
`total_revenue`, `net_income`, `operating_income`, `ebitda`, `total_debt`,
`shareholder_equity`, `free_cash_flow`, `eps`, `pe`, `pb`, `ev_ebitda`, `roe`,
`operating_margin`, `market_cap`. Period-end rows from statements; "current ratio"
rows (pe/pb/…) stamped with the fetch date.

## 5. Schema — `06-stock-screener.sql` (new ConfigMap key, schema Job rerun)

```sql
-- Universe (security-master fields adopted from the target architecture)
CREATE TABLE IF NOT EXISTS universe_constituents (
  universe   TEXT NOT NULL,            -- 'SP500' | 'NIFTY500'
  symbol     TEXT NOT NULL,            -- Yahoo symbol
  name       TEXT NOT NULL,
  sector     TEXT,
  isin       TEXT,                     -- NiftyIndices CSV carries ISIN
  cik        TEXT,                     -- Wikipedia S&P table carries SEC CIK
  exchange   TEXT,                     -- NSE | NASDAQ | NYSE
  currency   TEXT,                     -- INR | USD
  active     BOOLEAN NOT NULL DEFAULT TRUE,
  first_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (universe, symbol)
);

-- Daily stock OHLCV (max-history: US veterans reach 25-35y on Yahoo;
-- ~4-6M rows ≈ ~0.6-1 GB — comfortably inside the 30 GiB PV)
CREATE TABLE IF NOT EXISTS stock_prices (
  symbol TEXT NOT NULL, ts TIMESTAMPTZ NOT NULL,
  open DOUBLE PRECISION, high DOUBLE PRECISION,
  low DOUBLE PRECISION, close DOUBLE PRECISION, volume BIGINT
);
SELECT create_hypertable('stock_prices', 'ts', if_not_exists => TRUE);
CREATE UNIQUE INDEX IF NOT EXISTS ux_stock_prices_symbol_ts ON stock_prices (symbol, ts);

-- Fundamentals: long/narrow, source-tagged (mixed-source design), point-in-time
CREATE TABLE IF NOT EXISTS stock_fundamentals (
  symbol TEXT NOT NULL,
  ts TIMESTAMPTZ NOT NULL,             -- period END (statements) or fetch date (ratios)
  metric TEXT NOT NULL,
  value DOUBLE PRECISION,
  source TEXT NOT NULL DEFAULT 'yfinance',   -- 'yfinance' | 'edgar' | ...
  filing_published_at TIMESTAMPTZ,      -- when the market could FIRST know this fact;
                                        -- historical views must respect it (no lookahead)
  PRIMARY KEY (symbol, ts, metric, source)
);

-- Computed daily metrics (see §6)
CREATE TABLE IF NOT EXISTS stock_metrics_daily (
  symbol TEXT NOT NULL, ts TIMESTAMPTZ NOT NULL,
  metric TEXT NOT NULL, value DOUBLE PRECISION
);
SELECT create_hypertable('stock_metrics_daily', 'ts', if_not_exists => TRUE);
CREATE UNIQUE INDEX IF NOT EXISTS ux_stock_metrics_symbol_ts_metric
  ON stock_metrics_daily (symbol, ts, metric);

-- Daily factor + composite scores (wide: one row per symbol per day)
CREATE TABLE IF NOT EXISTS stock_scores (
  symbol TEXT NOT NULL, ts TIMESTAMPTZ NOT NULL, universe TEXT NOT NULL,
  value_score DOUBLE PRECISION, quality_score DOUBLE PRECISION,
  growth_score DOUBLE PRECISION, momentum_score DOUBLE PRECISION,
  risk_score DOUBLE PRECISION,
  composite DOUBLE PRECISION, rank INT, coverage DOUBLE PRECISION,
  PRIMARY KEY (symbol, ts)
);
SELECT create_hypertable('stock_scores', 'ts', if_not_exists => TRUE);

-- Shortlist reports (markdown)
CREATE TABLE IF NOT EXISTS stock_reports (
  symbol TEXT NOT NULL, ts TIMESTAMPTZ NOT NULL,
  report_md TEXT NOT NULL,
  PRIMARY KEY (symbol, ts)
);

-- Screener run log + resumable cursor for long fetches
CREATE TABLE IF NOT EXISTS screening_runs (
  ts TIMESTAMPTZ NOT NULL, universe TEXT, n_scored INT,
  n_shortlisted INT, params_hash TEXT,
  PRIMARY KEY (ts, universe)
);
CREATE TABLE IF NOT EXISTS job_state (
  job_name TEXT PRIMARY KEY, last_key TEXT, updated_at TIMESTAMPTZ DEFAULT now()
);
```

Idempotency: constituents/`stock_reports`/`screening_runs` upsert; prices/metrics
DELETE+INSERT per `(symbol, ts[, metric])`; fundamentals DELETE+INSERT per
`(symbol, ts, metric, source)`.

## 6. Derived daily metrics (computed in `stock-metrics`)

Per active symbol, from `stock_prices` (all 252-day windows are trading days):

| metric | formula |
|---|---|
| `ret_1m/6m/12m` | `close / close_lag(n) − 1` (n = 21/126/252 bars) |
| `vol_180d` | `std(daily_returns, 180) × sqrt(252)` |
| `max_dd_252d` | `min(P_t / cummax(P_t) − 1)` over 252 bars |
| `pos_52w` | `(close − min252) / (max252 − min252)` |
| `sma50_ratio / sma200_ratio` | `close / SMA(50|200)` |
| `dol_vol_20d` | `mean(close × volume, 20)` — liquidity filter |
| `rev_cagr_3y` | `(rev_t / rev_{t−3y})^(1/3) − 1` — from fundamentals |
| `eps_growth_yoy` | `eps_t / eps_{t−4q} − 1` |

Missing window (new listing) → metric omitted; coverage policy in §7.3.

## 7. Scoring — balanced composite

### 7.1 Cross-sectional percentile method

For each metric, **within each universe, per day**: winsorize at the 1st/99th
percentile → convert to a percentile rank `P ∈ [0,1]` (higher = better after
direction handling: for "lower is better" metrics like PE, rank `−metric`).

### 7.2 Factor definitions (mean of member percentiles)

| Factor | Components | Weight |
|---|---|---|
| **VALUE** | `P(−pe)`, `P(−pb)`, `P(−ev_ebitda)`, `P(fcf_yield = fcf/market_cap)` | **0.25** |
| **QUALITY** | `P(roe)`, `P(operating_margin)`, `P(−de = −total_debt/equity)`, `P(gross_profitability = (rev−cogs)/assets)`* | **0.25** |
| **GROWTH** | `0.5·P(rev_cagr_3y) + 0.5·P(eps_growth_yoy)` | **0.20** |
| **MOMENTUM** | `P(ret_6m)`, `P(ret_12m)`, `P(pos_52w)`, `P(sma200_ratio)` | **0.20** |
| **RISK** | `P(−vol_180d)`, `P(−max_dd_252d)` | **0.10** |

\* gross profitability falls back to `operating_margin` when COGS unavailable.

**Composite** = `(0.25·VALUE + 0.25·QUALITY + 0.20·GROWTH + 0.20·MOMENTUM + 0.10·RISK) × 100`
→ `rank` per universe (1 = best). "Balanced" = no factor above 25%, so no
deep-value or pure-momentum tilt; the factor columns keep the tilt auditable.

### 7.3 Missing data policy (fundamentals will be patchy, especially NSE)

- Missing component → impute that percentile as **0.50 (neutral)**.
- `coverage` = share of non-imputed components.
- **Shortlist eligibility:** `coverage ≥ 0.60` AND `dol_vol_20d` above the universe's
  10th percentile (liquidity floor). Below that → scored but flagged
  `insufficient_data`, excluded from ranking.

### 7.4 Shortlist

Top **25 per universe** by composite (50 stocks total). Stored per day — the 30-day
history of shortlists is itself signal (persistent members vs. churn).

## 8. Shortlist reports — "AI report generation"

**v1 (deterministic template + existing FinBERT):** `stock-report` job renders, per
shortlisted symbol, a markdown report from the tables:

- Header: name/symbol/universe/rank/composite + factor bar summary.
- Valuation block: PE/PB/EV-EBITDA/FCF-yield vs universe medians.
- Quality block: ROE, margins, D/E, 3y revenue CAGR, EPS growth.
- Price block: 1m/6m/12m returns, 52w position, vol, max drawdown.
- **News block (the AI part):** join `news_sentiment` by symbol/ticker_relevance
  (same-day ± 3 days) — mean sentiment, most positive/negative headlines; the
  existing FinBERT CronJob already scores every headline daily — no new model needed.
- One combined daily digest (top 10 lines) written to `stock_reports` with
  `symbol='__digest__'`.

**Pluggable LLM narration (off by default):** a `report_llm.py` hook that can call the
3090 box or an external API later (roadmap Tier 3; CGNAT permits outbound APIs).
v1 ships without it — templated text + FinBERT is honest, reproducible, and needs
zero new compute.

## 9. CronJobs (all namespace `market-data`, images node-local, `Never` pull)

| CronJob | Schedule (UTC) | Runs on | Image | Writes | Est. runtime |
|---|---|---|---|---|---|
| `universe-refresh` | `0 9 * * 0` (Sun) | Pi worker | `local/screener:v8` | `universe_constituents`, `ticker_names` | ~2 min |
| `stock-prices` | `30 23 * * *` | Pi worker | `local/screener:v8` | `stock_prices` | ~15-30 min (1000 syms, chunks of 100, 3 s sleep) |
| `stock-fundamentals` | `0 6 * * 6` (Sat) | Pi worker | `local/screener:v8` | `stock_fundamentals`, `job_state` | ~45-90 min, resumable via `job_state` cursor |
| `stock-metrics` | `0 2 * * *` | Pi worker | `local/screener:v8` | `stock_metrics_daily` | ~5-10 min |
| `stock-screener` | `15 2 * * *` | Pi worker | `local/screener:v8` | `stock_scores`, `screening_runs` | ~2-5 min |
| `stock-report` | `30 2 * * *` | Pi worker | `local/screener:v8` | `stock_reports` | ~2-5 min |
| `backfill-stock-prices-max` | one-shot Job (manual) | Pi worker | same as `stock-prices` (env `BACKFILL=max`) | `stock_prices` | ~30-60 min, resumable |
| `backfill-stock-fundamentals` | one-shot Job (manual) | Pi worker | same as fundamentals (env `BACKFILL=1`) | `stock_fundamentals` | hours; resumable across runs |

Scheduling rationale: `stock-prices` 23:30 slots in after `rates-fetcher` 23:20 and
before `news-fetcher` 23:45 — a fetch pod overlapping news costs nothing. Metrics →
screener → report run 02:00-02:35, after `pg-backup` 01:30 (that day's dumps capture
yesterday's scores — fine) and clear of the 00:15 sentiment RAM window on the TX2
(jobs run on Pis anyway; only their DB writes touch the TX2).

**Health (pipeline-health v3):** add feeds — `stock_prices` (max age 48 h),
`stock_fundamentals` (192 h), `stock_scores` (48 h). Same build/import cycle, image
tag `v3`.

**As-built (2026-10-04):** implemented as a SINGLE toolkit image — `local/screener:v7`
(v7 = v1→v7 lineage) containing all six scripts; each CronJob picks its script via
`command:`. One image = one no-registry build/import cycle instead of six.
Updated runtimes: prices daily ~8 min (chunk 50); fundamentals weekly ~35-60 min
resumable; backfill prices per-symbol (multi-symbol max-range chunks stall on
Yahoo throttling — find F25), ~36 s/symbol.

Manifest layout (as built): `manifests/stock-screener/scripts/` (all six .py +
Dockerfile — the build context) · `cronjobs.yaml` (6 CronJobs) · `backfills.yaml`
(2 one-shot Jobs).

## 10. Backfill plan

1. **Prices — maximum history** — chunked `yf.download(symbols, period='max', interval='1d')`,
   50 symbols/chunk, per-(symbol, ts) DELETE+INSERT (resumable by nature: rerun
   skips nothing but harms nothing; the `job_state` cursor avoids refetch).
   Expect some NSE symbols to have short history (recent listings) and some to be
   dead on Yahoo — WARN-log both. US veterans typically deliver 25-35 years.
2. **Fundamentals history** — as deep as each source reaches: **EDGAR company-facts
   gives US history back to ~2009 structured** (older 10-K/10-Q history exists as
   unstructured text — a future parsing project, flagged not blocked); yfinance
   statements give ~4y (US) / ~4y (NSE). Ingest what exists; the schema holds
   whatever arrives; forward accumulation extends it daily. Optional FMP free tier
   (250 req/day) can add US depth later via the same table + `source` column.
3. **Backfills run on the established quiet-window rules** (evenings/weekend,
   one job at a time) — they're fetch+DB-write pods, not API-server load.

## 11. Validation (per stage — follows the existing job-validation pattern)

| Stage | Check | Pass bar |
|---|---|---|
| Universe | counts per list; diff vs previous week | SP500 ≥ 495, NIFTY500 ≥ 490; churn WARN if > 20 changes |
| Prices (daily) | `count(DISTINCT symbol)` with today's row | ≥ 95% of active universe; per-symbol 3-day miss streak → auto `active=false` + WARN |
| Prices (backfill) | per-symbol bar count vs Yahoo's own max range; gap % | US veterans ≥ 5000 bars; total gaps < 5% |
| Fundamentals | rows per symbol; metric coverage | ≥ 80% of universe with `pe` + `roe`; WARN list printed |
| Metrics | row count = priced symbols × metric count | exact; NULLs only where window missing |
| Screener | distribution sanity + spot checks | composite ~uniform in [0,100]; known cheap stock (e.g., a low-PE name) ranks > 60th pct on VALUE; coverage ≥ 0.6 for ≥ 90% of universe |
| Reports | digest renders; sentiment join non-empty | ≥ 20/50 shortlist reports; news block present when headlines exist |
| Health | `pipeline_heartbeat` rows | 3 new feeds fresh; alert-ready |

Every new job gets a `kubectl create job --from=cronjob/<name>` canary before its
schedule goes live (existing §6 ops-manual cycle), and a `*-validate` DB query block
in the ops manual.

## 12. Capacity impact (fits — verified against finds §1.3)

- **DB:** +252k price rows/year (+4-6M once max-history backfill lands) ≈ 0.6-1 GB in a 30 GiB PV;
  scores/metrics another ~1.5M rows/year ≈ ~100 MB. Timescale compression optional
  later.
- **RAM:** each new pod ≤ 1 Gi limit on Pi workers; screener/report work on ≤ 1000-row
  DataFrames — trivial. TX2 unaffected beyond DB writes (2 Gi limit unchanged).
- **pi2:** +7 small CronJob objects (tiny etcd footprint); fetch runs are worker pods.
- **Runtime budget:** ~35 min evening fetch + ~20 min early-morning compute; weekly
  fundamentals ≤ 90 min resumable.

## 13. Rollout (incremental phases; each ends validated + documented)

| Phase | Deliverable | Status (2026-10-04) | Risk | Rollback |
|---|---|---|---|---|
| A | `06-stock-screener.sql` via schema Job | ✅ done (8 tables + indexes) | none | drop new tables (they're new) |
| B | `universe-refresh` + names sync | ✅ done — 503 SP500 + 495 NIFTY500 active; S&P leg parses Wikipedia via lxml.html (pd.read_html proved unreliable); NSE list via archives.nseindia.com | none | suspend cronjob |
| C | `stock-prices` daily | ✅ done — 966/998 fetched, 4.3k rows, connection-drop fix proven (chunk mode, 5d window) | rate-limit WARNs | suspend; `active` flags untouched |
| D | max-history price backfill | ✅ done (2026-10-04, ~9h unattended) — **6.34M rows / 997 symbols** (920 fetched fresh, 7 dead-symbol WARNs); per-symbol mode (chunk mode stalls: Yahoo throttles multi-symbol max-range into silent retries); `job_state`-resumable | long runtime only | harmless reruns |
| E | `stock-fundamentals` | ✅ done — EDGAR 179k facts / 496 S&P companies (~15-20y history, point-in-time), yfinance 32k / 997 symbols; units-nesting + yfinance-1.7 row-name + cursor-wrap fixes (image v7) | Yahoo NSE patchiness | suspend; gap documented |
| F | `stock-metrics` + `stock-screener` | ✅ chain validated end-to-end (2026-10-09, image v8): **997 scored (494 NIFTY + 503 SP500), 888 eligible, 50 shortlisted, avg coverage 0.91/0.98**. v7 bug fixed in v8: SP500 leg died at the NIFTY→SP500 boundary every night (implicit-transaction connection drop — ops manual §8); screener now on the house connection pattern (autocommit reads, atomic `conn.transaction()` writes, leg-level reconnect-retry). Also fixed in v8: `latest_metrics` now `ORDER BY ts DESC` (multi-vintage metric rows could resolve nondeterministically) | math errors → §11 spot checks | suspend both; prices remain useful |
| G | `stock-report` + FinBERT join + digest | ✅ done — 25 reports + `__digest__` validated (v6 restructured onto the house connection pattern after the v1 loop-death bug). v8 fix: shortlist query now takes each symbol's LATEST scores row (v1-v7 had no ts filter → union of all historical top-25s: 51 NIFTY reports instead of 25+25); validated 2026-10-09: 25+25 reports + digest per day | none | suspend |
| H | health v4 (13 feeds); Grafana screener dashboard; docs | 🔶 health done; docs updated (ops manual §8 recurrence + §4 quirk row, 2026-10-09); dashboard built against full-quality scores (2026-10-09) | none | revert configmap |

**Deployed image lineage:** `local/screener:v1→v8` (v2 universe fix, v3 per-symbol
backfill, v4 EDGAR+yfinance fixes, v5 cursor-clear, v6 report rewrite, v8 screener
connection-pattern fix + report today's-shortlist fix) — single
toolkit image, one no-registry cycle per fix. **Ops lessons in the manual §8:**
live CronJob tags must be re-APPLIED after sed bumps; DB `args:` not `command:`;
TX2 carries a `gpu=true:NoSchedule` taint, so the toolkit image is only needed on
pi1/pi2/pi3 (verified 2026-10-09 — TX2's containerd has no screener images, by
design).

Sequencing note: A→B same evening; C after B validates; D on a weekend; E the
following week (lets F build on real fundamentals); F→G next evening; H last.

## 14. What this deliberately does NOT change

- The 13 pre-screener CronJobs, their schedules, and tables (`index_prices`, `fx_rates`,
  `intraday_prices`, `bond_yields`, `interest_rates`, `news_sentiment`,
  `technical_indicators`, `capital_flows`, `raw_headlines`, `ticker_names` — only
  appended to).
- ta-compute and its `index_prices` contract; the FinBERT scorer; Grafana provisioning
  for existing dashboards; backup job (dumps naturally include new tables); Tailscale
  posture; the no-registry image pipeline.
- The 30 GiB PV (no expansion needed at these volumes).

## 15. Open decisions (defaults chosen, flag to override)

1. Shortlist size: **25 per universe** (50 total) — tunable via env.
2. Liquidity floor: universe 10th percentile of 20d dollar volume.
3. FMP free tier for US fundamentals depth: **deferred** (schema ready via `source`).
4. LLM narration hook: **off** until the 3090 layer or an API decision (roadmap Tier 3).
5. Optional Timescale columnstore compression on `stock_prices` after backfill lands.
