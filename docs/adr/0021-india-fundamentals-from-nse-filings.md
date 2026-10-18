# 0021. India fundamentals come from NSE's own results filings

- Date: 2026-10-18
- Status: accepted (resolves G-6)

## Context
yfinance gives ~4 annual statements per NSE company and no filing dates, so half the universe could not be tested
on fundamentals (EV-0) and its screener inputs were not point-in-time. Options considered:
1. **Paid API** (EOD Historical Data, FMP and similar): one structured feed, but a recurring cost, uncertain India depth
   and licence terms for stored history, and a key to manage.
2. **Scrape aggregators** (screener.in and similar): convenient, but terms of use and layout churn.
3. **NSE's own filings** — measured 2026-10-18: every quarterly and annual result since 2005 (or listing), each with an
   exact filing timestamp. Three eras: archive HTML pages 2005–2011, a JSON data endpoint 2012–2024 (also bank
   records, `format=New`), integrated-filing XBRL 2025→ (rupees, quarter + YTD contexts). Free and official; needs
   the session-cookie pattern `fiidii-fetcher` already uses, and polite pacing.

## Decision
We ingest NSE filings (`nse_fundamentals.py`, `screener:v15`) because it is the primary source, free, deep and
point-in-time. Rules: consolidated filings preferred, standalone only for periods without one (sources `nse_cons` /
`nse_sa`); **every** filing of a period is kept (TCS FY2016: original 2016 + Ind-AS restatement 2018) and stored with
the ADR 0015 first-release/restatement rule; revenue = gross income from operations (`re_gro_inc` = net sales + other
operating income — TCS FY2014 booked 96 % of revenue as the latter); banks use total income; a missing filing date is
estimated as period end + 60 days (late on purpose — never look-ahead); exact zeros on old pages mean "not reported".
The screener reads `nse_cons` alongside EDGAR (`FACT_SOURCES`); single quarters (2012–2024) are summed into TTM.

## Consequences
- First full history: Job `backfill-nse-fundamentals` (~19 h at 1.3 s/request, resumable). Weekly incremental:
  CronJob `nse-fundamentals` (Sun) — suspended until the backfill ends (shared cursor).
- NSE changes endpoints periodically (it did in 2025); the parsers are tested against real captured filings in
  `tests/fixtures/nse/`. A new era means a new parser + fixture, not a silent gap: zero facts per filing is logged.
- India growth/FCF inputs change once the backfill lands: run the screener dry-run diff (NIFTY top-50) before relying
  on it, as for EDGAR.
- Not covered: balance-sheet and cash-flow history (results filings carry the P&L; half-year balance sheets only
  recently). Extend from the XBRL era if needed.
- Revisit if NSE blocks automated access or a licensed feed becomes cheap.
