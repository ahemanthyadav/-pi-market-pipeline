---
name: Architecture Decision Record
description: Use when making or documenting a decision with long shelf life — the ADR template, when an idea deserves one, and where they live (docs/adr/).
---

# ADRs

## When to write one
- A choice that's expensive to reverse (schema shape, the no-registry image
  strategy, adding a dependency, table grain) or that future-you will question
  ("why isn't there a git repo?", "why no Nifty 500 feed?").
- Not for: bug fixes, tag bumps, anything a log line explains.
- Rule of thumb: if re-deriving the answer would take >1 hour, or the answer
  is "because of a non-obvious constraint", write it down.

## Template — `docs/adr/NNNN-kebab-title.md` (numbered sequentially)

```md
# NNNN. <Decision title>

- Date: YYYY-MM-DD
- Status: proposed | accepted | superseded by NNNN

## Context
What forces a decision: the real constraints (hardware, CGNAT, 1 GB nodes,
no registry) and the options considered — at least two, each with its true cost.

## Decision
One paragraph, active voice: "We X because Y."

## Consequences
- What this makes easy / hard later.
- What we must now always do (e.g. "any code change requires the full §6 cycle").
- When this should be revisited.
```

## House decisions worth ADRs if not yet written

All recorded (2026-10-04) — `0004` no registry · `0005` DELETE+INSERT
idempotency · `0006` index_prices pure-daily vs intraday split · `0007`
sentiment on CPU FinBERT despite the GPU node · `0008` no Longhorn/Loki.
Earlier: `0001` max_locks=256 · `0002` PDT schedules stay · `0003`
per-symbol backfills. Later: `0009`–`0013` (Telegram, gazetteer NER, node stats, multi-user, trade-date
timestamps); 2026-10-18: `0014` own adj_close · `0015` point-in-time fundamentals · `0016` chunk sizing ·
`0017` DB roles · `0018` signals gated by EV-0 · `0019` no UPS · `0020` repo layout stays ·
`0021` India fundamentals from NSE filings · `0022` LLM via hosted API, no local GPU.
New long-shelf-life decisions get the next number.
