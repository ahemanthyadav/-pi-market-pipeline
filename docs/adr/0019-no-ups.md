# 0019. No UPS — a mains loss is an accepted, self-recovering outage

- Date: 2026-10-18
- Status: accepted (owner decision)

## Context
On 2026-10-18 ~06:00 UTC a mains power loss rebooted all five machines; `nodewatch` on pi0 went down with them, so nothing
alerted. Everything recovered unaided: nodes Ready, DB restarted once, no data loss, no failed CronJob after the window
(AGENTS safeguards skip stale runs; writers are idempotent, ADR 0005). Options: a small UPS for pi0 + router (keeps the
watcher alerting), a rack UPS (also spares SSDs hard power cuts), or none.

## Decision
We run without a UPS (owner, 2026-10-18) because recovery is automatic and a home-lab daily-batch system tolerates a short gap.

## Consequences
- During a mains loss there is no alert; the gap is visible afterwards in `node-stats` CSVs (sample gaps) and in
  `power-review.sh`, which reports gaps as FAIL — read such a FAIL against the boot times before blaming a supply.
- Repeated hard power cuts are a wear risk for the boot SSDs and the TX2 `sda4` DB disk; the daily dump + its second copy on
  the workstation (ops manual §9) is the mitigation. Off-site copy still pending.
- Not to be re-proposed unless outages become frequent or data is ever lost.
