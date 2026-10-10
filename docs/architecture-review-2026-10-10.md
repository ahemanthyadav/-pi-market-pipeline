# Architecture Review — 2026-10-10

> **Status:** recommendations, not decisions. Nothing here has been applied. Accepted items
> move to `pending-tasks.md` (already linked as AR-1…AR-12) and, where the decision has a long
> shelf life, get an ADR (candidates in §7).
> **Method:** repo and manifests read at HEAD plus the in-progress working tree (a parallel
> session was editing the Telegram bot, `yfinance-fetcher.py` and a new `telegram-alerts` job);
> evidence counts are reproducible with the commands in §8. **The live cluster was degraded at
> the time and was NOT re-verified** — everything below is about what the repo defines.
> Companion docs: `market-data-architecture.md` (what exists), `market-data-pipeline-architecture-roadmap.md`
> (hardening roadmap, incl. the "do not change" list), `adr/` (decisions).

## 1. Verdict

The foundation is right for a one-person, daily-batch system: idempotent writers, node-local
images, one DB, CronJobs, Tailscale-only access, strong documentation discipline. The weaknesses
are **failure containment, duplication, and observability** — the three things the
2026-10-09→10 outage (16 h control-plane wedge, root cause undervolting PSU) exposed. None needs a
platform change; all are fixable inside the current stack.

## 2. Keep (do not re-litigate)

- Row-level `DELETE+INSERT` + unique indexes (ADR 0005) — any job can re-run safely.
- One directory per fetcher with code + Dockerfile + manifest together.
- Resource limits and `backoffLimit` on every CronJob; tiny job-history limits; `imagePullPolicy: Never`
  on the local images (ADR 0004); schema as a ConfigMap; `pipeline_heartbeat`; ADRs; docs discipline.
- k3s, CronJobs, TimescaleDB, Grafana, Tailscale — no Airflow/Argo/Loki/Longhorn (ADR 0008).
- The new guards (pre-commit hook, `workloads.py --check`, tests) — extend, don't replace.

## 3. Findings and recommendations

Severity: **H** = would have prevented or shortened the outage / protects data; **M** = removes a
recurring cost or class of bug; **L** = hygiene.

### AR-1 (H) No protection against a restart storm
**Evidence:** of the 22 committed CronJobs, **0** set `startingDeadlineSeconds`, **0** set
`concurrencyPolicy` (default `Allow`), **0** set `activeDeadlineSeconds`, **0** set
`ttlSecondsAfterFinished`.
**Impact:** after a control-plane outage every job whose schedule was missed fires together on
recovery (the 2026-10-10 recovery had to suspend all CronJobs by hand); overlapping runs and hung
runs (e.g. a silently-retrying Yahoo pull) are unbounded.
**Recommendation:** one shared base with `concurrencyPolicy: Forbid`, a per-job
`startingDeadlineSeconds` (daily jobs ≈ 1 h, hourly intraday ≈ 10 min — a stale run is *skipped*,
which is safe because writers are idempotent and windows overlap), an `activeDeadlineSeconds` sized
to each job, and a `ttlSecondsAfterFinished`. Check each job's window really overlaps before
choosing its deadline. **Effort:** small. **Risk:** low (spec-only apply; no image change; do it in a
calm window per `cluster-mutation`).

### AR-2 (M) The "house pattern" is copy-pasted and unevenly applied
**Evidence (≈24 job scripts, ≈4.1 k lines):** `psycopg.connect` in 21, but `OperationalError`
handling in only 7 and `autocommit` in only 9. The screener's nightly crash (ops manual §8, the
connection-closed recurrence) lived in exactly this gap.
**Recommendation:** one small shared module — DB connect with a single retry, a `write_window()`
that does DELETE+INSERT in one transaction, structured logging, a `main()` wrapper that sets exit
codes — baked into images with `COPY` (no registry needed). **Effort:** medium. **Risk:** medium (touches every
job; roll out job by job at natural image rebuilds, each behind a canary per `canary-validate`).

