# Telegram Bot — As-Built & Update Catalog

> **Purpose:** everything about the Marketfredbot Telegram channel — how the
> deployed digest + alert pipeline is wired, how to operate and change it, and
> the tiered menu of two-way/next-step upgrades with their real constraints.
> **Last verified: 2026-10-09** (digest live-fire-delivered; alert chain
> validated end-to-end with a real FII firing; two-way listener deployed and
> command-validated from the phone — /status /nifty /digest /scores answered).
> Related: ADR 0009 (the decision record) · finds §1.5 F29–F32 (the rollout
> scars) · ops manual §3/§6 (workload table, image cycle) · pending-tasks.md
> (what's still open).

---

## 1. What exists (deployed 2026-10-09; two-way added same day)

One bot — **@Marketfredbot** — one daily digest, one alert channel, and one
two-way listener, all sharing the same Secret and the same image:

```
CronJob telegram-digest ──08:00 IST──▶ ┌──────────────┐
                                        │ Telegram API │ ──▶ your chat
Grafana contact point "telegram" ◀───── └──────────────┘
        ▲            (alerts, 10m eval, policy tree → telegram)
pipeline_heartbeat / index_prices /            ▲
capital_flows / news_sentiment (read-only)     │ sendMessage only
                                    Deployment telegram-bot (pi1, always-on)
                                    getUpdates long-poll ←── your commands
                                    /status /vix /nifty /sensex /gold /fii
                                    /scores /digest /help
```

| Piece | Manifest | Notes |
|---|---|---|
| Digest script | `manifests/telegram/digest.py` | Read-only DB; exits 1 only on send failure; 4096-char guard; HTML parse mode |
| Two-way listener | `manifests/telegram/bot.py` | Long-poll `getUpdates` (offset in-memory, backlog drained on start); ONLY getUpdates consumer — Telegram 409s a second poller; single-user allow-list (strangers logged+ignored); DB connection per query (F26) |
| Image (one, two entrypoints) | `manifests/telegram/Dockerfile` | `local/telegram-digest:v2`, python:3.12-slim + psycopg/requests (versions in `requirements.lock`); CronJob uses CMD (digest.py), listener sets `args: [python, bot.py]` |
| Digest schedule | `manifests/telegram/cronjob.yaml` | `0 8 * * *`, **the only explicit-`timeZone` job** (Asia/Kolkata), pinned **pi1** (one-node import burden, roadmap §5) |
| Listener Deployment | `manifests/telegram/deployment.yaml` | 1×, pinned pi1, ~32 MiB; restarts on exit; command menu registered via `setMyCommands` |
| Alert contact point + rules | `manifests/grafana/provisioning.yaml` (`alerting.yaml` key) | Telegram contact point, policy tree → `telegram` receiver, 3 rules @ 10m |
| Grafana env | `manifests/grafana/deployment.yaml` | `$TELEGRAM_*` from Secret — same expansion pattern as `$POSTGRES_PASSWORD` |
| Secret | applied out-of-band, NOT a manifest | `telegram-bot` (`bot-token`, `chat-id`) — AGENTS.md §7 rule; rotation in §3.5 below |

Digest content (one message, ~900 chars): Nifty/Sensex/S&P/VIX/India-VIX/DXY/
Gold closes **with day-change %**, USD/INR, 7-day sentiment average, latest
FII/DII net, stale-feed warnings from `pipeline_heartbeat`, 3 newest scored
headlines.

## 2. Decisions already paid for (ADR 0009 — don't re-litigate)

- **One bot, two roles.** A dead token kills BOTH channels silently — job
  history (`kubectl get jobs -n market-data`) is the tell.
- **Token never in a file.** Grafana needs the chat *id* as a literal in the
  rendered file (F29), but the repo copy of `grafana/provisioning.yaml` carries the
  placeholder `__TELEGRAM_CHAT_ID__` (no personal id in git, 2026-10-10);
  `ops-tools/apply-grafana-provisioning.sh` renders the real one from Secret
  `telegram-bot` at apply time. Never `kubectl apply -f` that file directly.
- **CGNAT (F10) ⇒ webhooks are impossible.** Any "push" design is dead on
  arrival; everything must be outbound (this is what forces long-polling for
  §4's two-way tier).
- **Egress single point:** api.telegram.org via pi0's Pi-hole DNS. If an
  ad-list ever eats the domain, the stale-feed alert cannot announce itself
  through the same dead channel — `kubectl get jobs` + the 01:45 heartbeat
  rows remain ground truth.

## 3. Operating it

### 3.1 Fire the digest now (test or manual resend)
```bash
kubectl create job -n market-data telegram-digest-test --from=cronjob/telegram-digest
kubectl logs -n market-data job/telegram-digest-test --tail=5   # expect: "digest sent ..."
```

### 3.2 Change digest content or bot commands
Edit `digest.py`/`bot.py` → bump the tag in `cronjob.yaml` **and**
`deployment.yaml` → full ops-manual §6 cycle, **pi1 import only** (pinned; no
pi2/pi3 import needed). Then `kubectl rollout restart -n market-data
deployment/telegram-bot` — the listener is always-on and must re-read the
image; the digest CronJob needs nothing (its pods are created per run).
Update `requirements.lock` per §6 after any dependency-touching rebuild.

### 3.3 Tune or add alert rules
Edit `grafana/provisioning.yaml` (`alerting.yaml` key) →
`bash ops-tools/apply-grafana-provisioning.sh` (`--dry-run` first; it renders the
chat id from the Secret — never plain `kubectl apply -f`) →
**wait ~60 s before deleting the pod** (F32: a pod recreated too fast can
mount the previous ConfigMap revision and crash-loop on the old error).
Alerting is **all-or-nothing per file** — one bad rule takes the contact point
down and crash-loops Grafana (F29–F31). Current thresholds (first guesses):

| Rule | Trigger | Tuning note |
|---|---|---|
| Stale pipeline feed | `pipeline_heartbeat` fresh=false count > 0 | solid as-is |
| VIX above 25 | `^VIX` close > 25 | watch real volatility first |
| Large FII outflow | latest FII net < −3000 Rs cr | **fired legitimately at −12,944** on day one; raise to −5000+ if too chatty |

### 3.4 Validate the alert chain end-to-end (no test endpoint exists, F31)
Channel sanity check first — token + chat id + pi0 egress DNS in one shot
(`@@TELEGRAM_*@@` resolve from `.secrets.env` at run time; no values on the line):
```bash
python3 ops-tools/runcmd.py pi0 pi0 'curl -s https://api.telegram.org/bot@@TELEGRAM_BOT_TOKEN@@/getMe'
python3 ops-tools/runcmd.py pi0 pi0 'curl -s -d chat_id=@@TELEGRAM_CHAT_ID@@ -d text="alert-chain test" https://api.telegram.org/bot@@TELEGRAM_BOT_TOKEN@@/sendMessage'
```
Temporarily: group `interval: 10m → 1m` AND stale-feed threshold `gt 0 → gt -1`
→ apply → fresh pod → rule goes `firing` within ~2 min → message arrives →
**revert both** → rule resolves (resolve message = the return path validated).
Check states live:
```bash
# policy tree:      GET /api/v1/provisioning/policies        (kebab-case! F31)
# rules + states:   GET /api/prometheus/grafana/api/v1/rules
# contact points:   GET /api/v1/provisioning/contact-points   (nested receivers list)
```

### 3.5 Rotate the token / Secret
BotFather `/revoke` → `kubectl -n market-data delete secret telegram-bot` →
recreate with `--from-literal` (out-of-band, never a file) → restart Grafana
pod (digest pods pick it up per-run automatically). Remember: the chat-id
literal in `provisioning.yaml` is unaffected by token rotation.

### 3.6 Operate the two-way listener
```bash
kubectl logs -n market-data deploy/telegram-bot -f
# "listening as @Marketfredbot …"   startup OK
# "drained N backlog update(s)"     the pre-restart queue, skipped by design
# "answered /status"                a command round-trip (→ phone)
# "IGNORED chat=…"                  a stranger found the bot — expected; allow-list held
```
- **Restart semantics:** the offset is in-memory; on start the backlog is
  drained without replying, so a restart never replays old commands. A
  command sent while the pod is down is dropped — acceptable for idempotent
  read-only replies.
- **Only one poller, ever.** Telegram answers 409 to a second `getUpdates`
  consumer on the same token — including a local test script left running.
  The digest CronJob and Grafana only `sendMessage`; they are safe.
- **Quick health check:** send `/status` from the phone → expect
  `answered /status` in logs within a second (the poll holds ~25 s server-side,
  so replies are near-instant).

## 4. Update catalog (tiers; pick, then check pending-tasks discipline)

### Tier 1 — quick wins (days, no new infrastructure)

1. **Sentiment-drop rule** — the one candidate from finds Tier 1 #1 still
   unwritten (e.g., 7-day mean < −0.15). Pure addition to `alerting.yaml`.
2. **Threshold tuning pass** — §3.3 table; two weeks of real firings first.
3. **Watchlist section in the digest** — a `watchlist` table (ticker, note)
   joined to `stock_prices`/`stock_scores`; manual-INSERT pattern like FDI.
   First step toward the portfolio layer riding the same channel.
4. **Weekly chart digest** — Grafana render-to-PNG → `sendPhoto`. Needs the
   image-renderer plugin investigated first (headless Chromium on ARM64 = not
   trivial; treat as research item).

### Tier 2 — two-way interface — ✅ DEPLOYED 2026-10-09 (see §1)

As built: exactly the design below, plus three as-built decisions —
`/start` maps to help, unknown commands get the help text back, and the
backlog is drained on start so a restart never replays old commands.
Validated from the phone 2026-10-09: /status /nifty /digest /scores all
answered; zero errors, zero restarts, strangers' messages never answered.

**Architecture (forced by F10):** an always-on **Deployment** running a
`getUpdates` long-poll loop (offset-tracked, `timeout=25 s`) — NOT a webhook.
Outbound-only, survives CGNAT, no VPS.

- New `bot.py` entrypoint alongside `digest.py`; same base image contents
  (requests + psycopg already in v1) → tag `v2`; still pi1-only.
- **Security model: single-user.** Only the allow-listed chat id answers;
  other senders are logged and ignored. Telegram bots are public — anyone
  who guesses @Marketfredbot can message it; the allow-list is the door.
- Command surface (all read-only SELECTs — house rule):

| Command | Answers from | Notes |
|---|---|---|
| `/status` | `pipeline_heartbeat` | the /health checklist, in your pocket |
| `/vix` `/nifty` `/sensex` `/gold` | `index_prices` | latest close + day change |
| `/fii` | `capital_flows` | latest net, 5-day trend |
| `/scores` | `stock_scores` | current top-25 shortlist digest |
| `/digest` | (re-runs digest logic) | on-demand resend |

- Grafana alerts keep flowing untouched — the contact point and the listener
  share the bot token; Telegram allows concurrent getUpdates + sendMessage.
- One process, ~30–50 MB RAM on pi1; restartPolicy Always, liveness = log
  heartbeats in a `bot_state` row (or reuse `pipeline_heartbeat`).

### Tier 3 — Strata-backed chat (needs decisions before build)

Free-text messages → the workstation's Strata server (Qwen3.8-Flash-Next) →
AI answers in Telegram, streamed by **message-edit** every few seconds
(`editMessageText`), thinking folded via `reasoning_effort` (map `/think
low|medium|high`).

**Blockers, verified 2026-10-09:**
- Strata binds `127.0.0.1:8080` **only** — unreachable from the cluster.
  Needs a Strata serve flag for 0.0.0.0 (check `serve --host`), or an SSH
  tunnel/Tailscale serve front; workstation LAN IP is `<workstation-lan-ip>`.
- Workstation uptime becomes a dependency of a cluster service — WoL or
  "accept it's best-effort" are the only honest options.
- Latency reality: ~1.5–2K tok/s prefill locally ⇒ seconds-to-minutes to
  first token on long chats. Acceptable for async Q&A, not for chat-as-UX.
- Conversation memory: keep last-N turns per chat in a small table, or send
  Strata's `--conversation-cache` a session key (its prompt cache makes
  re-reads cheap — see Strata docs).

### Icebox (deliberately not now)

- Inline keyboards / alert acks (callback state, heavier parsing).
- Multi-user allow-list + per-user watchlists — until a second human asks.
- Voice notes → whisper → command (fun, zero homelab value).

## 5. Gotcha index (don't re-pay these)

F29 digit-typing in env expansion · F30 nonzero relativeTimeRange ·
F31 receiver-before-route + moved API paths · F32 ConfigMap cache lag — all
in `market-data-finds-and-projects.md` §1.5; ADR 0009 for the decision
record; cluster-mutation skill for any apply/restart/import discipline.
