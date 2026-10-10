---
name: Debugging
description: Use when something is broken or behaving unexpectedly — reproduce first, read the full error, form competing hypotheses, bisect with data not code, then write the regression test. Cluster-tailored triage pointers included.
---

# Debugging method

1. **Reproduce before theorizing.** Smallest failing case with real data. In
   this repo that means: the exact job name, date window, and log tail.
2. **Read the error output completely.** Then establish the timeline: when did
   it last succeed? (`kubectl get jobs -n market-data`, the table's `max(ts)`,
   `pipeline_heartbeat`.)
3. **Form ≥2 competing hypotheses before testing any.** Write each down with a
   cheap discriminating test. Known-pattern checks first (manual §8):
   - feed died / symbol renamed? → WARN lines + the Yahoo search probe
   - image missing on a node? → `ErrImageNeverPull` + the pod's NODE column
   - data fine, dashboard lying? → Grafana `jsonData.database` / time-picker gotcha
   - pi2 wedged? → load check before touching anything (cool-down first, §8)
   - `kubectl exec` failing on TX2? → cgroupfs alignment check (§8)
4. **Bisect.** One variable at a time; prefer narrowing data windows over code
   changes to locate the boundary. Don't fix while still diagnosing.
5. **Fix, then prove it.** Re-run the reproduction, then write the regression
   test (`test-writing` skill) so it can't come back.

## Rules
- No cluster mutations during diagnosis that you can't undo with one command.
- Capture evidence (log excerpts, row counts, timestamps) into the report or
   docs as you go — after the fix, "what we saw" is as valuable as the fix.
- If two different fixes both "work", you don't understand the bug yet. Find
  the discriminating test.
