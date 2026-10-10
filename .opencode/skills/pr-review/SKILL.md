---
name: PR Review
description: Use when reviewing a diff, manifest change, or script change — correctness, error handling, security, cluster-safety and consistency checklist; severity-ordered findings.
---

# Review checklist

Review in this order; report blockers before style nits.

## Correctness
- Does it do what it claims? Trace the main path with a concrete example.
- Boundaries: date ranges, cron schedules in UTC, `>=` vs `>`.
- Idempotency: can it run twice safely? (Pipeline writers: DELETE scope must
  exactly match INSERT scope — `sql-conventions` skill.)
- Failure modes: what happens when the feed is empty / returns garbage /
  times out? House style is WARN-and-continue per item, hard-fail only on
  total breakdown.

## Security & cluster safety
- No credentials in code, manifests, or logs; secrets only via Secret refs.
- No new public exposure — everything stays tailnet-only by design.
- Resource requests/limits present (nodes have 1 GB RAM).
- Destructive operations guarded: no naked `kubectl delete`, no DROP TABLE
  without a stated rollback.

## Consistency
- Naming, timezone handling, and log-line format match sibling fetchers
  (`"fetched N/M tickers"`, `"wrote N rows into <table>"`).
- Docs updated: schedule changes → manual §3; new quirks → §4 + script header;
  "Last verified" dates stay true.

## Output format
Findings in severity order — each with `file:line`, severity
(blocker / major / minor / nit), and a one-line suggested fix.
End with a verdict: ship / fix-then-ship / hold.
