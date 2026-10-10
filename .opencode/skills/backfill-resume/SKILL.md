---
name: Backfill Resume
description: Use when running, resuming, or sanity-checking one-shot backfill Jobs (max-history prices, EDGAR/yfinance fundamentals) — job_state cursor semantics, pass-completion detection, throttle-aware pacing, and the verify steps that prove a backfill actually landed.
---

# Backfill resume

Backfills are one-shot Jobs (manifests: `manifests/stock-screener/backfills.yaml`)
designed to survive crashes: a `job_state` cursor records the last COMPLETED
symbol, and rows are idempotent (DELETE+INSERT), so reruns never duplicate or
corrupt — they just continue.

## Cursor mechanics

- `job_state.job_name` keys: `stock_prices_max` (prices), `stock_fundamentals`
  (statements + ratios). `last_key` = last successfully written symbol,
  processed in **sorted symbol order**.
- **Resume = just re-apply the Job.** It filters `symbol > last_key` and
  continues. A crash mid-symbol loses nothing (cursor only advances on
  success).
- **Pass-complete detection (v7+):** an empty post-cursor universe in backfill
  mode means the previous pass finished — the script clears the cursor and
  prints "pass already complete — cursor cleared". Without the clear, the
  next weekly run would see "nothing to do" forever (this exact bug shipped
  in ≤v6; if you ever see "nothing to do" WITHOUT the clear line, re-run
  once with v7+).
- Applying `backfills.yaml` launches BOTH Jobs — when sequencing matters,
  split the docs (`yaml.safe_load_all`) and apply one at a time.

## Pacing reality (Yahoo)

- Multi-symbol `yf.download(period='max')` chunks stall into silent
  multi-minute retries (find F25) — max-history runs **per-symbol only**
  (`Ticker.history(period='max')`), ~36 s/symbol under throttle ≈ 6-9 h for
  ~1000 symbols. That's normal: unattended, resumable, fine.
- Daily mode (5d window) chunks fine (~8 min for 998).
- Fundamentals: EDGAR leg is throttle-free (~35-60 min for 500); NSE leg via
  yfinance (~1-2 s/symbol). Serial with price backfills — shared per-IP
  throttle.

## Before launching

1. pi2 quiet (load < 2), no other long fetch running (cluster-mutation skill).
2. Image present on pi1/pi2/pi3 AND the live Job manifest references it —
   verify with jsonpath (canary-validate skill step 1).
3. Previous run's Job object deleted (name collision blocks apply).

## After completion

4. Expect the OK-marker: `PRICES-OK mode=max fetched=…` /
   `FUNDAMENTALS-OK done=… rows=…`.
5. Verify in the DB (read-only), not the log alone:
   - `count(DISTINCT symbol)` vs universe (~998; a handful of dead Yahoo
     symbols is normal — WARNs list them),
   - per-symbol bar counts vs the source's max range (US veterans ≥ 5000
     daily bars; NSE listings shorter),
   - gap % < 5; EDGAR facts reach ~2006 for established filers.
6. Coverage holes that are pure data-availability (no Yahoo symbol) stay
   WARN'd — they are documented, not bugs; do not retry-loop them.

## Anti-patterns (all happened)

- Waiting on `kubectl logs job/…` while a throttled chunk sat 25 min producing
  nothing — per-symbol mode was the fix, not more waiting.
- Reading "Complete" as proof of data (a backfill once finished with an empty
  parse; the DB count caught it).
- Clearing `job_state` by hand mid-pass — resume does that itself on
  completion; manual clears lose the crash-safety.
