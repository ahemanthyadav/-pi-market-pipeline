# 0015. Point-in-time fundamentals in `financial_facts`; the screener reads them with a staleness guard

- Date: 2026-10-18
- Status: accepted (refines the "v2 revisions" note in ADR 0005)

## Context
`stock_fundamentals` keyed EDGAR values by `(metric, period end)`, so 3/6/9/12-month year-to-date figures collapsed
onto one key (median 3-year revenue CAGR −17.8 % vs a like-for-like +8.8 %), and `filing_published_at` held the
*latest* re-filing (MSFT FY2024 "known" in 2026) — history was not point-in-time (DQ-2). Options:
1. **Change `stock_fundamentals`' key** to include duration and filing date. Breaks every current reader at once.
2. **New append-only table** keyed `(symbol, source, metric, period_end, duration_days, filed)`, readers switched
   one by one behind a flag. Additive; old path kept for rollback.

## Decision
We keep `stock_fundamentals` as the "latest" view and add `financial_facts` because readers can move safely and
history becomes reproducible. Writer rules: EDGAR — one row per first release and per genuine restatement (a later
filing repeating the same value as a comparative is dropped), instants get duration 0; yfinance — a row only when the
value changes, `filed` = first day we observed it. The screener (`FUND_SOURCE=facts`, live since 2026-10-18) uses EDGAR
full-year series and TTM FCF (latest annual + YTD − prior-year YTD) known on the as-of date, and **falls back to yfinance
whenever a symbol's newest EDGAR annual period is older than 460 days**.

## Consequences
- The staleness guard is mandatory: companies change XBRL tags (CBOE's revenue stops in 2017; 19/486 revenue series
  stale on 2026-10-18). Without it the screener scored a 9-year-old CAGR. Extending `EDGAR_MAP` is append-only
  (first tag wins per key) and needs one fundamentals pass.
- Any new fundamentals reader must filter `filed <= as_of` and pick the latest `filed` per period — never `max(value)`.
- Rollback: `FUND_SOURCE=yfinance` on CronJob `stock-screener` (env only). Before/after evidence: SP500 top-50 46/50,
  NIFTY500 50/50 (India has no EDGAR, so it is unchanged).
- Revisit when an India filings source exists (G-6), or when Telegram `stocks.py` moves to the same reader.
