# 0005. Row-level DELETE+INSERT as the universal idempotent writer pattern

- Date: 2026-09-30 (practiced since first fetcher; recorded 2026-10-04)
- Status: accepted

## Context
Every fetcher must be safely re-runnable: CronJobs retry, humans re-trigger
manual validations, backfills overlap daily runs. Options: (a) INSERT-only +
dedup views — pushes complexity into every reader; (b) UPSERT (ON CONFLICT) —
requires constraints everywhere and silently coexists with genuinely-different
re-reports; (c) each writer DELETEs exactly the (key, ts) rows it is about to
INSERT, inside one transaction.

## Decision
Option (c): writers own their rows and DELETE+INSERT them per natural key;
unique indexes (added 2026-10-03) enforce the same keys DB-side as a belt for
concurrent edges. Full form in the `sql-conventions` skill; connection
discipline (autocommit reads, atomic `conn.transaction()` writes,
reconnect-retry) added 2026-10-04 after find F26.

## Consequences
- Re-runs are idempotent by construction; late corrections overwrite cleanly.
- The DELETE scope must exactly match what the INSERT can produce — no wider.
- Sanctioned exceptions: INSERT-only staging (`raw_headlines`) until its
  rebuild; append-only provenance tables in the v2 target architecture
  (`financial_facts_raw` revisions) — never mix patterns silently.
- Revisit only if a feed's re-reports must be *retained* as history
  (that is exactly the v2 revisions design).
