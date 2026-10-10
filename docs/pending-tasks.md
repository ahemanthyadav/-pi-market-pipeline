# Pending Tasks — the single tracker

> **Purpose:** one authoritative list of everything not yet done. Detail lives in
> the linked docs — this file is the index + status. Maintained per AGENTS.md docs
> discipline: mark items ✅ with a date (and where the completion is recorded) when
> done; prune ✅ lines into the relevant doc's history at housekeeping time.
> **Last reviewed: 2026-10-10** (2026-10-09→10 outage — recovery in progress, see §1;
> node-local stats logging deployed per ADR 0011; screener v8 fixes + first
> full-quality run verified 2026-10-09; Grafana screener dashboard live).

Legend: 🔶 pending · ⛔ blocked (by what) · 🔄 recurring · 🤔 needs a decision ·
🧊 icebox (deliberately not doing — kept visible so it stays deliberate)

---

## 1. Immediate (next checkpoint: tomorrow's `/health`)

- [ ] 🔶 **2026-10-09→10 outage recovery (IN PROGRESS)** — pi2 wedged ~16 h;
  root cause found by the new stats logger: LIVE undervoltage+throttle on
  pi2 (0xd0005, 62 °C) — physical PSU/cable check pending. All CronJobs
  SUSPENDED (etcd-persisted) to stop catchup storms on the single-node
  control plane; agents failed on pi1/pi3/TX2; DB pod down (data safe, PV
  Retain). Remaining: PSU check → agents pi3→pi1→TX2 (§8 order) → verify
  timescaledb Running → unsuspend in dependency order (fetchers →
  sentiment/ner → ta → screener chain → health) → delete stale Jobs (nse,
  digest) → refire missed runs (nse, fiidii, ~15× intraday, yfinance,
  digest). Detail: ops manual §8 (newest subsection); ADR 0011.
- [x] ✅ **Node-local stats logging** — deployed + first-sample-verified
  2026-10-10 on pi0/pi1/pi2/pi3/TX2 (ADR 0011): root-cron CSV every 5 min
  at /var/log/node-stats/stats.csv (load/cpu/mem/swap/temp/throttle-hex/
  k3s-state/db-procs/disk), logrotate weekly×8, keeps recording while k3s
  is dead. Puller: `ops-tools/collect-node-stats.sh` (passwords + host aliases
  resolve from the gitignored local files — no env needed). First catches: pi2 live uv+throttle,
  pi0 past flags 0x50000, TX2 root disk 84%.
- [x] ✅ **Verify first full-quality scoring run** — done 2026-10-09, one day late:
  the run had been failing silently every night since 10-05 — the screener's SP500
  leg died at the NIFTY→SP500 boundary (pod→DB connection drop; the one script
  still on the pre-2026-10-04 connection layout). Fixed in image v8 (house pattern
  + leg-level reconnect-retry) together with the report job's missing-ts-filter
  bug (it reported the union of all historical top-25s). Canary-validated:
  **997 scored / 888 eligible / 50 shortlisted; 25+25 reports + digest**.
  Evidence: screener plan §13 F/G rows; ops manual §8 recurrence note.
- [x] ✅ **Grafana screener dashboard** — done 2026-10-09, ConfigMap-only per plan:
  "Stock Screener" (uid `screener`) — per-universe variable, top-25 table,
  median-composite trend, top-10-by-factor panels; all SQL pre-flighted against
  live data. Evidence: screener plan §13 Phase H.

## 2. Security & hygiene (this week)

- [x] ✅ **Secrets kept out of git** — done 2026-10-10: single gitignored local
  store `.secrets.env` (template `.secrets.env.example`); docs/tools carry no
  values (`@@PW@@` token + `ops-tools/_creds.py`); secret manifests + 
  `validation/grafana/` gitignored; `.example` secret manifests added; agents denied
  read of `.secrets.env` in `opencode.jsonc`. Credential rotation is explicitly
  NOT a priority (owner decision 2026-10-10). Detail: ops manual §10.
- [ ] 🔶 **Verify the CGNAT claim** — 2026-10-10 measurement: the public IP this
  LAN egresses with EQUALS the router's WAN IP (docs concluded CGNAT from the
  opposite). One check from one workstation; confirm on the router's WAN page or
  from the phone off Wi-Fi. If not CGNAT: "no inbound ports by construction" is
  false and the stale UDP 51820 forward may be reachable — remove it first. Detail:
  ops manual §12.9.
- [ ] 🔶 pi0 → tailnet (remote Pi-hole admin + ad-block DNS on the move).
  Detail: ops manual §12.6.
- [ ] 🔶 Remove dead router UDP 51820 port-forward (WireGuard leftover).
  Detail: roadmap §11.

## 3. Next features (roadmap order)

- [ ] 🔶 **Deploy `nodewatch` on pi0** — out-of-cluster dead-man's switch (would have caught the
  2026-10-09 outage in ≤5 min). Script + tests done 2026-10-10 (`tests/test-nodewatch.sh`, 9/9); install steps
  in ops manual §11. Needs the Telegram credentials placed on pi0 (a new secret location — your call).

- [x] ✅ **Telegram digest bot** — deployed + validated 2026-10-09 (ADR 0009).
  08:00 IST (only job with explicit timeZone), pinned pi1; Secret `telegram-bot`
  applied out-of-band; test digest delivered to chat; first scheduled run
  2026-10-10 08:00 IST. Rollout gotchas recorded as finds F29–F32.
  Detail: findings Tier 1 #6, §3; ADR 0009; `manifests/telegram/`.
