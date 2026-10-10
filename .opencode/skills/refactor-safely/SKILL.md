---
name: Refactor Safely
description: Use before restructuring working code or k8s manifests — characterize current behavior first, plan a step series, verify after every step, keep manifest parity and image-tag discipline.
---

# Safe refactoring

1. **Characterize before changing.** Capture current behavior first: run it,
   record the output (row counts, log lines, dashboard screenshot), write
   characterization tests where behavior matters. If you can't describe the
   current behavior, you're not refactoring — you're rewriting.
2. **Plan the steps as a series of small diffs.** Each step independently
   verifiable and revertible alone. No step mixes "move code" with "change
   behavior" — behavior changes get their own step with their own test.
3. **Verify after every step.** Re-run the characterization check from step 1;
   the moment output diverges unexpectedly, stop and bisect.
4. **Manifest parity.** In k8s manifests, preserve every field that encodes
   operational knowledge: `imagePullPolicy: Never`, nodeSelector, tolerations,
   resource limits, `ReclaimPolicy: Retain`. A "cleanup" that drops one of
   these is an outage with a diff.
5. **Tag discipline.** Any behavior change inside a fetcher image = new tag +
   the full §6 rebuild cycle. Refactors shipped under an existing tag poison
   node caches silently (`Never`-pull).
6. **Keep history somewhere.** This isn't a git repo yet: finish each step
   with a dated one-line note in the relevant doc (what/why/date) — see the
   `commit-and-changelog` skill.
