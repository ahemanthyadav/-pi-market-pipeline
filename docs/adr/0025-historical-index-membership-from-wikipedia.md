# 0025. Historical S&P 500 membership from Wikipedia's changes table; NSE deferred

- Date: 2026-10-26
- Status: accepted

## Context
EV-1 (evidence roadmap Phase 0) is the blocking item for every US price-signal result: the
2026-10 EV-0 run showed low-vol/low-beta coming out with the *wrong sign* because today's
constituents include firms that were volatile small winners before joining — survivorship
bias baked into the sample. Fixing it needs point-in-time index membership. Candidate
sources: S&P DJI's official change history (press releases only, no bulk file, commercial
products license the data), CRSP/Compustat (paid), scraping press releases (fragile), or
Wikipedia's maintained tables. For the Nifty 500, NSE publishes reconstitution circulars
as PDFs, scattered across press pages.

## Decision
1. **US from Wikipedia**: the `constituents` table ("List of S&P 500 companies" — current
   members with their own "Date added") plus the `changes` table ("Historical components
   of the S&P 500" — effective date / added / removed, ~400 rows). `membership_history.py`
   (screener toolkit) rebuilds `index_membership` intervals monthly from both; the whole
   (SP500, wikipedia) slice is replaced per run, so upstream corrections land automatically.
2. **Interval semantics**: `removed IS NULL` = current member; `added = 1900-01-01` =
   "member since before the records". Backtests must clip to the window the source covers.
3. **India deferred, decision recorded**: NSE circulars are unstructured PDFs — a separate
   session with its own parsing approach. `universe_membership_snapshots` (accruing since
   2026-10-18) builds the forward history for both universes in the meantime, and EV-1's
   blocking effect was on *US* signals.

## Consequences
- US EV-0 runs can select point-in-time members (join `index_membership` on the signal
  date) from roughly 2012 comprehensively, selected changes back to 1976. The pre-2012
  thinness is a known limit, recorded here; it still removes the bias from the decade the
  harness actually tests.
- Wikipedia is a community source: the loader validates row counts (refuses implausibly
  small tables) and cross-checks the reconstructed current set against
  `universe_constituents` (drift > 10 symbols fails the run) before replacing anything.
- Ticker spellings are normalized to the universe's Yahoo form (`BRK.B` → `BRK-B`), so
  joins against `stock_prices`/`universe_constituents` need no mapping table.
- If a better bulk source ever lands (e.g. licensed CRSP), `source` keys the slice — load
  it alongside and compare before switching.
