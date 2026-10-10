---
name: ML Experiment
description: Use when training models, tuning, or running backtests on market data — seed control, time-based split hygiene, leakage checks, experiment logging, reproducibility.
---

# ML experiment hygiene

## Reproducibility
- Seed everything: `random`, `numpy`, `torch`/sklearn; record library versions.
- One experiment = one config dict + one log line (timestamp, data hash,
  metric). If you can't re-run it from the log, it didn't happen.
- Hash the data query + timeframe, not just "latest".

## Split hygiene (market data rules)
- **Time-based splits only. Never shuffle.** Random K-fold on time series
  leaks; use expanding windows or purged splits with an embargo gap ≥ the
  label horizon.
- Split on label time, not feature time: a label computed from t+5 must not
  appear in training if t+5 falls inside the validation window.
- Cross-market data (NSE + US) shares global regimes — split by date across
  both, or state explicitly why not.

## Leakage checks (run before every training)
- Any feature correlated ~1.0 with the target? (usually the target's own transform)
- Any feature with future knowledge: forward-filled macro series, "current"
  index membership, normalize-then-split instead of split-then-normalize?
- One suspicious feature dominating importance → investigate before iterating.

## Financial specifics
- Model returns, not prices. Log or simple — pick one and say which.
- Fees and slippage in every backtest, even rough ones; report turnover.
- Directional accuracy vs class balance first — AUC flatters a 52/48 problem.
  Sharpe needs ≥30 observations to mean anything.

## On this cluster
- Train on the TX2 (GPU node) or the admin machine; Pis are for serving, not
  training. Anything heavier than a notebook → `notebook-to-script` skill.
