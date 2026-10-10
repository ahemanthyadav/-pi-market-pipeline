---
name: Commit and Changelog
description: Use when recording completed work — conventional commit format for when this workspace becomes a git repo, changelog discipline, and how to keep history in docs before that.
---

# Commits & changelogs

## Conventional commits (adopt when this workspace becomes a git repo)

`<type>(<scope>): <imperative summary ≤72 chars>`

- Types: `feat`, `fix`, `docs`, `ops`, `refactor`, `test`, `chore`.
- Scope = component: fetcher name, manifest dir, or dashboard.
- Body explains why over what, and links the evidence (job name, row counts).
- Examples:
  - `fix(yfinance): drop dead ^CNXAUTO symbol, bump image to v5`
  - `ops(grafana): move database into jsonData (Grafana 12 requirement)`

## Changelog discipline
- Group by Added / Changed / Fixed / Known gaps; user-visible language.
- Every fix names its symptom, not just its cause.

## Until then (no git yet)

- Record completed work as dated entries in the relevant doc: manual §3
  (schedules & images), §4 (feed quirks), §12 (gaps opened/closed) — ISO dates.
- The manual's "Last verified" line is the workspace's clock; keep it true.
- A change that isn't written down somewhere in `docs/` did not happen.
