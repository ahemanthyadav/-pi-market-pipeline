---
name: Test Writing
description: Use when adding tests or validating pipeline changes — what to test first, arrange-act-assert, market-data edge cases, and the cluster validation-job pattern for CronJob images.
---

# Test writing

## Priorities (highest value first)
1. **Contract tests at the data edges** — what does the writer do with: empty
   feed, partial feed, duplicate timestamps, timezone boundary (UTC midnight
   vs IST market open), first/last trading day?
2. **Idempotency test** — run the writer twice over the same window; row count
   and contents must be identical after run 2.
3. **Transformation tests** — pure functions with exact input→output fixtures.
4. **Integration smoke** — the cluster pattern below.

## Style
- Arrange-act-assert; one behavior per test; the test name states the behavior
  (`test_missing_trading_day_is_warned_not_fatal`).
- Fixtures are small real-shaped data (a 3-ticker × 5-day frame), never random noise.
- Assert on exact values with useful failure messages: "expected 248 rows for
  2026 trading days, got 251 — check NSE holiday handling".

## Market-data edge cases to cover explicitly
- Exchange holidays (NSE ≠ NYSE calendars), weekends, zero-volume days.
- No DST in IST, but US-sourced timestamps cross DST — store UTC, compare UTC.
- Feed format drift: renamed JSON keys (NSE FII/DII dropped its `{data:…}`
  envelope), symbol deaths (`FTSE.MI` → `FTSEMIB.MI`).

## Cluster validation pattern (CronJob images)

After building a new image, before declaring victory:

```bash
kubectl create job -n market-data <name>-validate --from=cronjob/<name>
kubectl get job -n market-data <name>-validate   # wait for Complete
kubectl logs -n market-data job/<name>-validate --tail=20
# expected lines documented per fetcher in manual §6, e.g. "fetched 28/28 tickers"
```

Then verify the DB actually changed (read-only count before/after — manual §5).
A passing job with zero new rows is a test failure, not a pass.
