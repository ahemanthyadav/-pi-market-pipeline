---
name: SQL Conventions
description: Use when writing or reviewing SQL — naming, CTE style, dialect quirks for Postgres/TimescaleDB, and the idempotent DELETE+INSERT writer pattern pipeline fetchers must follow.
---

# SQL conventions

## Style
- snake_case identifiers; plural table names; `ts` for the primary time column
  (timestamptz, UTC everywhere).
- CTEs over nested subqueries; one CTE per logical step, named for what it means.
- Explicit column lists in every INSERT; never `SELECT *` in production code.
- Keywords upper-case; spell out JOINs (`INNER JOIN`, `LEFT JOIN`).
- Round only for display (`round(x::numeric, 2)`), never in stored data or joins.

## Postgres / TimescaleDB
- Time buckets: `time_bucket('1 day', ts)` on hypertables, or `date_trunc` on
  plain tables — know which one you are touching.
- Hypertable DDL goes through the schema ConfigMap + schema-job, never ad-hoc
  psql (see the `migration` skill).
- Always filter hypertables by time first — `WHERE ts >= now() - interval '30 days'`
  — even when you think the table is small.
- `EXPLAIN (ANALYZE, BUFFERS)` before claiming a query is slow.

## Pipeline writer pattern (idempotency)

Fetchers own their rows keyed by (entity, ts) and must be safely re-runnable:

```sql
BEGIN;
DELETE FROM target
 WHERE ticker = $1 AND ts >= $start;
INSERT INTO target (ticker, ts, close, ...)
SELECT ...;
COMMIT;
```

- The DELETE scope must exactly match what the INSERT can produce — no wider.
- Writers without a natural key need `ON CONFLICT ... DO NOTHING/UPDATE` at
  the next image rebuild (known gap: the news tables — manual §12).
- Never INSERT-only into a shared table; never DELETE another writer's rows.
- Single commit per window; wrap fetch+transform outside the transaction.

## Connection discipline for long-running fetchers (find F26 — all scripts follow this)

The pod→DB path drops connections that sit idle inside an open transaction
during multi-minute fetches ("the connection is closed"). House pattern,
required for any new fetcher/scorer:

- `conn.autocommit = True` for the whole session — reads never leave a
  lingering transaction; no idle-in-transaction windows.
- One write unit per `with conn.transaction():` (per symbol/chunk) — short,
  atomic, replaces BEGIN/COMMIT blocks.
- On `psycopg.OperationalError`: `conn.close()` (guarded), reconnect, retry
  the write unit ONCE, then WARN-and-continue — never let one dropped
  connection kill a 9-hour run.
- Monitor/aggregate scripts that count or scan hypertables:
  `SET max_parallel_workers_per_gather = 0` — parallel workers multiply
  per-chunk lock-table use and exhausted shared memory at
  `max_locks_per_transaction=64` (now 256, but serial checks are still
  kinder to concurrent ingests).
- Revisions/provenance tables (`financial_facts_raw`, future) are the ONE
  append-only exception to DELETE+INSERT (target-architecture doc §15.4).

## Ad-hoc analysis
- Read-only by default: propose writes, don't run them.
- Prefer DuckDB over pulling large extracts into pandas.
- Row-count reconciliation beats spot checks: counts per stage per day.
