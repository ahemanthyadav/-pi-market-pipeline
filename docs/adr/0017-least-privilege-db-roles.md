# 0017. Readers get least-privilege DB roles; pipeline jobs stay on `postgres` for now

- Date: 2026-10-18
- Status: accepted

## Context
Every workload connected as the `postgres` superuser, including Grafana and the Telegram bot — the two processes
that take input from people (dashboards over the tailnet, chat commands). Options:
1. **Roles for everything** (readers + a writer role for the 18 pipeline jobs). The writer role needs INSERT/UPDATE/DELETE
   on every table and sequence; a missed grant fails jobs overnight across a 23-job blast radius.
2. **Roles for the human-facing readers only.** Small change (env + a Secret each, no image rebuild), removes the
   superuser from the exposed surface.

## Decision
We do option 2 now because it buys most of the risk reduction for almost none of the blast radius. `10-roles.sql`
(idempotent, in the schema ConfigMap) defines `grafana_ro` — SELECT on all tables incl. future ones via default
privileges, `default_transaction_read_only = on` — and `telegram_app` — SELECT plus INSERT/UPDATE/DELETE on `watchlist`
and `bot_users` only. Roles are created NOLOGIN by the schema; LOGIN + password are set out-of-band from Secrets
`grafana-db-ro` / `telegram-db` (never in git, never printed).

## Consequences
- A new table is readable by both roles automatically; a new *write* by the bot needs an explicit GRANT in `10-roles.sql`.
- Secret rotation procedure: ops manual §10. Research tools (EV-0 export) use `grafana_ro` so they cannot write.
- Revisit the pipeline writer role when jobs adopt `manifests/_common/mdjob.py` (AR-2) — one shared connect path makes a
  role switch a one-place change.