- [ ] 🔶 **Grafana alerting tuning** — Telegram contact point + policy tree +
  3 rules (stale feed, VIX spike, FII outflow) deployed AND live-fire-validated
  2026-10-09 (FII rule fired on real data: −12,944 Rs cr). Remaining:
  sentiment-drop rule; threshold tuning (VIX 25 / FII −3000 are first guesses —
  FII fired at −12.9K, consider −5000+ if too chatty).
  Detail: findings Tier 1 #1; architecture §12.4; ADR 0009.
- [x] ✅ **Telegram two-way interface** — deployed + validated 2026-10-09:
  listener Deployment `telegram-bot` (pi1, image v2, long-poll getUpdates —
  CGNAT/F10 rules out webhooks), single-user allow-list, backlog drain on
  start, command menu registered via setMyCommands. Commands validated from
  the phone: /status /nifty /digest /scores, zero errors. Full set: /status
  /vix /nifty /sensex /gold /fii /scores /digest /help. Strata-backed chat
  (doc §4 Tier 3) remains blocked on Strata's 127.0.0.1-only bind +
  workstation-uptime decision.
  Detail: `market-data-telegram-bot.md` §1/§3.6/§4; ADR 0009.
- [x] ✅ **Entity/event extraction on headlines** — done 2026-10-09 (ADR 0010):
  `headline-ner` CronJob, TX2 at 00:45 PDT, image v3. Gazetteer-first
  (deterministic ticker_names matching, no model) → `headline_entities`
  (instrument-linked; 323 rows over the 563-headline history) +
  `headline_events` (16-type keyword taxonomy; 163 rows). False-positive
  stoplist tuned from measured canary data (v1→v3: 380→323). Model-based NER
  stays on the 3090 layer (roadmap §7). Feeds findings #10 (per-company
  sentiment) — buildable anytime. Detail: ADR 0010; ops manual §3/§4.
- [x] ✅ **RBI G-Secs / repo rate feed** — done 2026-10-09, no third-party feed
  needed: `rbi-fetcher` (07:00 PDT) scrapes the official RBI mobile "Current
  Rates" widget → 7 policy rates into `interest_rates` (IN_REPO 5.50 etc.),
  5 G-Sec tenor buckets + 3 T-bill cut-offs into `bond_yields`
  (IN_GS_10Y 7.29 on first run). Writes its own `pipeline_heartbeat` row
  ('rbi'). India yields panel added to the Bonds dashboard. Detail: findings
  Tier 2 #8; ops manual §4/§12.
- [ ] 🔶 **Nifty 500 / Auto / FMCG index sources** — split 2026-10-09: Nifty 500
  ✅ restored via Yahoo `^CRSLDX` (nse-fetcher v3, 9/9 tickers live). Auto/
  FMCG 🔶 confirmed dead across all Yahoo symbol families; remaining avenue is
  NSE-direct (session-cookie API, fiidii-fetcher pattern) or jugaad-data.
  Detail: findings Tier 2 #9; ops manual §12.2.
- [ ] 🔶 Per-job heartbeat v2 + fetcher-internal upstream guards — lands with
  the next NATURAL image rebuilds (don't rebuild 9 working images just for
  this). NEW jobs start on the v2 pattern directly (rbi-fetcher already writes
  its own 'rbi' row; the health job's FEEDS list adopts new feeds at its next
  natural rebuild). Detail: roadmap §3.1/§3.2.
- [ ] 🔶 `news_sentiment`/`raw_headlines` unique constraints (need ON CONFLICT
  in scorer/fetcher first). Detail: ops manual §12.5; roadmap §3.4.

## 4. v2+ (target architecture — build on v1's tables)

- [ ] Sector-relative 6-component scoring + classifications. Detail: target
  architecture §5–§6.
- [ ] Style tags + investor lenses (Phase 3.5; DCF lens deferred to Phase 5).
  Detail: target architecture §13.
- [ ] Market-regime layer (Phase 3.6) — FRED-sourced series (T10Y2Y, HY OAS,
  Buffett indicator) buildable anytime via the existing rates-fetcher
  pattern. Detail: target architecture §14.
- [ ] RTX 3090 AI layer (WoL) — LLM summaries, embeddings at scale, RAG.
  Detail: roadmap §7; findings Tier 3 #13.
- [ ] GraphRAG — after entity extraction has produced reliable history.
  Detail: target architecture §8; findings Tier 3 #14.
- [ ] 🤔 Optional depth decisions (no action unless wanted): FMP free tier for
  US fundamentals history; LLM narration hook for reports; Timescale columnstore
  compression on `stock_prices`.

## 5. Recurring (never "done" — calendar items)

- [ ] 🔄 Daily: `/health` checklist (ops manual §7). Automatic: 22 CronJobs.
- [ ] 🔄 Monthly (1st): fdi-watch logs DPIIT links → 5-min manual INSERT.
  Detail: ops manual §11.
- [ ] 🔄 Quarterly: timed restore drill (`restore-drill-job.yaml`), after any
  schema/backup change too. Detail: ops manual §9.
- [ ] 🔄 After ANY TX2 apt work: re-verify iptables wrappers (ops manual §8).
- [ ] 🔄 eMMC >85% alert → prune TX2 docker cruft (ops manual §7 step 7).

## 6. Icebox 🧊 (deliberately declined — revisit triggers noted)

- JetPack 5 reflash (lifts CUDA/cgroup ceilings; recovery-mode, full revalidation)
- Longhorn/OpenEBS · Loki · Argo/Tekton · Citus (pi2 1 GB ceiling — ADR 0008)
- 4th Pi worker · streaming ingestion · public-website/VPS front
  Detail: roadmap §10; findings icebox; ADRs 0008.

---

*When something here completes, record the ✅ here first, then update the
owning doc (schedule tables, gap lists, rollout statuses) in the same session —
this tracker and the docs must never disagree.*
