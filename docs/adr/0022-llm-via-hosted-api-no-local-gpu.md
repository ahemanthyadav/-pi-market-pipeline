# 0022. LLM inference via a hosted API key — no local GPU, no agent framework

- Date: 2026-10-18
- Status: accepted (owner decision on the GPU; refines ML-7)

## Context
ML-7 (digest narrative, shortlist narration, story summaries, a gated `/ask` in Telegram) needs an LLM. Options: the
workstation's RTX 3090 running Strata (free, local, but ties the pipeline to a desktop being on and exposed to the
LAN), or a hosted API with a key. Separately: build the LLM steps as an agent framework (LangGraph and similar) or as
plain jobs.

## Decision
**Hosted API only** (owner, 2026-10-18): the 3090 / Strata is not part of this system. The provider is chosen by the
owner and set through `LLM_PROVIDER` / `LLM_MODEL` / `LLM_API_KEY` (local `.secrets.env`, cluster Secret `llm-api`,
created out-of-band — never in git or chat). Code talks to one OpenAI-compatible chat endpoint (`LLM_BASE_URL`), so
switching provider or model is a config change, not a rebuild.
**No agent framework for now:** ML-7a/b/c are single calls (facts JSON in → schema-checked JSON out); `/ask` is a
small tool-calling loop over an allow-listed menu of read-only queries (`grafana_ro`, statement timeout, row limits).
Adopt PydanticAI if `/ask` grows typed multi-step tools; LangGraph only for long-running, resumable agents with
human approval steps — nothing planned needs that.

## Consequences
- LLM jobs run as normal CronJobs on the Pi workers (they only make HTTPS calls; no GPU, small images).
- Outbound data is public market data only; never send Telegram chat ids, watchlists or holdings to the provider.
- LLM output is never a scoring input (ADR 0018); every number in generated text must match the facts JSON (validator);
  if the API fails the digest is sent without the narrative.
- Cost is a few dollars a month on a small model at the planned volume (re-check the provider's current pricing).
- Supersedes the "Strata-backed chat" Tier 3 option in `market-data-telegram-bot.md`.
