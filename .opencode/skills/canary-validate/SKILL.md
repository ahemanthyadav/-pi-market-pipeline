---
name: Canary Validation
description: Use before trusting ANY CronJob change, new image, or "it should work now" claim — verify the live spec first, run a --from=cronjob canary, capture logs before the pod vanishes (k8s 1.36 deletes failed job pods), then check the DB. Sed-editing a manifest changes nothing until applied.
---

# Canary validation

The pipeline's rule: no schedule goes live, no fix is believed, until a
canary run proves it against the LIVE cluster. Three failure modes this
checklist exists to catch — stale live specs, vanishing pods, and
"completed but wrote nothing".

## 1. Verify the LIVE spec first (find F28 — the trap that cost 3 wasted validations)

```bash
kubectl -n market-data get cronjob <name> -o jsonpath='{.spec.jobTemplate.spec.template.spec.containers[0].image}{"\n"}'
```
- If this does not show the tag you expect, `kubectl apply` the manifest and
  re-check. **A sed'd yaml file is not a deploy.** Never validate against an
  image you haven't confirmed is live.
- Same for any patched field (env, command, schedule): jsonpath the live object.

## 2. Launch the canary

```bash
kubectl -n market-data create job <name>-validate --from=cronjob/<name>
```
- For env-var canaries (UNIVERSE_LIMIT, CANARY_LIMIT, BACKFILL), create a
  one-off Job manifest instead — `create job --from=cronjob` cannot inject env.

## 3. Capture logs LIVE — failed job pods are deleted within ~a minute

`kubectl logs job/<name>` often times out with "no pods found" because the
k8s 1.36 job controller removes failed pods quickly. Poll for the pod and
grab logs the moment it exists:

```bash
for i in $(seq 1 20); do P=$(kubectl -n market-data get pods -l job-name=<name>-validate \
  -o jsonpath='{.items[0].metadata.name}' 2>/dev/null); [ -n "$P" ] && break; sleep 2; done
for i in $(seq 1 30); do L=$(kubectl -n market-data logs "$P" 2>/dev/null); \
  echo "$L" | grep -qE "<OK-marker>|Traceback" && break; sleep 4; done
kubectl -n market-data logs "$P" | tail -15
```
- Know the script's OK-marker before you start (PRICES-OK, FUNDAMENTALS-OK,
  METRICS-OK, SCREENER-OK, REPORT-OK, HEALTH-OK, UNIVERSE-OK…).
- `kubectl exec`-style debugging of DB env inside pods: never inline passwords
  (AGENTS.md §7) — use a Job manifest with `secretKeyRef`.

## 4. Trust the DATABASE, not the exit code

Exit 0 + zero rows is a real failure mode (silent-empty parsers). Check:
- Row counts / coverage against the pass bars in the relevant plan §
  (e.g. screener plan §11): `count(DISTINCT symbol)`, today's-row coverage.
- Freshness: `pipeline_heartbeat` flips to `fresh=false` when a feed stalls.
- For silent-empty suspicion: run the same query the script runs, by hand
  (read-only), and look at what the parser saw (e.g. raw API response shape).

## 5. Clean up + record

```bash
kubectl -n market-data delete job <name>-validate
```
- Record the result in the plan's rollout table (✅/🔶 + one-line evidence).
- New failure modes discovered → ops manual §8 entry (copy-paste fix).

## Anti-patterns (all happened)

- Believing a rerun "tested the fix" while the live CronJob still pointed at
  the old image (three times in one day).
- Reading only `kubectl logs job/…` — works for completed jobs, useless for
  failed ones whose pods are gone; poll-capture instead.
- Trusting WARN-free logs without a DB row-count check (EDGAR once parsed
  100% clean and wrote 0 rows).
