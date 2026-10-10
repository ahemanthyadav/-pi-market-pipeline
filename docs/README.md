# Documentation Index — marketdata

> **What this repo is:** a home-lab market-data platform on a 5-node k3s cluster
> (Pi workers + Jetson TX2) ingesting ~1,000 instruments daily — indices, FX,
> commodities, yields, rates, news, FinBERT sentiment, FII/DII flows, technicals,
> and a 998-stock fundamental screener (Nifty 500 + S&P 500) — into TimescaleDB,
> with Grafana dashboards, Tailscale-only access, and no container registry.
> **Last verified 2026-10-09:** all 4 nodes Ready · **20 CronJobs live
> (telegram-digest added 2026-10-09, 08:00 IST)** · Telegram alert channel
> live (contact point + 3 rules) · **Telegram two-way listener live**
> (Deployment telegram-bot: /status /vix /nifty /sensex /gold /fii /scores
> /digest) · screener toolkit `local/screener:v7` ·
> health monitor `local/pipeline-health:v4`.

## Reading order (new session? start here)

1. `AGENTS.md` (repo root) — ground rules, invariants, DB access pattern, agent roster
2. `market-data-architecture.md` — what the system *is*
3. `market-data-pipeline-operations-manual.md` — how to *operate* it
4. Everything else, as needed

## The docs

| Doc | Purpose | Read when | Update when |
|---|---|---|---|
| **`pending-tasks.md`** | **The single tracker of everything not yet done** — immediate, security, features, v2, recurring, icebox; each item links to its owning doc | Start of any session / before planning work; after completing anything | Mark ✅ + date on completion; owning doc updated in the same session |
| **`market-data-architecture.md`** | Canonical system reference: nodes, tech stack, feed catalog, DB schema + live volumes, all workloads, security, limitations register, file/repo structure | You need to understand what exists and why | Any cluster/schema/workload change; capacity facts; limitations |
| **`market-data-pipeline-operations-manual.md`** | The runbook: image build/redistribute cycle (§6), daily health checklist (§7), failure recovery copy-paste commands (§8), backup/restore + drill (§9), DB query reference (§5) | Something breaks, or before/after any mutation | New failure modes, new jobs, new runbook lessons; feed quirks (§4) |
| **`market-data-pipeline-plan.md`** | The original design/build log — Phase 0→8 with per-phase build notes, decisions, and the incident history of building it (pi2 wedges, TX2 bring-up) | You want the "why did we do it this way" history | Phase-completion ticks; major scope changes |
| **`market-data-pipeline-architecture-roadmap.md`** | Hardening roadmap with live status: what's DONE (constraints, heartbeat, restore drill), what's next (alerts, feed gaps), what is deliberately NOT changing | Planning the next hardening step | Whenever a roadmap item completes or a new "do not change" decision lands |
| **`market-data-finds-and-projects.md`** | **32 hard-won finds** with fixes (infra gotchas, feed quirks, screener-rollout lessons, alerting-provisioning scars, ML capacity facts) + the tiered project catalog with recommended order | Before debugging anything (someone already hit it) or picking the next project | Every new gotcha; project completions |
| **`stock-screener-implementation-plan.md`** | The v1 BUILD ORDER for the Nifty 500 + S&P 500 screener — as-built schema, sources (EDGAR + mixed), CronJobs, balanced scoring formulas, validation bars, rollout phases with live status | Extending/fixing the screener layer | Any screener code/schema change; phase completions |
| **`nifty500_sp500_fundamental_analysis_implementation_plan.md`** | The TARGET ARCHITECTURE (v2+) above v1: security master, sector-relative 6-component scoring, classifications, style tags + investor lenses (§13), market-regime layer (§14), AI placement, binding ops constraints (§15) | Planning v2+ analysis features | When v1 scope shifts or a v2 item gets built |
| **`market-data-telegram-bot.md`** | The Telegram channel as built — digest CronJob, Grafana alert contact point, **and the two-way listener (deployed 2026-10-09)** — plus operating procedures (test-firing, threshold tuning, token rotation) and the remaining update catalog incl. Strata-chat blockers | Anything touching the bot or notification channel; planning further two-way work | Any bot/alerting change; new alert rules; two-way decisions |

## Roles in one line each

- **Architecture** = the map · **Ops manual** = the driving school · **Plan** = the
  travel diary · **Roadmap** = the maintenance schedule · **Finds** = the scars ·
  **Screener plan** = the current construction project · **Target architecture** =
  the city plan it grows into.

## House documentation rules

- Docs are the source of truth (no git yet) — update on every verified change; keep
  "Last verified" dates true.
- Feed quirks/symbol deaths → ops manual §4 **and** the fetcher script header.
- New failure modes → ops manual §8 (copy-paste fix commands).
- Long-shelf-life decisions → `docs/adr/` via the `adr` skill — 9 written
  (0001–0011, latest 2026-10-10: node-local stats logging; 0009 Telegram bot);
  see `docs/adr/` for the format.
- Secrets never enter docs — see AGENTS.md §7 for where they live. Neither do IP
  addresses (AGENTS.md §8): use node names/placeholders; real values are in the
  gitignored `.hosts.env`.
