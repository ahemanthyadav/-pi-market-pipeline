# Data foundations — schema + writer draft (G-1, G-2a, EV-2, EV-9, factor returns)

> **Status: DRAFT, written 2026-10-10. Nothing here is applied.** No ConfigMap, manifest,
> script or tracker has been edited. Read-only queries against the live DB were used to
> verify the findings in §1. Follows the `migration` skill: additive only, idempotent DDL,
> ConfigMap workflow, written rollback.
> Companion docs: `evidence-based-signals-roadmap.md`, `stock-screener-implementation-plan.md` §16.

## 1. Verified findings that shape the design (2026-10-10, live DB)

| # | Finding | Evidence | Consequence |
|---|---|---|---|
| F-1 | **EDGAR quarterly values are year-to-date, not per quarter.** `edgar_facts()` keys on `(metric, end)` and ignores `start`/duration. | MSFT `net_income`: Sep = 27.75 bn (3 mo), Dec = 66.21 (6 mo), Mar = 97.98 (9 mo), Jun = 133.75 (12 mo). Same pattern for flow metrics generally; cash-flow lines are YTD by SEC rule. | `annual_series()` keeps "max period end per calendar year", so for non-December fiscal years it can compare a 12-month figure with a 6-month one. Live revenue CAGR / EPS growth / FCF yield are probably distorted for those companies (**not yet measured across the universe**). Blocks EV-9…EV-15. |
| F-2 | **`filing_published_at` is the latest re-filing, not the first release.** `if filed > best[key][1]` picks the newest filing that repeats the fact as a comparative. | MSFT FY2024 (period ending 2024-06-30) shows `filed = 2026-07-29`; the real 10-K was filed mid-2024. | The point-in-time guarantee in the screener (`filing_published_at <= as_of`) is false for history: a backtest would think FY2024 became known two years late. Today's live scoring is unaffected only because it takes "latest". |
| F-3 | **yfinance statement rows get `filing_published_at` reset to the fetch date on every weekly run** (DELETE+INSERT at the same key). | All yfinance statement rows currently show `min_pub = max_pub = 2026-10-04` — one run so far. | After the next weekly run the "first seen" date for India is gone. This, not the ratios, is the real EV-2 problem. Ratio rows are keyed by fetch date (`ts`) so they already accumulate; verify after the second weekly run. |
| F-4 | `stock_fundamentals.py` line 228 uses an undefined name `failed` (`done + failed >= len(universe)`). | grep: `failed` is never assigned in `main()`. | Will raise `NameError` after the last symbol in `BACKFILL=1` mode, before the cursor-clear and the `FUNDAMENTALS-OK` line. The cursor shows cleared on 2026-10-04, so the deployed image may differ from the repo file — **check the live script before the next weekly run**. Fix in the same release. |
| F-4a | **F-4 is live in the deployed image (strongly indicated).** | Cursor was not cleared after the 10-04 full pass; the 10-10 13:00 UTC Job (20 s) logged only "pass already complete — cursor cleared"; `pe` still has a single `ts` (10-04). | No fundamentals refresh happened this week; 10-17 will do a full pass and fail at the end again. |
| F-1a | **F-1 measured**: median screener revenue CAGR −17.8 % vs like-for-like YoY +8.8 % (477 S&P symbols); 400 understated > 10 pp, 351 sign-flipped. | SQL emulating `annual_series` (2026-10-10). | Live `growth_score`, EPS growth and FCF yield are materially distorted, not marginally. Answers open decision 3 below: fix, do not wait. |
| F-5 | Yahoo history is already fetched with `auto_adjust=False`, so the response contains `Adj Close`, `Dividends`, `Stock Splits`; `write_symbol()` discards all three. | `stock_prices.py` lines 119–120, 58–64. | G-1 needs **no new feed** — keep what is already downloaded. |
| F-6 | 12 of 503 S&P symbols have no EDGAR rows (e.g. `AAPL`, `MSFT` exists, `AAPL` does not). | `edgar` rows cover 489–491 symbols per metric; `AAPL` query returned 0 rows. | Check `universe_constituents.cik` for the gap before relying on US coverage. |

## 2. DDL — new ConfigMap key `09-data-foundations.sql`

All additive; every statement idempotent. Existing readers (screener, Telegram bot, dashboards)
keep working unchanged.

