# 0006. `index_prices` stays pure-daily; intraday lives in `intraday_prices`

- Date: 2026-10-03 (recorded 2026-10-04)
- Status: accepted

## Context
The intraday feature (hourly gold/silver/oil/DXY + FX) needed a home. `ta-compute`
iterates `SELECT DISTINCT ticker FROM index_prices` and computes daily RSI/MACD
over ALL rows of each ticker — hourly rows there would corrupt its math on 1 GB
Pis. Options: (a) put hourly rows in `index_prices` and teach ta-compute to
filter — every future consumer inherits the trap; (b) a separate
`intraday_prices` hypertable; (c) refuse intraday entirely.

## Decision
Option (b): `intraday_prices` (ticker, ts, OHLCV, unique (ticker, ts)) for
futures/DXY; hourly FX goes to `fx_rates` (nothing computes over it). Dashboards
UNION daily + intraday where granularity helps. `index_prices` remains
pure-daily by contract.

## Consequences
- ta-compute and every daily consumer stay correct without knowing about
  intraday; the intraday fetcher is idempotent against candle timestamps
  (closed markets write nothing new).
- Any new fast-granularity feed follows the same split-first rule.
- Revisit if a consumer genuinely wants mixed granularity (then: explicit
  interval column + consumer-side filtering, not silent mixing).
