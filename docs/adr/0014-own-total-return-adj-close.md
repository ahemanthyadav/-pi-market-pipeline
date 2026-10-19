# 0014. `adj_close` is our own total-return series, not Yahoo's Adj Close

- Date: 2026-10-18
- Status: accepted

## Context
Returns, momentum and volatility were computed on raw `close`, which Yahoo split-adjusts but does not
dividend-adjust (DQ-1). Two ways to get a total-return price:
1. **Store Yahoo's `Adj Close`.** Free — it is already in every download. But Yahoo rewrites the whole column
   backwards on every new dividend, and our daily job only refreshes the last 5 days, so older rows would hold
   a mix of factor vintages that never reconcile. Silent, unfixable drift.
2. **Compute it ourselves** from `close` + a `corporate_actions` table: `adj(t) = close(t) × Π(1 − div_d / c_d)`
   over dividends with ex-date `d > t`, `c_d` = close of the last bar before `d`. Needs the dividend history
   (one backfill) and a recompute when a dividend arrives. Splits need no factor: Yahoo's raw `Close` and its
   dividend amounts are both already split-adjusted.

## Decision
We compute `adj_close` ourselves (`stock_prices.adj_series()` / `recompute_adj_close()`, `screener:v12`) because
only a series we derive from stored inputs stays internally consistent and re-derivable. New rows start at
`adj_close = close` (correct: no later dividend exists yet); a symbol is recomputed after any full-history write
or when a dividend appears in the daily window. Full re-derivation: Job `backfill-corporate-actions`.

## Consequences
- Never write Yahoo's `Adj Close` anywhere — a test (`test_adj_close_starts_at_close_never_yahoo_adj_close`) guards it.
- `corporate_actions` is now load-bearing: losing it means re-running the backfill (~85 min, resumable).
- Verified 2026-10-18: 0 NULL of 6,343,487 rows; `adj_close ≤ close` everywhere; 10-year total − price return
  matches known dividend yields (KO 3.4 %/yr, XOM 4.75 %, BRK-B 0).
- Not yet consumed: `stock_metrics.py` still reads `close` (EV-0 found small rank effects; switch is a separate change).
- Revisit if a second price source (G-18) brings its own dividend data, or if spin-offs need value-based factors
  (today Yahoo records them as split ratios — CTVA 6.66 — which the resync path handles).
