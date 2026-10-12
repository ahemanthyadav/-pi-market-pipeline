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

- [x] ✅ 2026-10-11 **Node jobs/responsibilities documented** in `node-roles.md` (all Pis + TX2; pinned vs unpinned
  CronJobs, host cron jobs, blast radius). Live check that day: pi1 **Ready** (telegram-bot Running there), pi2 Ready but
  **cordoned** (undocumented — find out when/why), all 23 CronJobs still suspended.
- [x] ✅ **2026-10-12 Telegram v7 deployed** (DQ-2 fix for `/stock` and the digest tables: flow metrics read full-year yfinance rows, not EDGAR year-to-date
  10-Q rows). Built on the TX2 (code verified identical to the repo, per-file sha256), tarball checksummed at each hop, imported on pi1 (the only node
  that runs it; 2 undervolt events, node stayed Ready), tags bumped on the Deployment + both CronJobs (live diff = exactly 3 image lines), bot rolled
  out cleanly and is listening; `/stock MSFT` renders the full card in the new pod (no message sent — called inside the pod). 96-test suite passes.
  Observed in the old pod's log: a chat that is not on the allow-list messaged the bot (`/status`) and was ignored — the allow-list is working;
  worth knowing who that was.
- [x] ✅ **2026-10-12 Screener v9 rolled out (DQ-2 + DQ-3 fixes).** Image content verified byte-identical to the repo scripts (sha256 per
  file), tarball (checksummed at each hop) imported on pi1 (v9 was already on pi3; 3 undervolt events during the import, node stayed
  Ready), all six screener CronJobs bumped v8 → v9 (live diff = exactly 6 image lines), canaries run **on pi1 itself**:
  `stock-screener` → `SCREENER-OK scored=994 eligible=885 shortlisted=50`; `stock-report` → `REPORT-OK reports=50 digest=yes`; no duplicate
  score rows. **Top-50 diff** (`out/v9/top50-{before-v8,after-v9}.csv`, gitignored): Nifty 500 50/50 identical (its fundamentals were already
  full-year yfinance rows → no change); **S&P 500 only 25/50 overlap** (top-10 moved from MU/SNDK/APA/PTC/NEM/HPQ/WDC/EOG/DVN/TRV to
  INCY/ALL/SNDK/NEM/TRV/MU/APA/PTC/PGR/PM; mean growth_score −0.06 on the overlap) — the intended effect of no longer comparing year-to-date
  figures with full years. `stock_fundamentals` DQ-3 (NameError) is unit-tested only; **its first real validation is the Sat 2026-10-17
  06:00 PDT full pass** (watch for `FUNDAMENTALS-OK` with a `failed=` count and a Completed Job). US price data currently ends 10-08 (the
  10-10 `stock-prices` run failed during the outage; its 5-day window recovers tonight). Previously: History of the 2026-10-10 second wedge:** Sequence: v9 built on
  TX2 and imported on pi3 (63 s), then pi1's tarball push/import → API `ServiceUnavailable`, pi1 `ctr` EOF; pi1/pi2 SSH
  banner resets with ping alive, pi3 off the network; pi2 + pi3 later came back (~17:41 UTC, "up 0 min"); **pi1 still
  NotReady with no ping at 17:50 UTC — needs a physical power check.** Cause unproven (a 116 MB push + import on
  Pis with a known PSU fault is the prime suspect — avoid bulk transfers until the power fix is accepted).
  At 17:44 UTC **all 23 CronJobs were suspended** (all 23 were active before; list in
  `/tmp/opencode/cronjob-suspend-before.txt`) — un-suspend **staggered**, not all at once, once pi2 load < 2 and
  pi1 is back. Live CronJobs referenced `screener:v8` until 2026-10-12; `screener:v9` exists only in TX2 docker, pi3's containerd and
  tarballs (TX2 `/home/ahytx2/screener-v9.tar.gz`, workstation `/tmp/opencode/`, and a leftover copy in `/home/pi1/`).
  Resume the v9 rollout (DQ-2/DQ-3 fixes) only after: 4 nodes Ready, pi2 calm, power fix accepted.
  **Update 2026-10-11 ~23:45 UTC (autonomous work session):**
  - ✅ **`pg-backup` fix (AR-11) applied and canary-proven** — `tests/test-pg-backup.sh` 21/21; live canary
    `BACKUP-OK marketdata-2026-10-11.dump size=171611578 entries=14935`, atomic rename + `.sha256`, the 0-byte
    10-10 dump and the 393 KB 10-03 dump pruned. Fresh dump copied to `out/backups/` (sha256 matches). CronJob stays
    **suspended** (applied manifest kept `suspend=true`).
  - ✅ 15 stale failed Jobs from the first outage deleted.
  - 🔴 **pi3 dropped off the network again (~23:42 UTC, no ping, NotReady)** minutes after the backup canary (pg_dump
    writing ~164 MB to its SSD) plus a 165 MB read — same trigger pattern as the pi1-push wedge. **Power is NOT
    fixed**; pi1/pi2/pi3 are still on the shared 105 W block. pi1, pi2, TX2, pi0 are up; DB, Telegram bot (pi1) up;
    Grafana (pinned pi3) and pg-backup (pinned pi3) unavailable until pi3 returns. Needs a physical check/power cycle.
  - Staged un-suspend **started and rolled back**: `yfinance-fetcher` un-suspended once, its catch-up pod hit
    `ErrImageNeverPull` on pi1 (see next), then re-suspended. **All 23 CronJobs are suspended again.**
  - 🔶 **Image gap on pi1:** `yfinance-fetcher:v5` and `nse-fetcher:v4` exist on pi3 but NOT on pi1 (unpinned jobs that
    schedule on pi1 fail with `ErrImageNeverPull`). Fix = import both on pi1 (or pin to pi3) **before un-suspending**;
    avoid bulk pushes until the power fix. `screener:v9` is on pi3 only.
  - ✅ (repo only, **not deployed**) Telegram `stocks.py` `series()` now uses full-year yfinance rows for flow metrics
    (same DQ-2 flaw as the screener); new test, 96/96 pass. **Deployed 2026-10-12 as `telegram-digest:v7`** (see the v7 item in §1).
  - Order when pi3 is back and power is fixed: import missing images (pi1) → un-suspend in stages (fetchers → ner/
    sentiment → ta → screener chain) with `dmesg`/load checks → `screener:v9` import on pi1 + apply + canary + top-50 diff.

