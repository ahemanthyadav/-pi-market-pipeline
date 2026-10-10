# 0003. Max-history backfills fetch per-symbol, not in chunks

- Date: 2026-10-04
- Status: accepted

## Context
The max-history price backfill initially used the daily fetcher's chunk pattern
(50 symbols per `yf.download(period='max')`). Yahoo throttles multi-symbol
max-range requests into silent multi-minute retries: the chunk variant sat 25+
minutes at near-zero CPU producing nothing, while daily-mode (5d) chunks work
fine. Options: (a) bigger sleeps/smaller chunks — still crawls, unbounded;
(b) per-symbol `Ticker.history(period='max')` with a `job_state` cursor — one
request at a time, symbol-granular resume; (c) third-party bulk data source —
adds a dependency for a one-time job.

## Decision
Backfill mode (`BACKFILL=max`) fetches one symbol at a time, writing each
atomically and advancing the `job_state` cursor; daily mode keeps chunks.
Verified: ~36 s/symbol under throttle, 997 symbols / 6.34M rows completed in ~9 h
unattended. Same rule applies to any future Yahoo-bound bulk backfill.

## Consequences
- Backfills are slow but flow; resumable at symbol granularity (a crash loses
  at most the in-flight symbol).
- Never run two Yahoo-heavy jobs concurrently — the throttle is per-IP.
- The cursor-clear rule (empty post-cursor universe = pass complete) is part of
  this design (v7+); without it the weekly fundamentals refresh would stall
  forever after one crash near the end.
- Revisit only if a bulk data source is ever adopted for history.