```sql
-- G-1: corporate actions + our own total-return price. ------------------------
ALTER TABLE stock_prices ADD COLUMN IF NOT EXISTS adj_close DOUBLE PRECISION;
-- adj_close = OUR OWN total-return series (raw close x cumulative dividend/split
-- factor, §3.1) — NOT Yahoo's Adj Close, which is rewritten backwards on every
-- new dividend and would go stale in rows the 5-day daily job never touches.

CREATE TABLE IF NOT EXISTS corporate_actions (
  symbol      TEXT NOT NULL,
  ts          TIMESTAMPTZ NOT NULL,           -- ex-date
  action      TEXT NOT NULL,                  -- 'dividend' | 'split'
  value       DOUBLE PRECISION NOT NULL,      -- dividend per share, or split ratio (new:old)
  source      TEXT NOT NULL DEFAULT 'yfinance',
  detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (symbol, ts, action, source)
);

CREATE TABLE IF NOT EXISTS price_anomalies (
  symbol      TEXT NOT NULL,
  ts          TIMESTAMPTZ NOT NULL,
  kind        TEXT NOT NULL,                  -- 'jump_gt_40pct' | 'history_restated' | 'bad_bar'
  detail      TEXT,
  ret         DOUBLE PRECISION,
  status      TEXT NOT NULL DEFAULT 'open',   -- 'open' | 'explained' | 'refetched'
  detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (symbol, ts, kind)
);

-- G-2a / EV-1: append-only weekly membership snapshot. ------------------------
CREATE TABLE IF NOT EXISTS universe_membership_snapshots (
  universe      TEXT NOT NULL,
  snapshot_date DATE NOT NULL,
  symbol        TEXT NOT NULL,
  sector        TEXT,
  PRIMARY KEY (universe, snapshot_date, symbol)
);

-- EV-2 / EV-9 / EV-15: point-in-time facts, append-only on change. -------------
-- Replaces nothing yet; stock_fundamentals stays as the "latest" view for current
-- readers. One row per (period, filing) and ONLY when the value differs from the
-- previous filing's value for that period (comparatives repeated unchanged are
-- dropped) -> first release + genuine restatements.
CREATE TABLE IF NOT EXISTS financial_facts (
  symbol        TEXT NOT NULL,
  source        TEXT NOT NULL,                -- 'edgar' | 'yfinance'
  metric        TEXT NOT NULL,
  period_end    DATE NOT NULL,
  period_start  DATE,                         -- NULL for balance-sheet (instant) facts
  duration_days INT,                          -- end - start; ~91 / 182 / 273 / 365; NULL = instant
  value         DOUBLE PRECISION NOT NULL,
  filed         DATE NOT NULL,                -- EDGAR 'filed'; yfinance = first date WE observed it
  form          TEXT,                         -- '10-K' | '10-Q' | NULL
  accession     TEXT,                         -- EDGAR accn, provenance
  observed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (symbol, source, metric, period_end, duration_days, filed)
);
CREATE INDEX IF NOT EXISTS idx_financial_facts_pit
  ON financial_facts (symbol, metric, period_end, duration_days, filed);

-- Standard factor returns, to test whether a signal is more than known factors.
CREATE TABLE IF NOT EXISTS factor_returns (
  market  TEXT NOT NULL,                      -- 'US' | 'IN'
  factor  TEXT NOT NULL,                      -- 'MKT_RF' | 'SMB' | 'HML' | 'RMW' | 'CMA' | 'MOM' | 'RF'
  ts      DATE NOT NULL,                      -- month end (monthly) or day (daily)
  freq    TEXT NOT NULL,                      -- 'M' | 'D'
  value   DOUBLE PRECISION NOT NULL,          -- percent, as published
  source  TEXT NOT NULL,
  PRIMARY KEY (market, factor, freq, ts)
);
```

Plain tables, not hypertables (all are small): `corporate_actions` ≈ 1,000 symbols × ~100
dividends ≈ ≤ 100 k rows; `universe_membership_snapshots` ≈ 1,000 × 52/yr ≈ 52 k rows/yr;
`financial_facts` first-release + restatements only ≈ a few hundred thousand rows
(estimate — confirm after the canary).

### Rollback
`DROP TABLE` the five new tables and `ALTER TABLE stock_prices DROP COLUMN adj_close`. Nothing
reads them until the writers ship, so "leave empty and stop using" is the safe reverse. Dropping
needs explicit approval per the migration skill.

