---
name: Exploratory Data Analysis
description: Use when first encountering a dataset — CSV, Parquet, or SQL table — and before any analysis of it. The standard EDA checklist — shape, grain, nulls, duplicates, distributions, outliers, time-series gaps, leakage. Plots to out/.
---

# EDA checklist

Work top-down; each step gates the next. Prefer DuckDB (`read_csv_auto`,
`read_parquet`) — it handles multi-GB files without loading them into memory.

## 1. Shape & schema
- Row/column counts; column names, dtypes, nullability.
- Primary key candidates: uniqueness + completeness. State the grain of the
  table ("one row per ticker per day") in one sentence before anything else.
- Time range: min/max timestamp, and the timezone — assume UTC here until
  proven otherwise.

## 2. Nulls & duplicates
- Null count per column; decide whether nulls are random or systematic —
  systematic is usually the interesting part.
- Exact-duplicate rows; duplicate keys (count duplicates at the stated grain).
- Market data: missing trading days per ticker vs the exchange calendar.
  NSE holidays ≠ NYSE holidays — use the right calendar per universe.

## 3. Distributions
- Numeric: min / median / mean / p95 / max — not just mean±std. Flag skew.
- Categorical: value counts, top-N, and any unexpected values.
- Save a histogram + box plot per important numeric column to `out/`.

## 4. Outliers
- Rule-based first (negative prices, yields outside plausible bands, daily
  moves beyond exchange limits), then z-score or rolling approaches.
- Never drop outliers silently — list them and report; a "bad" price is often
  a feed quirk worth documenting, not a row to delete.

## 5. Time-series specifics
- Gap scan: expected vs actual rows per ticker per period.
- Level breaks / regime shifts around known events (data-source change, feed
  death, split) — check `pipeline_heartbeat` for ingestion gaps at those times.
- Stale series: last non-null timestamp per series.

## 6. Leakage preview (only if modeling is coming)
- Any column encoding the future (next-day close, forward-filled macro data)?
- Any split that shuffles time? Market data must be split by time — see the
  `ml-experiment` skill.

## Output
- Every plot → `out/<nn-descriptive>.png`; tables → printed or `out/*.csv`.
- Findings summary: quality problems first, structure second, hypothesis-worthy
  observations third. Numbers, not vibes.
