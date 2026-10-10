---
name: Experiment Report
description: Use when writing up an analysis, backtest, or A/B result — hypothesis, metric, baseline, result, caveats, plus the statistical-testing checklist that prevents overclaiming.
---

# Experiment report format

1. **Question & hypothesis** — one sentence each. If you can't state the
   hypothesis before seeing the results, you're exploring, not testing — say so.
2. **Metric & decision rule** — the exact quantity, computed how, with the
   threshold that would change a decision.
3. **Baseline** — always name one: buy-and-hold, persistence (last known
   value), or the naive rule. No baseline = no result.
4. **Setup** — data timeframe, universe, excluded periods (and why), seeds
   and sampling. Someone else should be able to re-run it from this section.
5. **Result** — effect size with confidence interval first, p-value second,
   plot to `out/`.
6. **Caveats** — what would change the conclusion; multiple-comparison
   exposure; survivorship (delisted tickers); lookahead risks.

## Statistical testing checklist

- Time series are not i.i.d.: use block bootstrap or Newey-West errors; a plain
  t-test on overlapping returns lies.
- Multiple comparisons: 20 tickers × one test each ≈ one false positive at
  p<0.05 expected. Correct (Benjamini-Hochberg) or don't compare.
- State n before claiming significance; n < 30 with p = 0.04 is noise.
- Regimes: does the effect survive both halves of the data? Check rolling windows.
- Report failures and nulls with the same rigor as wins.

## House bias check

Sentiment, technicals, and flows all share market-calendar gaps — align on
trading days before comparing anything across feeds. And remember the feeds
themselves have documented quirks (manual §4) before blaming the model.