### AR-3 (H) Failures leave no durable record
**Evidence:** failed pods vanish within ~1 min on k8s 1.36; the only run record is `pipeline_heartbeat`
(per-feed freshness, written once at 01:45).
**Recommendation:** the shared module (AR-2) writes a `job_runs` row per run — start, end, rows
written, status, error text. Alerts can then name the failing job and reason, and post-mortems don't
depend on catching a pod. This is "heartbeat v2" from the roadmap, promoted. **Effort:** small once AR-2
exists. **Risk:** low (additive table — follow the `migration` skill).

### AR-4 (H) Always-on workloads: no probes, DB not protected from OOM
**Evidence:** `timescaledb`, `grafana`, `telegram-bot` have no liveness/readiness probes; the DB is
`Burstable` (request 1 Gi / limit 2 Gi) on a 7.7 GB node shared with the 4 Gi sentiment job.
**Recommendation:** DB `requests == limits` (→ `Guaranteed` QoS, lowest OOM score) and a *readiness*
probe (`pg_isready`; keep liveness generous or absent so load can't restart-kill it); a liveness
check for the long-poll bot; consider a `PriorityClass` for the DB. **Effort:** small. **Risk:**
**a StatefulSet change restarts the single DB instance** — in-flight jobs must be resumable; do it in a
quiet window (`cluster-mutation` §7).

### AR-5 (M) 16 images, 3 lockfiles, unpinned builds
**Evidence:** 16 Dockerfiles (15 × `python:3.12-slim`, 1 × 3.11), 3 requirements/lock files; Pi-side
images are 185–393 MB each and every code change costs a tarball + 3 imports (pi2's is slow).
**Impact:** 13 images build unpinned — a rebuild can pull a newer `yfinance`/`pandas` (F24 happened).
**Recommendation:** consolidate to ~3 images by dependency profile (light: psycopg+requests+feedparser;
data: pandas+yfinance+pandas-ta; ml: FinBERT) each with a committed lockfile; the job is chosen by
`command:` — the screener already proves the pattern (one image, six CronJobs). **Trade-off:** one
build affects every job on that image, so smoke-test each job's entrypoint before rollout. **Optional
later:** mount scripts via ConfigMap so code-only changes need no rebuild at all. **Effort:** medium.

### AR-6 (M) Repo layout mixes code, images and manifests; SQL hidden in YAML
**Evidence:** `manifests/` holds Python, Dockerfiles and YAML; hyphenated module names
(`fx-fetcher.py`) cannot be imported, which is part of why job logic has no unit tests; schema SQL is a
string inside a ConfigMap.
**Recommendation:** see §4. A pure move with identical file contents needs **no image rebuild**; guard
it with the manifest-parity check (`refactor-safely`). **Effort:** medium. **Risk:** low-medium.

### AR-7 (M) Manifest boilerplate drifts
**Evidence:** per-job YAML repeats env, resources and policy in ~16 files; one job already differs
(`IfNotPresent`).
**Recommendation:** `kustomize` (built into `kubectl`, no new tool): a base CronJob carrying the
safeguards from AR-1 plus per-job patches, so a policy is changed in one place. Pairs with AR-6.
`workloads.py` then validates the rendered output. **Effort:** medium.

### AR-8 (M) Everything connects as the superuser; job logic is untested offline
**Evidence:** jobs, Grafana and the bot use the `postgres` role via the one DB Secret; the bot's read paths are
growing; job code is validated only by canaries on the cluster (impossible while it is down).
**Recommendation:** read-only roles for Grafana and the bot, a writer role for jobs, superuser only for
migrations/backups; extract pure functions (parse → rows) and add fixture tests, plus a few
idempotency tests against a throwaway Postgres. `tests/test_stocks.py` (in progress) is the right model.
**Effort:** medium. **Risk:** low (roles are additive; follow `migration`).

### AR-9 (M) No CI; concurrent sessions share one working tree
**Evidence:** no `.github/workflows`; during this review another session had uncommitted edits to the bot,
`yfinance-fetcher.py`, several manifests and docs while this one worked.
**Recommendation:** a GitHub Actions workflow (no secrets needed) running `workloads.py --check`, the test
suites, YAML lint, `shellcheck`, `gitleaks` and a Python compile — it would have flagged the doc drift
found on 2026-10-10. Give each session its own branch or `git worktree` so WIP is never committed by the
wrong session. **Effort:** small.

### AR-10 (H, needs decisions/hardware) Topology and backup risks
- **Control plane** is one 1 GB Pi 3B+ with SQLite state and **no state backup**. Back up `state.db` +
  node-token + certs (SQLite-safe copy), and plan a stronger control-plane host (not another 1 GB Pi).
- **TX2** now holds the DB, Docker and the k3s container store on **one USB SSD** (2026-10-10 change) and cannot
  run any pod without it. Separate "database host" from "legacy GPU host" when hardware allows.
- **Backups** are same-LAN dumps only; add an off-site encrypted copy and keep the restore drill quarterly.
- **Schedules** still follow the server's local time (clock change due 2026-11-01): decide `timeZone: UTC` via
  ADR 0002 — in a kustomize base (AR-7) it is a one-line change.
- **Power** is its own track and is **PLANNED** (owner replacing the supplies, 2026-10-10): see the
  `node-power-health` skill, the tracker item "Fix the Pi power supplies" in `pending-tasks.md` §1 (5.1 V / 3 A,
  short thick cables, 24 h clean-under-load acceptance), and the supply recommendation. The SSD is the **boot**
  drive: power it separately but keep its data path direct (powered enclosure / separate-power Y-cable); a hub in the
  boot path is unverified on Pi 3 / 3B+ — test on pi3 or a spare first.

### AR-11 (H) The backup job can keep empty dumps and prune good ones
**Evidence (verified on pi3, 2026-10-10):** the newest dump is 0 bytes (a failed run during the outage);
retention is `ls -t | tail -n +8 | xargs rm` by mtime, so empty files count as dumps — `set -e` makes a single
failure harmless, but a run of failed days followed by a success evicts good dumps (after 7 consecutive failures
none survive); no integrity check, non-atomic write; dumps are now ~165 MB (8 files = 792 MB, 208 GB free), so the
388 KB / 2 s drill figures in the docs are stale.
**Recommendation:** dump to a temp name → size floor + `pg_restore -l` → atomic `mv` → prune only *verified* dumps
(keep ≥ 7 verified); copy each verified dump to a second node (pull-based from pi1, checksummed, restricted key)
and off-site; alert when the newest verified copy is > 36 h old; re-run the restore drill on a real dump. Use the
Pi SSDs for the second copy before buying anything (a NAS only adds independence from the shared power class).
**Effort:** small. **Risk:** low — the script lives in the CronJob manifest, no image change; apply when calm.
**Immediate:** while the cluster is down, copy the last good dumps off pi3 to the workstation.

### AR-12 (M) Observability gaps on the nodes themselves
**Evidence (2026-10-10 ~12:00Z):** the 5-minute stats logger (ADR 0011) shows a **single sample** on pi0, pi1 and
pi3 hours after install; on pi0 the root crontab has no logger entry and the cron journal shows no 5-minute runs
(`/etc/cron.d` not inspected). The power fix's "24 h clean `throttle_hex`" acceptance depends on this logger, so
verify and repair it first. `nodewatch` is built but not installed (no cron entry on pi0).
**pi0 as the watcher / power-controller host:** the right *place* (outside k3s; hardware watchdog already enabled,
`RuntimeWatchdogSec=1min`; `/dev/gpiochip0` present; healthy at check time: `0x0`, 34.7 °C). Caveats: it is also the
only LAN DNS and boots from a microSD (ext4, rw), has an undervolt history (fix its supply first), and a home
watcher cannot see power/internet loss — pair it with an external dead-man's switch. If it ever drives relays, wire
them **normally-closed** (a dead controller leaves every node powered) and pick GPIOs whose boot state does not
energise the relay. Power-cycle on command, or only after a long silence plus an alert — a hard cut risks the SSD and
SQLite state. A TM4C123G LaunchPad would add fast, OS-independent rail logging but is not required; a smart plug or
an INA219 on a Pi covers the same needs more simply.
**Effort:** small. **Risk:** low.

## 4. Target repo layout (proposal)

```
src/        common/ (shared module, AR-2/3) + jobs/ (snake_case modules)
images/     one Dockerfile + lockfile per dependency profile (AR-5)
deploy/     kustomize base (safeguards, AR-1/7) + per-job patches
db/         schema as .sql files (rendered into the ConfigMap), migrations
tests/      unit + fixture + hook/tool tests
docs/  ops-tools/  .githooks/   (unchanged)
```

## 5. Phased plan

| Phase | Items | Risk | Gate |
|---|---|---|---|
| 0 | AR-1 safeguards in manifests; AR-11 backup-job fix | Low | Edit now; **apply only when the cluster is calm** |
| 1 | AR-2 shared module, AR-3 `job_runs`, lockfiles (AR-5), first fixture tests (AR-8), AR-12 logger repair | Medium | At natural image rebuilds; canary each job |
| 2 | AR-6 layout, AR-7 kustomize, AR-5 image consolidation, AR-8 DB roles, AR-9 CI | Medium | Mechanical; manifest-parity + `workloads.py --check` after every step |
| 3 | AR-4 DB QoS/probes, AR-10 control-plane state backup, off-site backup, hardware | Needs window / purchase | One change at a time |

## 6. Explicitly not recommended

Rewriting jobs in another language (measured: the cost is image size and rebuild friction, which AR-5 and a
ConfigMap-mounted-code option address without a rewrite; runtime is not the bottleneck); Airflow/Argo/Loki
(ADR 0008); a container registry before AR-5 reduces the image count (revisit ADR 0004's CGNAT argument
separately — a LAN registry needs no inbound access).

## 7. Decisions needed / ADR candidates

1. Adopt the safeguard defaults (AR-1) and where they live (kustomize base) — ADR.
2. Image consolidation by dependency profile and lockfile policy (AR-5) — ADR (touches ADR 0004).
3. `job_runs` as the durable run record (AR-3) — ADR (supersedes the heartbeat-v2 plan).
4. DB role model (AR-8) — ADR.
5. Schedule timezone (ADR 0002 revisit) — before 2026-11-01.
6. Control-plane host and DB-host separation (AR-10) — ADR; needs hardware.

## 8. How to re-measure the evidence

```bash
python3 ops-tools/workloads.py --check                      # docs vs manifests
# CronJob safeguards (counts of jobs that set each field) — parse manifests/**/*.yaml, kind: CronJob
grep -rlE "startingDeadlineSeconds|concurrencyPolicy|activeDeadlineSeconds|ttlSecondsAfterFinished" manifests | wc -l
# duplication of the house pattern across job scripts
for p in "psycopg.connect" "autocommit" "OperationalError" "DELETE FROM"; do
  printf "%-18s %s of %s\n" "$p" "$(grep -lE "$p" $(find manifests -name '*.py') | wc -l)" "$(find manifests -name '*.py' | wc -l)"; done
find manifests -name Dockerfile | wc -l ; find manifests -name 'requirements*' | wc -l
```

## 9. Caveats

- Counts are from the repo (HEAD plus in-progress work), not the live cluster, which was degraded.
- Effort/risk labels are estimates; image-size figures were measured on the nodes, memory figures for
  non-Python alternatives were estimates.
- The in-progress Telegram work (`telegram-alerts`, new bot commands, `yfinance-fetcher.py` changes) was
  not reviewed here and still owes its docs update (the drift check flags it).
