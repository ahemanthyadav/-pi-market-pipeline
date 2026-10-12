# Documentation Index — marketdata

> **What this repo is:** a home-lab market-data platform on a 5-node k3s cluster
> (Pi workers + Jetson TX2) ingesting ~1,000 instruments daily — indices, FX,
> commodities, yields, rates, news, FinBERT sentiment, FII/DII flows, technicals,
> and a 998-stock fundamental screener (Nifty 500 + S&P 500) — into TimescaleDB,
> with Grafana dashboards, Tailscale-only access, and no container registry.
> **Status 2026-10-12 — recovered, power fix on trial.** The 2026-10-09→10 outages are over: all 4 nodes Ready, DB Running,
> all 23 CronJobs active and completing (verified 08:22 UTC); the root cause (Pi power) is only *claimed* fixed — all Pis moved
> to separate supplies ~02:30 UTC, 24 h acceptance review due ~02:59 UTC 2026-10-13 (pending-tasks §1; per-node roles: `node-roles.md`).
> Earlier healthy check 2026-10-09: all 4 nodes Ready · **23 CronJobs** (per `manifests/`; telegram-digest 08:00 IST) · Telegram alert channel
> live (contact point + 3 rules) · **Telegram two-way listener live**
> (Deployment telegram-bot: /status /vix /nifty /sensex /gold /fii /scores
> /digest) · screener toolkit `local/screener:v9` ·
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
| **`node-roles.md`** | Per-node jobs and responsibilities for pi0–pi3 + tx2: what each runs (pinned workloads, host cron jobs), CronJob placement, blast radius, current scheduling state | You need to know what a node is for, or what breaks if it dies | A pin, cordon, host job, image placement or hardware change |
| **`market-data-pipeline-operations-manual.md`** | The runbook: image build/redistribute cycle (§6), daily health checklist (§7), failure recovery copy-paste commands (§8), backup/restore + drill (§9), DB query reference (§5) | Something breaks, or before/after any mutation | New failure modes, new jobs, new runbook lessons; feed quirks (§4) |
| **`market-data-pipeline-plan.md`** | The original design/build log — Phase 0→8 with per-phase build notes, decisions, and the incident history of building it (pi2 wedges, TX2 bring-up) | You want the "why did we do it this way" history | Phase-completion ticks; major scope changes |
| **`market-data-pipeline-architecture-roadmap.md`** | Hardening roadmap with live status: what's DONE (constraints, heartbeat, restore drill), what's next (alerts, feed gaps), what is deliberately NOT changing | Planning the next hardening step | Whenever a roadmap item completes or a new "do not change" decision lands |
| **`market-data-finds-and-projects.md`** | **32 hard-won finds** with fixes (infra gotchas, feed quirks, screener-rollout lessons, alerting-provisioning scars, ML capacity facts) + the tiered project catalog with recommended order | Before debugging anything (someone already hit it) or picking the next project | Every new gotcha; project completions |
| **`stock-screener-implementation-plan.md`** | The v1 BUILD ORDER for the Nifty 500 + S&P 500 screener — as-built schema, sources (EDGAR + mixed), CronJobs, balanced scoring formulas, validation bars, rollout phases with live status | Extending/fixing the screener layer | Any screener code/schema change; phase completions |
| **`nifty500_sp500_fundamental_analysis_implementation_plan.md`** | The TARGET ARCHITECTURE (v2+) above v1: security master, sector-relative 6-component scoring, classifications, style tags + investor lenses (§13), market-regime layer (§14), AI placement, binding ops constraints (§15) | Planning v2+ analysis features | When v1 scope shifts or a v2 item gets built |
| **`market-data-telegram-bot.md`** | The Telegram channel as built — digest CronJob, Grafana alert contact point, **and the two-way listener (deployed 2026-10-09)** — plus operating procedures (test-firing, threshold tuning, token rotation) and the remaining update catalog incl. Strata-chat blockers | Anything touching the bot or notification channel; planning further two-way work | Any bot/alerting change; new alert rules; two-way decisions |
| **`data-foundations-schema-draft-2026-10-10.md`** | DRAFT (nothing applied): verified fundamentals/price data defects (DQ-2, DQ-3, G-1) and the additive schema + writer plan that fixes them (`financial_facts`, `corporate_actions`, membership snapshots, factor returns) | Before touching `stock_fundamentals.py`, `stock_prices.py` or the schema ConfigMap | The draft is applied, amended or rejected (record which) |
| **`evidence-based-signals-roadmap.md`** | Which screener/bot signals have research backing, which do not, the replacement for each weak one, and the build order (EV-0…EV-18) with a written acceptance test | Before adding or re-weighting any factor, screen or score | A signal is tested (record pass/fail in §5), added, or dropped |
| **`ml-roadmap-2026-10-10.md`** | The ML/LLM plan beyond ranking signals: ML-0…ML-8, **each labelled by research backing 🟢🟡🔵⚪** (experiment infra, anomaly detection, news embeddings, vol forecasts, regime, peer clusters, hard-gated GBM ranker, **LLM via hosted API**), guardrails, phasing, data/deploy pattern, risks, ADR candidates | Planning any model or LLM work; before touching the digest/bot narrative | When an ML item is built, rejected, or gated differently (update the tracker in the same session) |
| **`prediction-validation-and-training-2026-10-10.md`** | Pipeline so every daily prediction is logged write-once, resolved against outcomes on adjusted prices, scored against baselines and monitored; plus the offline train → gate → shadow → promote path for components that learn. Inventory of what is predicted today, schema, daily jobs, per-kind validation rules, acceptance tests (PV-0…PV-3, TP-0…TP-2) | Adding or changing any score, forecast or model; judging whether a prediction works | When a prediction kind is added/retired or a threshold decision (ADR) lands |
| **`architecture-review-2026-10-10.md`** | Architect's review of the repo/system structure: strengths to keep, 12 findings (AR-1…AR-12) with evidence, target repo layout, phased plan, ADR candidates, how to re-measure | Planning structural/refactor work; before adding jobs or touching manifests | When an AR item is applied or rejected (update the tracker in the same session) |

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
- Long-shelf-life decisions → `docs/adr/` via the `adr` skill — 11 written
  (0001–0011, latest 2026-10-10: node-local stats logging; 0009 Telegram bot);
  see `docs/adr/` for the format.
- Secrets never enter docs — see AGENTS.md §7 for where they live. Neither do IP
  addresses (AGENTS.md §8): use node names/placeholders; real values are in the
  gitignored `.hosts.env`.
