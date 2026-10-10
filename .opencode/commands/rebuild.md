---
description: Full fetcher image rebuild + redistribute cycle (operations manual §6)
---
Rebuild and redeploy "$1" following `docs/market-data-pipeline-operations-manual.md` §6 exactly. If a target version is not specified, bump the patch version of the current `local/<name>` tag.

Before building, show me and get confirmation: the code diff, the tag bump, and which nodes the tarball must reach. Ask me for the TX2 and Pi SSH passwords — they are never in this repo.

Then execute the cycle: build on TX2 → save tarball → pull to the admin machine → distribute to pi1/pi2/pi3 (pi2 import detached + poll) → apply the CronJob → validation job → check logs against the expected success lines → verify DB rows → update `requirements.lock`.

Finish with: measured end-to-end time, any WARNs, and whether the manual needs a §3/§6 update.
