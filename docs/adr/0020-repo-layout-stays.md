# 0020. Repo layout stays; CronJob safeguards are enforced by a test, not a kustomize base

- Date: 2026-10-18
- Status: accepted

## Context
Architecture review AR-6/AR-7 proposed moving to `src/ images/ deploy/ db/` with a kustomize base, so that the
CronJob safeguards (Forbid, deadlines, TTL, history limits) live in one place instead of 23 files. Costs found when
planning it: every manifest path referenced by the runbooks, CI, `ops-tools/workloads.py` and two months of docs
changes; the owner's apply workflow becomes `kubectl apply -k`; no runtime behaviour improves. The actual risk being
addressed is drift — a new or edited CronJob silently missing a safeguard.

## Decision
We keep one directory per job (code + Dockerfile + manifest together, as the review's own "keep" list says) and enforce
the safeguards with `tests/test_manifest_safeguards.py` in CI: every CronJob must carry concurrencyPolicy Forbid,
starting and active deadlines, a TTL, history limits ≤ 3/1, a backoffLimit, `imagePullPolicy: Never` for `local/*`,
resource limits, and no inline password/token env.

## Consequences
- Adding a CronJob without the safeguards fails CI before it can be applied.
- The test counts CronJobs (23): adding or removing one means updating that number on purpose.
- Revisit if image consolidation (AR-5 step 3) restructures the directories anyway — then a kustomize base costs little extra.
