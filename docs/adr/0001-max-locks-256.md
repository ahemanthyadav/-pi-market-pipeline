# 0001. Raise Postgres max_locks_per_transaction to 256

- Date: 2026-10-04
- Status: accepted

## Context
Default (64) exhausted the shared lock table under concurrent hypertable access
during the EDGAR fundamentals backfill: repeated `out of shared memory` errors,
parallel count workers dying, and one backend killed outright (surfaced client-side
as a deterministic "the connection is closed"). Options: (a) keep 64 and serialize
all DB access — unacceptable, ingestion and analysis must overlap; (b) raise the
lock table to 256, the standard TimescaleDB recommendation for hypertable-heavy
use; (c) reduce hypertable chunk counts — fights the data model for no gain.

## Decision
We set `max_locks_per_transaction=256` on the TimescaleDB StatefulSet, passed via
container `args: ["postgres", "-c", "max_locks_per_transaction=256"]`, and added
`SET max_parallel_workers_per_gather = 0` to the health monitor's session
(aggregation checks never need parallelism; parallel workers multiply per-chunk
lock use).

## Consequences
- Concurrent ingest + reads + analysis coexist without lock exhaustion.
- Changing Postgres server options means StatefulSet `args:` — **never `command:`**
  (that replaces docker-entrypoint.sh and crash-loops the DB; recover by deleting
  the pod). The DB restarts on such changes: every long job must be cursor-resumable.
- Revisit only if lock errors return under heavier concurrency (next stop: 512).
