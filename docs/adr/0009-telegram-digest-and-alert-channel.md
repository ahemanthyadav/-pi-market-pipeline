# 0009. Telegram bot: one channel for the daily digest and pipeline alerts

- Date: 2026-10-09
- Status: accepted — deployed and live-fire-validated 2026-10-09

## Context
Findings Tier 1 #6 (digest bot) and #1 (Grafana alert rules) share one blocker:
the notification-channel decision (pending-tasks 🤔). The digest is pure reuse —
every number it sends already sits in existing tables; alert rules are pure
ConfigMap additions once a contact point exists (roadmap §5). The house is
CGNAT'd (F10), so the channel must be outbound-only. AGENTS.md forbids secrets
in files/code/chat output — and the cluster already carries two plaintext
secret files (fred-api, grafana-admin) flagged for scrubbing in pending-tasks §2.

## Decision
1. **Telegram Bot API**, one bot, two roles: digest CronJob (08:00 IST) and
   Grafana alert contact point.
2. Credentials live in Secret `telegram-bot` (`bot-token`, `chat-id`), created
   out-of-band via `kubectl create secret` — never in a manifest, unlike the
   two legacy secret files. One nuance forced by Grafana's env expansion
   (find F29): the CHAT ID is a literal in `grafana/provisioning.yaml`
   (digit-only expansions get re-typed as numbers and rejected; the chat ID
   is an identifier, not a credential). The TOKEN stays Secret-only and
   env-expanded — it is alphanumeric, so the typing bug cannot hit it.
   *Update 2026-10-10:* the repo copy now holds a placeholder
   (`__TELEGRAM_CHAT_ID__`); `ops-tools/apply-grafana-provisioning.sh` renders the
   id from Secret `telegram-bot` at apply time, so no personal id is in git.
3. The digest CronJob is the ONLY job with an explicit `spec.timeZone`
   (Asia/Kolkata). Existing schedules stay node-local PDT per ADR 0002; a new
   job states its intent instead of inheriting the accident.
4. Pinned to pi1: import burden = one node (roadmap §5), pi2 stays light by
   policy.
5. The Grafana contact point reads `$TELEGRAM_*` via env expansion in
   provisioning — same mechanism as `$POSTGRES_PASSWORD` in the datasource.
   Token is deployment config, never rule logic (roadmap §5).

## Consequences
- Token rotation = update Secret + restart consumers (digest pods are
  per-run; Grafana needs a rollout restart). A dead token kills BOTH channels
  silently — digest job history (`kubectl get jobs`) is the tell.
- Both roles share one egress dependency (api.telegram.org via pi0 DNS). If
  Pi-hole's lists ever eat the domain, the stale-feed alert cannot announce
  itself through the same dead channel: the 01:45 pipeline-health DB rows and
  `kubectl get jobs` remain ground truth.
- Alert thresholds (VIX 25, FII −3000 Rs cr) are first guesses recorded in
  `grafana/provisioning.yaml`; tune after watching real traffic.
- Contact-point env expansion AND rule firing must be validated live (F1:
  API-pass ≠ UI-works) before the pending-tasks items close.
- Portfolio alerts (concentration, drift) will ride the same contact point
  once a holdings layer exists; nothing here changes then.
