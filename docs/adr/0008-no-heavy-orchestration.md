# 0008. No Longhorn, Loki, Argo/Tekton, or Citus on this cluster

- Date: 2026-10-04 (positions held since first design; recorded 2026-10-04)
- Status: accepted

## Context
pi2 is a 1 GB RAM control-plane that swap-thrashes under API bursts and once
died under registration-storm load. Every candidate add-on is evaluated against
that ceiling first. Longhorn/OpenEBS: constant API watching + PV orchestration —
for a single-node DB already protected by Retain + daily off-host pg_dump.
Loki: another always-on statefulset for logs that `kubectl logs` already serves
at this scale. Argo/Tekton: workflow controllers watch the API continuously —
staggered CronJobs already provide the needed sequencing. Citus: horizontal
Postgres for a database growing ~100 MB/year.

## Decision
All declined. Sequencing = staggered schedules; resilience = Retain PV +
measured restore drill (2 s); logs = kubectl; durability = pg_dump to pi3's SSD.
The daily-volume reality: this pipeline writes a few thousand rows/day.

## Consequences
- The cluster stays inside pi2's envelope; every "wouldn't it be nice" must
  beat the 1 GB ceiling argument (architecture doc §9, finds doc).
- True gaps (e.g. searchable log history, real HA) are consciously accepted,
  documented in the limitations register (§10), not accidents.
- Revisit triggers: a second control-plane node, pi2 hardware upgrade, or a
  workload that genuinely outgrows staggered CronJobs.