## 3. Writer changes (one release, `local/screener:v9` — full §6 cycle)

### 3.1 `stock_prices.py` (G-1)
1. `write_symbol()`: also read `Dividends` and `Stock Splits` from the frame already in hand;
   upsert non-zero values into `corporate_actions` (DELETE+INSERT per `(symbol, ts, action, source)`).
2. **Restatement detector** (works whatever Yahoo does): in the daily 5-day pull, compare each
   fetched `Close` with the stored `close` for the same day. If any stored value differs by
   > 0.5 %, history was restated (split / spin-off) → write a `history_restated` row to
   `price_anomalies`, then re-pull that symbol with `period=max` and rewrite it in one
   transaction. One symbol at a time, same throttle as the existing max backfill.
3. **Jump flag**: after the write, any |1-day return| > 40 % → `price_anomalies('jump_gt_40pct')`.
   This is how CTVA (−84 %), HEGAM.NS (−63 %) and MRNA (+177 %) get explained or fixed.
4. **`adj_close`** per symbol, computed from raw `close` + `corporate_actions` after each write:
   for each dividend with ex-date `d` and previous close `c₋`, factor `fᵈ = 1 − div / c₋`;
   `adj_close(t) = close(t) × Π fᵈ over dividends with d > t`. Splits need no factor because
   Yahoo's raw `Close` is already split-adjusted (that is what the restatement detector guards).
   Recompute the whole symbol when a new action lands (cheap: one symbol, ≤ ~9 k rows).