- [x] ✅ 2026-10-12 **2026-10-09→10 outage recovery — complete except power acceptance:** all 4 nodes Ready, DB Running, all 23 CronJobs
  un-suspended (staggered), missed runs refired (fiidii, rbi, news, sentiment, ner, universe-refresh, health) — details in the 10-12 entry
  below. The root cause (undervoltage) is only *claimed* fixed until the 24 h acceptance in the power item passes.
- [x] ✅ 2026-10-12 **Telegram v6 running** — bot pod Running on pi1 (`local/telegram-digest:v6`), `COMMANDS['nifty']('/nifty')` returns the
  card (22,531.65, "12 Oct close"), `telegram-digest` ran in-window and sent. 🔶 The "12 Oct close" is likely a live intraday bar from the
  04:00 UTC yfinance canary; the `nse-fetcher` run at 11:15 PDT overwrites it (DELETE+INSERT) — spot-check tomorrow.
- [x] ✅ 2026-10-12 **News feeds repaired** — diagnosed: Moneycontrol (both feeds) 302-redirect to a login-consent wall for every user-agent, Reuters
  (`feeds.reuters.com`) no longer resolves. Fixed with a `FEEDS` env override in `manifests/ingestion/news/cronjob.yaml` (no image rebuild): kept
  ET + Business Standard, added LiveMint, Hindu BusinessLine (India) and CNBC, MarketWatch (global). Canary: 6/6 feeds parse, 160 headlines, 127 new
