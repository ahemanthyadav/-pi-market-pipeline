---
name: Cluster Mutation Discipline
description: Use before ANY cluster change — kubectl applies, agent restarts, StatefulSet edits, backfill launches, image imports. pi2 (1 GB control-plane) wedges under load; the rules here are what keep it alive. Load this instead of re-deriving the quiet-window rules from ops manual §8.
---

# Cluster mutation discipline

These rules were paid for in outages (pi2 wedged twice in one night; agents
crash-looping against a hot control-plane never break through — they only
sustain the storm). Ops manual §8 has the full runbooks; this is the
pre-flight checklist for any change.

## Before anything

1. **Check pi2** — load target < 2, and no other long job running:
   ```bash
   python3 ops-tools/runcmd.py pi2 pi2 'uptime; free -m | head -2'
   ```
   If load > 3 sustained: stop, follow ops manual §8 cool-down first.
2. **Confirm the change is one change.** Batch nothing — each mutation gets
   verified before the next begins.
3. **Know the rollback** before you apply (suspend the cronjob? delete the
   job? revert the manifest?). If there isn't one, say so out loud first.

## During

4. **One at a time, verify between.** After each apply: nodes Ready, the new
   job/pod status, DB rows where applicable.
5. **Agent restarts follow the proven order** — stop all agents → let pi2
   cool → start ONE (pi3 first), verify Ready (2 min), then pi1, then TX2.
   Never two at once; never against a hot server.
6. **Image imports:** pi1/pi3 can take a blocking `ctr images import`
   (~1-2 min); **pi2's runs detached** or it wedges the SSH session:
   `nohup sh -c "…import… && rm tarball" >/tmp/import.log 2>&1 &` then poll.
7. **DB-touching StatefulSet changes restart the database** — the DB is
   single-instance. In-flight jobs must be cursor-resumable or stopped
   first; expect their retry to crash-and-resume (that's designed).
   Postgres options go in StatefulSet `args:` — **never `command:`**
   (that replaces docker-entrypoint.sh → crash loop; delete the pod to
   recover).
8. **Long fetches run serially when they share an upstream.** Two
   Yahoo-heavy jobs in parallel throttle each other per-IP: worse total
   wall-clock than running them back to back.

## After

9. Re-verify the full state: `kubectl get nodes`, the job's logs' OK-marker,
   DB row counts, `pipeline_heartbeat` freshness for affected feeds.
10. Update docs in the same session (AGENTS.md docs discipline) — schedule
    tables, image tags, phase statuses. A change not documented is a change
    that will surprise the next session.

## Anti-patterns (all happened)

- Restarting two agents "to save time" — pi2 swap-thrashed; both had to be
  stopped and re-joined slowly.
- Applying a StatefulSet `command:` override — DB crash loop; data was safe
  (Retain PV) but every live connection died.
- Running the fundamentals backfill and price backfill concurrently — both
  Yahoo-bound, both slowed to a crawl.
