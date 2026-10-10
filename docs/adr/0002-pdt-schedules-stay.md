# 0002. Keep all CronJob schedules as-is despite the PDT discovery

- Date: 2026-10-04
- Status: accepted

## Context
Verified when the newly deployed screener chain ("0 2 * * *" documented as UTC)
fired at 09:00–09:30 **UTC** = 02:00 PDT: k3s's cron controller schedules in the
server's node-local timezone when no CronJob `timezone` is set. Every "UTC" time in
the docs has actually been firing at PDT since the pipeline's beginning. Options:
(a) convert all 19 schedules so they fire at the originally-intended UTC times;
(b) leave every schedule untouched and correct the documentation.

## Decision
We leave all schedules untouched and correct the docs (ops manual §3, architecture
§5.2): the existing cadence has been running for weeks — every fetch still lands
after its market close (NSE 18:15 UTC, US 05:30 UTC next-day, sentiment 07:15 UTC),
the staggering order holds, and the intraday job is hourly (timezone-agnostic).

## Consequences
- Zero re-validation risk; the pipeline's proven rhythm is preserved.
- All documented times must be read as node-local PDT; new jobs must be
  designed in PDT too (or set an explicit CronJob `timezone` — deliberate,
  documented, and validated, never silently).
- Revisit if the Pis' timezone ever changes (e.g., a DST policy shift in the
  cluster's nodes) — that would silently move every schedule.
