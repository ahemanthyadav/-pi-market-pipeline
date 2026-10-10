---
name: Performance Profiling
description: Use when anything is slow — measure a baseline first, profile the right layer (SQL, Python, job, cluster), one change at a time, and report before/after numbers with the environment noted.
---

# Performance profiling

## Order of operations
1. **Define the metric and get a baseline before changing anything.** Wall
   time of what, on what data size: job duration (start→end from
   `kubectl get jobs`), query time (`EXPLAIN ANALYZE`), script time.
   No baseline = no optimization, just churn.
2. **Find the layer. Measure, don't guess:**
   - SQL: `EXPLAIN (ANALYZE, BUFFERS)` — look for seq scans on hypertables
     without a time filter, spills, row estimates off by 10×+.
   - Python: `python -m cProfile -s cumulative script.py`, then line-profile
     only the top functions.
   - Jobs: phase timings in logs (fetch vs transform vs write); network waits
     vs CPU (feeds rate-limit — batch, then sleep, watch totals).
   - Cluster: node load — the 1 GB RAM Pis thrash easily; DB lives on the
     TX2's USB SSD, not eMMC.
3. **Optimize the hot layer only.** One change at a time; re-measure the same
   metric on the same data after each.

## Reporting
Before/after table: metric, before, after, environment (data size, node,
date). Record failed attempts too — "tried X, made it worse because Y" saves
the next person an hour. Speedups without the measurement path are anecdotes.

## Cluster-specific ceilings
- Pis (1 GB RAM): anything materializing a big frame will swap — stream instead.
- TX2 eMMC is small and precious: multi-GB scratch belongs on `/mnt/tx2-ssd`,
  and watch `df -h /` above 85%.
- A k3s job's total time ≈ pull (≈0, images local) + start + run. If "run"
  isn't the dominant term, the problem is cluster-side, not your code.
