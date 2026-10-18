# 0018. No scoring change without passing EV-0; the composite stays as is after the first run

- Date: 2026-10-18
- Status: accepted

## Context
The composite (value .25 / quality .25 / growth .20 / momentum .20 / risk .10) was hand-picked and never tested. The
evidence roadmap §5 set an acceptance test *before* any testing: Newey-West IC t > 3; same sign in both halves and both
universes; Q5−Q1 positive after 0.2 % (US) / 0.4 % (India) per trade; adds information beyond existing factors.
`ops-tools/ev0.py` implements it. First run (2001–2026, `out/ev0/report-2026-10-18.md`): **no signal passes**.
NIFTY 500 12-1 momentum is strong (IC t 4.2, +13.5 %/yr net); S&P 500 results are dominated by survivorship (today's
constituents; low-vol and low-beta come out *negative*). Options: adopt the strong India signal now, or hold.

## Decision
We change no weights or inputs on this run, because the test was written before the results and a per-universe exception
is a design choice for composite v2 (EV-17), not something to slip in after seeing the numbers. Any future scoring or ML
change must show an EV-0 report that passes §5 (or documents the explained exception).

## Consequences
- **EV-1 (historical index membership) is now the blocking item** for any US signal; weekly snapshots (G-2a) only cover
  the future.
- Candidates for v2, recorded so they are not retried blindly: 12-1 momentum (India), drop `pos_52w` (no information after
  controls in either universe), reversal stays out (78 % turnover, costs consume it).
- Criterion 4 is partial (price controls only) until point-in-time value/quality history exists for both universes.
- Revisit after EV-1 lands or after ~12 more months of snapshots.
