# 0016. One-year chunks for long-history hypertables; old weekly chunks merged; hot queries bounded in time

- Date: 2026-10-18
- Status: accepted (extends the 2026-10-10 index_prices change recorded in `01-schema.sql`)

## Context
`stock_prices` used TimescaleDB's default 7-day chunks while holding data back to 1961: 3,382 chunks. `EXPLAIN
ANALYZE` of an open-ended per-symbol read: **34 s planning, 0.2 s execution**. It made the v12 price canary 2× slower
and would have made the adj_close backfill take ~13 h. Options:
1. **Rebuild the table** with a larger interval and swap names — rewrites 6.3 M rows, needs a writer pause.
2. **Merge existing chunks in place** with `merge_chunks()` (TimescaleDB 2.30.1) and set a 1-year interval for new
   chunks — same table OID, writers keep running, each year locked only for its own merge (~0.5–3 s).
3. Only bound every query in time — fixes new code, not ad-hoc queries, readers, or full-history jobs.

## Decision
We use option 2 plus option 3's rule, because it fixes the cause online and keeps the habit that prevents a repeat.
Applied after a verified pre-merge dump: stock_prices 1962–2025 → 107 chunks, index_prices 2021–2025 → 84; rows
identical, 0 duplicates; planning 34 s → 34 ms. New chunks: 1 year (`06e-chunk-intervals.sql`).

## Consequences
- AGENTS rule 9: hot-path queries carry a `ts >=` bound.
- `merge_chunks` is a PROCEDURE (`CALL`; chunk list passed via psql `\gset`). Script:
  `ops-tools/sql/2026-10-18-merge-weekly-chunks.sql`. Never merge the current year while writers are live.
- The 2026 weekly chunks of both tables remain; merge them after the year ends (an annual maintenance item).
- Small hypertables (fx, yields, scores…) keep 7-day chunks — revisit when any exceeds ~150 chunks
  (`SELECT hypertable_name, count(*) FROM timescaledb_information.chunks GROUP BY 1`).