5. One-off: backfill `corporate_actions` + `adj_close` for all symbols — **same per-symbol
   `period=max` pattern and cursor as `BACKFILL=max`** (ADR 0003; Yahoo throttles multi-symbol).
   Estimate ≈ the original price backfill (~1,000 symbols × 0.8 s sleep plus request time ≈
   30–60 min; pace to pi2's quiet window).

Downstream, once `adj_close` exists: `stock_metrics.py` returns/vol/momentum read `adj_close`
(separate commit, after EV-0 is run on both series so the difference is visible).

### 3.2 `stock_fundamentals.py` (EV-2, F-1…F-4)
1. Fix F-4 (`failed` counter).
2. `edgar_facts()` — stop collapsing. For every entry with form 10-K/10-Q, record
   `(metric, end, start, duration_days, val, filed, form, accn)`. Write to `financial_facts`
   only if no row with the same `(symbol, source, metric, period_end, duration_days)` has the
   same `value` already (first release + restatements only).
3. Keep writing `stock_fundamentals` for current readers, but select by **duration** so the
   "latest" rows are the right ones: ~365-day for annual metrics; for the latest value use TTM
   = latest FY + YTD(now) − YTD(prior year) (add a small helper, tested on MSFT's fiscal year
   — it is the worked example in F-1). Switching readers is a **separate** step (§5).
4. `yf_statements()`: append to `financial_facts` with `filed = first observation date`
   (earlier date kept on conflict — fixes F-3); `upsert()` for `stock_fundamentals` should no
   longer overwrite `filing_published_at` of an existing row (`ON CONFLICT … DO UPDATE SET
   value = EXCLUDED.value` and leave `filing_published_at` alone).
5. Ratio rows (`pe`, `pb`, …) keep their fetch-date `ts`; add a one-line assertion in the job
   log that `count(distinct ts)` per ratio grows week over week.

### 3.3 EV-9 — new statement lines

| metric (stored) | EDGAR us-gaap tag(s) — first match | yfinance row | Feeds |
|---|---|---|---|
| `total_assets` | `Assets` | Total Assets | EV-10, 11, 12 |
| `gross_profit` | `GrossProfit`; else `total_revenue − CostOfRevenue` / `CostOfGoodsAndServicesSold` | Gross Profit | EV-10, G-score |
| `ocf` | `NetCashProvidedByUsedInOperatingActivities` | Operating Cash Flow | EV-12, F-score |
| `capex` | `PaymentsToAcquirePropertyPlantAndEquipment` | Capital Expenditure | FCF |
| `current_assets` / `current_liabilities` | `AssetsCurrent` / `LiabilitiesCurrent` | Current Assets / Liabilities | F-score |
| `total_liabilities` | `Liabilities` | Total Liabilities Net Minority Interest | distress screen |
| `shares_outstanding` | `dei:EntityCommonStockSharesOutstanding` (namespace **dei**, the current code only reads `us-gaap`); fallback `WeightedAverageNumberOfDilutedSharesOutstanding` | Ordinary Shares Number | EV-13 |
| `dividends_paid` | `PaymentsOfDividends`, `PaymentsOfDividendsCommonStock` | Cash Dividends Paid | payout yield |
| `buybacks` | `PaymentsForRepurchaseOfCommonStock` | Repurchase Of Capital Stock | payout yield, EV-13 |
| `interest_expense`, `d_and_a` | `InterestExpense`; `DepreciationDepletionAndAmortization` | Interest Expense; Depreciation… | coverage, EBITDA |

Tag names are from memory of the us-gaap taxonomy — **verify each against a real
`companyfacts` payload for 3–5 symbols in the canary** (companies use different tags; the
first-match list will need extending, as `total_revenue` already did).

## 4. Rollout order (quiet-window discipline, `cluster-mutation` skill)

1. **Prerequisite:** AR-11 backup fix verified — the tracker marks the current `pg-backup` as
   untrustworthy. Take and verify a dump first (`migration` skill, non-negotiable 1).
2. Add `09-data-foundations.sql` to `manifests/timescaledb/schema-configmap.yaml`; apply; re-run
   the schema-job. Verify with `\d` on each table. No writers change yet.
3. Build `local/screener:v9` (tag bump in `cronjobs.yaml` + `backfills.yaml`) via the §6 cycle
   (`/rebuild`); one node at a time, pi2 load < 3.
4. **Canary** (`canary-validate` skill): `CANARY_LIMIT=5` with MSFT (non-Dec FY), a Dec-FY
   company, one NSE symbol and CTVA. Acceptance:
   - MSFT `financial_facts` has distinct 91/182/273/365-day rows, and the FY2024 first-release
     `filed` is in 2024, not 2026;
   - `corporate_actions` for a known dividend payer matches Yahoo's list;
   - `adj_close ≤ close` before the latest dividend and equal after it;
   - re-running changes **no** row counts (idempotency, ADR 0005).
5. Full backfills (prices actions first, then facts) — per-symbol cursor, `backfill-resume`.
6. **Then** `/review` + docs, `data-quality` skill pass (row-count reconciliation, freshness).
7. Only after that, separate changes: switch `stock_screener.py` readers to TTM/duration-aware
   facts (fixes F-1 in live scores — re-score and compare before/after), then point the
   metrics job at `adj_close`.

## 5. Open decisions for you

1. **`financial_facts` as a new table vs changing `stock_fundamentals`' primary key.** Draft
   chooses the new table (additive, no reader breaks). The ADR 0005 "v2 revisions" note already
   anticipates it — a short ADR is warranted once agreed.
2. **Factor-return sources:** Ken French data library (US) and the IIM Ahmedabad data library
   (India) are the usual free sources; confirm current URLs, file formats and terms of use
   before building the loader — not verified here.
3. **Fix F-1 in live scores** — measured (F-1a): the effect is large, so the recommendation is
   now to fix rather than wait for EV-0. It changes today's rankings; re-score and diff the
   top-50 before/after and note it in the Telegram digest once.

## 6. Tracker entries to add (not yet added to `pending-tasks.md`)

- [ ] 🔶 **P0 · DQ-2 (F-1/F-2)** EDGAR facts keyed without duration; `filing_published_at` is the
  latest re-filing. Fix in `financial_facts` (this draft); blocks EV-0 on fundamentals and
  EV-9…15. Measure impact on live scores before changing readers.
- [ ] 🔶 **P0 · DQ-3 (F-3/F-4)** weekly yfinance run resets first-seen dates; `failed` undefined
  at `stock_fundamentals.py:228`. Verify deployed script, fix in v9. Do before the next weekly run.
- [ ] 🔶 **P1 · G-20** factor returns (US + India) loaded for alpha tests; extend EV-0 §5 test 4
  to "beyond the standard factors".
- [ ] 🔶 **P2 · G-21** extra signals testable from existing data: payout yield, distress score,
  Amihud illiquidity, max-daily-return / idiosyncratic volatility, industry momentum.
- [ ] 🔶 **P2 · G-22** check the 12 S&P symbols with no EDGAR rows (`cik` gap).