- [x] ✅ **2026-10-12 Telegram multi-user — every user has their own setup (ADR 0012, `telegram-digest:v8`).** Owner = the Secret's chat id; members =
  `bot_users` rows, managed from the owner's chat with `/adduser <id> Name`, `/rmuser <id>`, `/users` (no Secret edit, no restart). `watchlist` is now keyed
  `(chat_id, symbol)` — each person's holdings, `/watch`, digest watchlist section and watchlist alerts are private to their chat; digest and alert Jobs fan
  out one message per user (a member who blocked the bot only logs a WARN). An unknown chat is still never answered, but the owner gets one access notice
  per chat per day with a ready `/adduser` line. Schema `09-multiuser.sql` applied (watchlist was empty; idempotent; refuses to guess an owner if it has
  rows; tested against a throwaway Postgres in 4 cases). Verified live in the new pod against the real DB with a throwaway member (cleaned up): stranger
  silent + owner notified once + stranger `/adduser` blocked; member `/watch` private; member cannot `/adduser`; removed member gets 0 replies; digest and
  alerts `main()` give each user only their own content. `tests/test_multiuser.py` 38 tests (allow-list and watchlist-scoping mutation-checked); added to CI.
  **The Secret's `chat-id` is the owner's PRIVATE chat again** (restored from `telegram-bot-prev-chat-id`; it had been pointed at a group, which made the whole
  group the owner). 🔶 Still to do by the owner: have each person message `@Marketfredbot`, then `/adduser` them from the access notice and ask them to
  `/start`. Open extension: per-user digest time and alert threshold. Side notes: the schema Job could not be re-run under its own name (delete guard on
  `timescaledb…`) — ran as `schema-multiuser-09`; `timescaledb-schema-09` (broken first attempt, suspended) and `telegram-bot-prev-chat-id` (rollback copy of the
  old owner id) remain in the namespace.
  rows. Note the source mix changed (affects sentiment comparability across the 10-12 boundary). The script's `DEFAULT_FEEDS` still lists the dead feeds
  — update it at the next natural rebuild.
- [x] ✅ 2026-10-12 **Import the new fetcher images on pi1** — `yfinance-fetcher-v5` and `nse-fetcher-v4` imported, canaried on pi1, CronJobs
  active. Side effect: pi1 logged undervolt events during both transfers (power item in §1).
- [x] ✅ 2026-10-10 **Index long-term reference** (v5): 1/3/5-year averages +
  low/normal/high reading on `/index` `/nifty` `/sensex` `/gold`; index history
  backfilled to 5 years (47,408 rows, no duplicates). Detail: telegram-bot doc
  §1a "v5 / v6". 95 unit tests.
- [x] ✅ 2026-10-10 **Index history back to 1985** (292,387 rows, 38 tickers,
  no duplicates, 299 chunks). Fetchers commit one calendar year per
  transaction (`yfinance-fetcher:v5`, `nse-fetcher:v4`, canaried on the live
  CronJob spec); `index_prices` creates one-year chunks from now on (approved,
  recorded in `01-schema.sql`). Jobs `backfill-yfinance-deep` (250,309 rows,
  3.5 min) and `backfill-nse-deep` (42,078 rows, 53 s). Cards verified against
  the live DB. `tests/test_index_fetchers.py` (4 tests).
- [ ] 🔶 `NIFTYMIDCAP150.NS` has only 2019 → today on Yahoo, so its reading
  rests on two years of comparisons; a longer series needs NSE's own archive.
- [ ] 🔶 pi2 keeps rebooting under shared-charger power (six+ times on
  2026-10-10, each taking API + cluster DNS + the bot down). Dedicated 5.1 V
  supply for pi2 is the fix; nothing in software will hold until then.
- [x] ✅ 2026-10-10 **Telegram v4 live** (same day as v3): table layout,
  `/index`, YTD everywhere, valuation repriced to the latest close,
  `/multibagger`, confidence score on every recommendation. 85 unit tests;
  canary `ALERTS-OK`. Detail: telegram-bot doc §1a "v4".
- [ ] 🔶 Phone check of the v4 commands (`/help`, `/stock TCS`, `/index nikkei`,
  `/world`, `/top growth sp500`, `/multibagger`, `/watch add …`, `/digest`) —
  only log-verified so far; table widths assume ~38 monospace characters.
