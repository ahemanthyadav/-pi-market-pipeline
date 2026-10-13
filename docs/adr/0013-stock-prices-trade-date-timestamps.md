# 0013. `stock_prices.ts` is midnight UTC on the trade date

- Date: 2026-10-13
- Status: accepted

## Context
`stock_prices` held two timestamp conventions at once. The first backfill stamped each bar with the exchange's local
midnight converted to UTC (US 04:00/05:00 UTC; NSE 18:30 UTC of the *previous* calendar day — 99.7 % of 6.34 M rows).
The daily job, since ~2026-09-28, writes `00:00` UTC on the trade date. Consequences found 2026-10-12: 4,434 duplicate
symbol-days (the unique index is on `(symbol, ts)`, so it could not see them), every old NSE `ts::date` one day early
(Monday's bar on Sunday), and row-count lookbacks in `stock_metrics.py` shortened for the affected symbols.
Options: (a) keep both and make every reader normalise — every future query and the EV-0 harness would carry the rule and
get it wrong once; (b) a `trade_date` generated column — additive but leaves two conventions in `ts` and doubles the
index surface on a 3,381-chunk hypertable; (c) rewrite history once to the convention the writer already uses.

## Decision
We store every `stock_prices` row at `00:00:00+00` UTC on the exchange's trade date, and rewrote the history to match
(`ops-tools/sql/2026-10-13-stock-prices-normalise-ts.sql`: `date_trunc('day', ts + interval '6 hours')`, per-symbol
transactions, each verified inserted == deleted), because the live writer already produces it and a single convention
keeps `ts::date` equal to the trade date for every reader.

## Consequences
- `ts::date` is the trade date for both universes; joins by date and monthly buckets need no per-exchange rule.
- Any new writer or backfill of `stock_prices` MUST stamp `00:00 UTC` on the trade date (never the exchange-local
  midnight). Check after a new backfill: `SELECT count(*) FROM stock_prices WHERE ts <> date_trunc('day', ts)` must be 0.
- The rewrite is not invertible by SQL; rollback is a restore from the pre-migration dump (`marketdata-2026-10-13.dump`).
- Same rule should be applied to any future per-stock daily table (corporate actions, adjusted prices — DQ-1).
- Revisit only if intraday stock bars are added: they belong in a separate table (compare ADR 0006), not in this one.
