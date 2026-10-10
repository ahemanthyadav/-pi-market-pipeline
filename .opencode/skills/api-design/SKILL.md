---
name: API Design
description: Use when designing an HTTP/data interface or when consuming upstream feeds — tolerance for feed drift, retries and rate limits, versioning and deprecation; applies to upstream market feeds and the upcoming screener API.
---

# API design

## Consuming feeds (the pipeline's real problem)
- **Expect drift.** Upstreams change shape silently (NSE FII/DII dropped its
  `{data:…}` envelope). Parse tolerantly: locate the payload, WARN-and-continue
  on missing items, hard-fail only when nothing arrives. Record quirks in
  manual §4 + the script header.
- **Retries with backoff**, few (2–3 attempts), with a per-item timeout. The
  cron cadence gives a fresh chance daily — never hammer a dying feed.
- **Rate limits:** batch (one yfinance call for 28 tickers, not 28 calls).
- **Validate at the edge:** schema-check the response before writing — right
  types, plausible ranges. Bad data entering the DB costs 10× more to remove
  than to reject at the door.
- **Symbols die** (`FTSE.MI` → `FTSEMIB.MI`). Keep symbol maps in one place per
  fetcher, WARN on missing, and make symbol swaps a one-line change.

## Designing our own interfaces (screener / fundamental-analysis v2)
- Resource-oriented paths, plural nouns: `/api/v1/symbols`,
  `/symbols/{id}/fundamentals`.
- Version in the path from day one (`/v1/`) — we consume feeds that didn't
  version and paid for it.
- JSON with snake_case keys (matches the DB); ISO-8601 UTC timestamps.
- Pagination + an explicit `as_of` on anything serving time-series — no
  implicit "latest".
- Errors: machine-readable code + human message; never a bare 500.
- Deprecation: new version ships alongside old for ≥1 release cycle; the old
  one logs a deprecation notice with a sunset date. No silent breaking.
- Auth: tailnet-only is the current perimeter. If anything is ever exposed
  beyond it, auth + TLS are prerequisites, not features (manual §10).