- [ ] 🤔 Screener value factor uses weekly Yahoo ratio snapshots (P/E, P/B,
  EV/EBITDA, market cap from Saturday's `stock-fundamentals` run), not the
  day's close. Reprice inside `stock_screener.py` the way `/stock` now does?
- [ ] 🤔 Multibagger screen is unbacktested. Possible now for the S&P 500 (EDGAR
  history with filing dates since 2007), not for the Nifty 500 (4 annual points,
  no filing dates). Superseded by the replacement screen in the evidence roadmap §3.
- [x] ✅ 2026-10-10 Schema Job rerun (`08-watchlist.sql` → table `watchlist`;
  `^RUI` in ticker_names). `yfinance-fetcher:v4` live (pi1 + pi3 imports),
  1y backfills run for both index fetchers: `^RUI` 251 rows, `^CRSLDX` (Nifty
  500) 246 rows, no duplicate (ticker, ts). Grafana "Derived Metrics"
  dashboard applied (file present in the pod; not yet checked in the UI).
- [x] ✅ 2026-10-12 **FX history backfill** — 2,050 daily closes (10 pairs × 205 days, 2025-12-15 → 2026-09-29) via a one-shot Job on the
  existing `fx-fetcher:v1` image with the script in a ConfigMap (no rebuild; `manifests/ingestion/fx/fx-backfill.py` + `backfill-job.yaml`).
  Verified: 0 duplicate (pair, ts), all at 00:00 UTC like the live daily rows, and the bot's own YTD query now returns a year-start for all 10
  pairs (e.g. USDINR +6.68 % YTD). First attempt failed on `with conn:` closing the connection (psycopg 3) — fixed with `conn.transaction()`.

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

### Architecture review follow-ups (2026-10-10 — recommendations, none applied)

Full evidence and rationale: `architecture-review-2026-10-10.md`. Order = its §5 phases.
- [ ] 🔶 **AR-1 (Phase 0)** CronJob safeguards — **applied 2026-10-12 02:5x UTC to all 23 CronJobs (since un-suspended — live and protecting them)** (22 applied by
  this session after a `kubectl diff` review showing only the 4 safeguard fields; `pg-backup` was already on the new spec).
  Live values verified (`concurrencyPolicy Forbid`, `startingDeadlineSeconds`, `activeDeadlineSeconds`, TTL 604800); values +
  rationale in ops manual §3. Effect on resume: only runs due inside each job's start window fire — no 23-job catch-up storm.
  Remaining: canary the estimated deadlines (`headline-ner`, `stock-screener`, `stock-report`, Telegram) on their first live runs.
- [ ] 🔶 **AR-2/AR-3 (Phase 1)** shared job module (DB connect+retry, `write_window()`,
  logging, `main()` wrapper) and a durable `job_runs` table (start/end/rows/status/error).
- [ ] 🔶 **AR-5 (Phase 1→2)** ✅ step 1 done 2026-10-12: a `requirements.lock` for every Python image (13 new frozen from the running images + the 3
  existing; only the upstream timescale image has none). Remaining: make the Dockerfiles consume them at the next natural rebuilds, then
  consolidate ~16 images to ~3 by dependency profile (ADR candidate; touches ADR 0004).
- [ ] 🔶 **AR-6/AR-7 (Phase 2)** repo layout (`src/ images/ deploy/ db/`) + kustomize base so
  safeguards live in one place; parity-checked, no rebuild for pure moves.
- [ ] 🔶 **AR-8 (Phase 1→2)** read-only DB roles for Grafana/bot, writer role for jobs;
  fixture tests for pure job logic (`tests/test_stocks.py` is the model).
- [ ] 🔶 **AR-9 (Phase 2)** GitHub Actions CI **written 2026-10-12** (`.github/workflows/ci.yml`: docs/manifest drift check, all unit + shell tests,
  manifest sanity, gitleaks; no secrets; verified step-by-step in a clean venv) — **has not run on GitHub yet (needs a push)**. Remaining: lint, and a
  branch/worktree per session so WIP is never committed by the wrong session.
- [ ] 🔶 **AR-4 (Phase 3)** DB `Guaranteed` QoS + readiness probe, bot liveness (StatefulSet
  change restarts the single DB — quiet window only).
- [ ] 🤔 **AR-10 (Phase 3, decisions/hardware)** control-plane `state.db` backup, stronger
  control-plane host, DB-host/GPU-host separation, off-site backups, schedule timezone
  (decide before 2026-11-01, ADR 0002 revisit).
- [ ] 🔶 **AR-11 (Phase 0)** fix `pg-backup` — **applied + canary-validated 2026-10-11 ~23:40 UTC (not by this session — applied
  by the owner or another session; I only found it)**: live spec carries the new script; pi3 holds `marketdata-2026-10-11.dump`
  (171 MB) + `.sha256` (`sha256sum -c` OK 2026-10-12), the 0-byte 10-10 file and the 10-03 dump are gone. The CronJob is still
  un-suspended 2026-10-12 with the rest. **Restore drill DONE 2026-10-12 (off-cluster, no load on the DB):** the 171 MB 10-11 dump restored into a
  local `timescale/timescaledb:2.30.1-pg16` container in **30 s, 0 errors** (12 hypertables, 3,703 chunks; serial `pg_restore` after
  `timescaledb_pre_restore()` — `-j2` fails on the catalog foreign keys); 12 of 13 tables match the live DB row-for-row (6,340,928 `stock_prices`,
  292,313 `index_prices`, …); the 13th, `universe_constituents` (1001 vs 998), differs by exactly the 3 rows `universe-refresh` added after the dump.
  **Second copy:** `ops-tools/pull-backups.py` pulls the newest verified dump(s) to the workstation, sha256-checked against the sidecar, exit 2 if the
  newest verified dump is > 36 h old (tested: stale path, and a corrupted local copy is detected and re-pulled). Remaining: off-site copy, and an
  in-cluster staleness alert (the Grafana `stale-feed` rule only counts `fresh=false` rows from the health job's own FEEDS, so a self-written row
  cannot go stale — needs a rule change or a health-job rebuild; run `pull-backups.py` from cron meanwhile). `tests/test-pg-backup.sh` 21/21.
- [x] ✅ **AR-12 (Phase 1)** — re-verified 2026-10-12 04:30 UTC: all five hosts logging every 5 min, `nodewatch` cron present on pi0. Repair/verify the 5-min stats logger (one sample on pi0/pi1/pi3; **all five hosts fixed 2026-10-11**: each
  root crontab was empty — entry `*/5 * * * *` added on pi0/pi1/pi2/pi3/TX2 (all logged at 23:10 UTC), so the 24 h
  acceptance record runs from ~23:10 UTC 10-11. Second bug found and fixed the same day: the script wrote its CSV header
  only if the file did not exist, so after each weekly logrotate (empty file left behind) the header was skipped —
  now `-s` (non-empty); header prepended to the four Pi files; rotation case tested on pi0; the script is now in the
  repo as `ops-tools/node-stats-log.sh`. pi2 note: 133 MB available + 77 MB swap in use at 23:07 UTC (watch)) — the power fix's 24 h acceptance depends on it; `nodewatch` on pi0 deployed 2026-10-11 (see §3); decide the watcher /
  power-controller host (pi0 vs MCU vs smart plugs; relays normally-closed; external dead-man's switch).

### Prioritised implementation order (value × effort — `stock-screener-implementation-plan.md` §16)

P0 do first · P1 next · P2 after · P3 later. Ratings are my priors; re-rate after the first EV-0 run.
- [ ] 🔶 **P0 (in order):** **G-1/DQ-1** adjusted prices + corporate actions → **G-2a** weekly membership snapshots, **EV-2**
  keep fundamentals snapshots, **G-3/PV-0** prediction ledger + outcome resolver (parallel; design in `prediction-validation-and-training-2026-10-10.md`) → **EV-0 + ML-0** test harness → **EV-1** historical
  membership. Prerequisite: power + backup fixes (§1, AR-11).
- [ ] 🔶 **P1:** **G-6** India fundamentals source (decision: quarterly filings vs paid API) · **EV-3/4/5/7** price signals under
  EV-0 · **EV-9 → EV-10…13** statement lines + signals · **ML-2** store embeddings now · **PV-1** model-health dashboard + alerts.
- [ ] 🔶 **P2:** **EV-17/18** composite v2 + measured confidence (after EV-0 results) · **EV-14/15/6/8** · **G-9** US insider +
  short interest · **G-10** India promoter pledge/holding · **EV-16** portfolio rules + risk dashboard · **ML-1/3/5/7a** ·
  **G-12** breadth/sector rotation · **G-13** macro series · **G-18** second price source · **PV-2/PV-3** extend the ledger (sentiment, alerts, confidence) + drift monitor · **TP-0/TP-1** training infrastructure (registry, shadow, promotion) + scheduled refits.
- [ ] 🔶 **P3:** **ML-4/6/7b–d** · **G-11** India delivery/bulk/OI · **G-16** filing-text analytics · **G-17** mid/small-cap
  universe · **G-19** 13F holdings · **TP-2** GBM quarterly retrain + gate.

### Data correctness — prerequisite for EV-0 and every ML backtest (found 2026-10-10)

- [ ] 🔶 **P0 · DQ-1 (G-1) corporate actions / adjusted prices.** Verified: `stock_prices` keeps only OHLCV from yfinance with
  `auto_adjust=False` — Yahoo's raw `Close` is split-adjusted but **not dividend-adjusted**, `Adj Close` is dropped, and
  there is no splits/dividends/corporate-actions table. The daily job refreshes only the last 5 days, so a split or
  spin-off *after* a symbol's backfill leaves a discontinuity in its older rows. Evidence it matters: 3 symbols show
  > 40 % single-day moves in the last 60 days (CTVA −84 % on 2026-10-01, HEGAM.NS −63 % on 2026-09-06, MRNA +177 % on
  2026-08-19 — causes **not verified**: spin-off, bonus/demerger or bad bars). Returns, momentum and volatility are
  wrong across such events. Fix (additive): `adj_close` column + `corporate_actions` table; re-backfill a symbol when an
  action is detected; flag > 40 % moves (ML-1); then run EV-0 on adjusted series. Total-return (dividend) effects are
  currently omitted from every return metric.
- [ ] 🔶 **P0 · DQ-2 fundamentals period + point-in-time errors** (verified 2026-10-10, live DB; design + DDL in
  `data-foundations-schema-draft-2026-10-10.md`). (a) `edgar_facts()` ignores period length, so quarterly rows hold
  year-to-date values (MSFT net income 27.75 → 66.21 → 97.98 → 133.75 bn across Sep/Dec/Mar/Jun) and
  `annual_series()` can compare 12-month with 6-month figures for non-December fiscal years; (b) `filing_published_at`
  is the *latest* re-filing (MSFT FY2024 shows 2026-07-29), so history is not point-in-time. Plan: new append-only
  `financial_facts` table keyed by duration + first-filing date. Measure the effect on live scores (non-December-FY
  companies) before switching readers. Blocks EV-0 on fundamentals and EV-9…EV-15.
  **Measured 2026-10-10** (emulating `annual_series`, 477 S&P symbols with EDGAR revenue): median "3-year revenue
  CAGR" = **−17.8 %** vs like-for-like YoY **+8.8 %**; 400 of 477 understated by > 10 pp, 351 sign-flipped, because the
  newest entry per calendar year is a half-year YTD figure compared with a full year. `growth_score` (20 % of the
  composite), EPS growth and `fcf_yield` are affected; percentile ranking hides part of it for companies at the same
  point in their reporting cycle, but it distorts ranks between companies at different points. Fix before trusting any
  growth/FCF ranking, not only before EV-0.
  **Status 2026-10-12: interim fix DEPLOYED in `screener:v9` (canaried on pi1; S&P 500 top-50 overlap 25/50 — see §1).** (2026-10-10: coded) `stock_screener.py`
  (`annual_series`, `latest_fundamentals`) and `stock_report.py` now read flow metrics (revenue, net income, operating
  income, EPS, FCF) from full-year yfinance rows only — on live data the median 3-y revenue CAGR becomes +8.5 % (was
  −17.8 %), no symbol loses coverage (every EDGAR symbol also has yfinance rows). Cost: US flow figures are the last
  fiscal year, up to ~12 months old, until `financial_facts` gives true TTM. Tests: `tests/test_stock_fundamentals_fixes.py`.
  Remaining: `/rebuild` as `screener:v9` → canary `stock-screener` → diff top-50 before/after → note in digest.
  **Same flaw, not fixed:** Telegram `stocks.py` `series()` (picks the newest-`ts` source, i.e. EDGAR YTD for US) — own image.
- [ ] 🔶 **P0 · DQ-3 weekly fundamentals job is effectively every-other-week + resets first-seen dates.**
  `stock_fundamentals.py:228` uses undefined `failed`. Evidence it is live in v8: the 2026-10-04 full pass left the
  cursor un-cleared (last update 10:39:13 UTC, the last symbol's write); the 2026-10-10 13:00 UTC run logged only
  "pass already complete — cursor cleared" and finished in 20 s with **no data refreshed** (`pe` still one `ts`,
  2026-10-04). The cursor is now NULL, so **2026-10-17 06:00 PDT does a full pass, then hits the NameError again**
  (Job fails after writing everything; the week after is another no-op). Also each full pass resets yfinance statement
  rows' `filing_published_at` to the fetch date (EV-2). Image v8 not inspected (not in TX2 Docker; repo file is the
  best evidence). Fix in the next image, `/rebuild`; if v9 won't land before 10-17, accept the one failing Job.
  **Status 2026-10-12: DEPLOYED in `screener:v9` (see the v9 item in §1); first live proof = the 10-17 weekly run.** (2026-10-10: coded) `failed` now initialised and counted (also printed in
  `FUNDAMENTALS-OK`); `upsert()` keeps the earliest `filing_published_at` (`LEAST`) so re-fetches stop resetting
  first-seen dates. Covered by `tests/test_stock_fundamentals_fixes.py` (7 tests pass).
- [ ] 🔶 **P1 · G-20** factor returns (US Ken French library, India IIM-A library — URLs/terms **not verified**) into
  `factor_returns`; extend EV-0 §5 test 4 to "beyond the standard factors".
- [ ] 🔶 **P2 · G-21** extra signals testable from data on hand: net payout yield (Boudoukh et al. 2007), distress score,
  Amihud illiquidity (2002), max daily return / idiosyncratic volatility (Bali et al. 2011), industry momentum
  (Moskowitz & Grinblatt 1999) — citations from memory, verify; each must pass EV §5.
- [ ] 🔶 **P2 · G-22** 12 of 503 S&P symbols have no EDGAR rows (e.g. AAPL) — check the `cik` gap in
  `universe_constituents`.

### Evidence-based signals (plan 2026-10-10 — `evidence-based-signals-roadmap.md`)

- [ ] 🔶 **EV-0** signal test harness (monthly IC, t-stat, quintile spread, costs)
  — prerequisite for every item below; acceptance test in roadmap §5.
- [ ] 🔶 **EV-2** keep every weekly fundamentals snapshot (stop overwriting) —
  cheap now, unrecoverable later.
- [ ] 🔶 **EV-3/EV-4/EV-5/EV-7** price-only signals, data on hand: 12-1 momentum,
  nearness to 52-week high, beta, index trend flag.
- [ ] 🔶 **EV-9** more statement lines (total assets, gross profit, operating cash
  flow, shares) → **EV-10…EV-14** profitability, investment, accruals, issuance,
  F-score / G-score.
- [ ] 🔶 **EV-17** composite v2: replace the growth factor with profitability +
  investment, equal weights. **EV-18** replace the heuristic confidence score with
  measured IC and hit rate.
- [ ] 🔶 **EV-1** historical index membership (removes survivorship bias);
  **EV-6/EV-8/EV-15/EV-16** risk-scaled and residual momentum, post-earnings
  drift, portfolio rules.

### ML roadmap (plan 2026-10-10 — `ml-roadmap-2026-10-10.md`; reuses EV-0, never bypasses EV §5)

Labels = research backing of the idea (legend in the roadmap): 🟢 research-backed · 🟡 conditional · 🔵 engineering
practice · ⚪ unproven here · ⚠️ citation not verified.

- [ ] 🔶 **ML-0 🟢** experiment infrastructure (`ml_runs`, Parquet export, walk-forward splitter, leakage test, trial
  budget) — shares the EV-0 harness. **ML-1 🔵** anomaly detection (v1 rules: bad bars, feed/row drops, scraper
  breakage; the node wedge signature is ⚪ — one outage) — needs the stats logger repaired (AR-12).
- [ ] 🔶 **ML-2 🔵** news embeddings + story clustering on the TX2 (return benefit ⚪) — **start storing embeddings now**
  (`float4[]`; pgvector not bundled in the DB image — verify). **ML-3 🟢** volatility forecasts (add GJR-GARCH/EGARCH),
  **ML-5 🟡** peer clusters (also test text-based similarity), **ML-4 ⚪** regime model (descriptive only until EV-0
  shows an out-of-sample difference).
- [ ] 🔶 **ML-7 🔵 (LLM via hosted API — decided 2026-10-10; "never in scoring" is 🟢)** ML-7a daily narrative first; provider-agnostic
  adapter, `LLM_API_KEY` only in the gitignored local file + an out-of-band cluster Secret, facts-JSON grounding +
  number verifier, hard $ cap, `llm_calls`/`llm_outputs` tables, deterministic digest as fallback. Needs a new ADR
  (provider, data-retention terms, what may be sent). **ML-7d** `/ask` stays gated.
- [ ] 🔶 **ML-6 🟡** cross-sectional GBM ranker — **hard-gated** on EV-0, EV-1 and composite v2 passing EV §5; weakest
  fit for large caps, expect small/null; a documented "no" is an acceptable outcome. **ML-8 🔵** TX2 stays CPU; DB move (AR-10) frees it for ML.
- [ ] 🤔 **Provide the LLM provider choice and place the key yourself** (`LLM_API_KEY` in the local credentials
  file; cluster Secret created out-of-band — never paste it into chat or a file in git).

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

- [ ] 🔄 Daily: `/health` checklist (ops manual §7). Automatic: 23 CronJobs.
- [ ] 🔄 Monthly (1st): fdi-watch logs DPIIT links → 5-min manual INSERT.
  Detail: ops manual §11.
- [ ] 🔄 Quarterly: timed restore drill (`restore-drill-job.yaml`), after any
  schema/backup change too. Detail: ops manual §9.
- [ ] 🔄 After ANY TX2 apt work: re-verify iptables wrappers (ops manual §8).
- [ ] 🔄 eMMC >85% alert → prune TX2 docker cruft (ops manual §7 step 7).
- [x] ✅ 2026-10-10 TX2 k3s containerd store moved to the SSD (bind mount), eMMC
  copy + 19 stale tarballs deleted: eMMC 84% → 54%. Detail: ops manual §2.
- [x] ✅ 2026-10-10 `local/headline-ner:v3` was missing from the TX2 k3s store
  (`ErrImageNeverPull`); imported from the tarball, the pending job Completed.

## 6. Icebox 🧊 (deliberately declined — revisit triggers noted)

- JetPack 5 reflash (lifts CUDA/cgroup ceilings; recovery-mode, full revalidation)
- Longhorn/OpenEBS · Loki · Argo/Tekton · Citus (pi2 1 GB ceiling — ADR 0008)
- 4th Pi worker · streaming ingestion · public-website/VPS front
  Detail: roadmap §10; findings icebox; ADRs 0008.

---

*When something here completes, record the ✅ here first, then update the
owning doc (schedule tables, gap lists, rollout statuses) in the same session —
this tracker and the docs must never disagree.*
