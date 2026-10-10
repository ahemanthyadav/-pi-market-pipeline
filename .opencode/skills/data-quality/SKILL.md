---
name: Data Quality
description: Use when validating pipeline data or before publishing any analysis — null/duplicate/range checks, row-count reconciliation between pipeline stages, freshness against pipeline_heartbeat, severity triage.
---

# Data quality checks

Run the battery before trusting any table; report as a table with PASS/FAIL
and severity. Numbers, not adjectives.

## Battery (per table, per day window)

| Check | Query sketch | Fail when |
|---|---|---|
| Row count | `count(*)` per day | outside ±2 of the recent daily median |
| Grain intact | `count(*) - count(distinct (ticker, ts))` | > 0 (duplicates) |
| Nulls in key cols | `count(*) filter (where close is null)` | > 0 |
| Range | negative prices; yields outside [0, 25]; sentiment outside [-1, 1] | any hit |
| Freshness | `max(ts)` per feed vs now | older than cadence × 2 |
| Step change | `abs(close / lag(close) - 1)` per ticker | > 25% intraday-market daily move — verify before trusting |

## Row-count reconciliation between stages

For each pipeline stage pair (rows fetched → rows written):
- Fetcher logs end with `"wrote N rows into <table>"` — the DB must show
  exactly N new/overwritten rows. A mismatch means a silent partial write
  (DELETE+INSERT misalignment): stop and reconcile before analysis.
- news: `raw_headlines` (staging) → `news_sentiment` (scored): scored ≤ staged;
  the gap is articles FinBERT failed on — profile the tail before assuming.

## Freshness via pipeline_heartbeat

`pipeline_heartbeat` is the alert source (10 feeds). Join each feed's cron
schedule (manual §3, all UTC) against its last-seen timestamp; flag anything
older than cadence × 2. NSE runs 11:15 UTC; US feeds 22:30–23:45 UTC — a
"stale" NSE row at 20:00 UTC is usually just early, not broken.

## Triage severity

- **P1** wrong data present (bad values, broken grain) — analysis must stop.
- **P2** missing data (gaps, stale feed) — analysis possible if scoped around it.
- **P3** cosmetic (naming, timezone-naive display) — note and continue.

Output: one table (check, result, severity, notes) + a one-paragraph verdict
that states what can and cannot be trusted from this dataset.
