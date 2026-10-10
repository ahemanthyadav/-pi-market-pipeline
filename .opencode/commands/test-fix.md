---
description: Validate the latest pipeline change end-to-end and fix what it broke
---
Validate the most recent change to the market-data pipeline and fix what it broke.

1. Identify the most recently modified fetcher script or manifest (ask me if ambiguous) and summarize the intended change.
2. Load the `test-writing` skill for the validation conventions.
3. Validate: `kubectl create job -n market-data <name>-validate --from=cronjob/<name>`, poll status, read the logs — expected success lines are documented per fetcher in the operations manual §6. Verify the DB actually changed with a read-only query (§5).
4. For each failure or WARN line: reproduce it, form a hypothesis, fix the code — then run the §6 rebuild cycle if the image changed. Confirm with me before each cluster mutation.
5. Report: what was broken, the root cause, the fix, and the evidence it now works.
