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
  Retain). Remaining: power-supply fix (next item — gates everything below) → agents pi3→pi1→TX2 (§8 order) → verify
  timescaledb Running → unsuspend in dependency order (fetchers →
  sentiment/ner → ta → screener chain → health) → delete stale Jobs (nse,
  digest) → refire missed runs (nse, fiidii, ~15× intraday, yfinance,
  digest). Detail: ops manual §8 (newest subsection); ADR 0011.
- [ ] 🔶 **Fix the Pi power supplies (PLANNED — owner is replacing them; gates the recovery above)**
  - **Evidence (2026-10-10):** pi2 live undervolt+throttle (`0xd0005`, 62 °C). Phone-style chargers do
    not hold: a 5 V 2 A adapter still gave 9 `Undervoltage detected` events in 5.5 min at near-idle
    load (no thermal cap, load calm, k3s up). pi3 — identical SSD, own supply — stays `0x0`. pi0 shows a
    chronic `0x50000`; pi1 accumulates events (skill `node-power-health`). pi1 was also unreachable at
    ~11:54Z (cause unverified — power suspected, not proven). Supplies fail as a class.
  - **Buy/do:** 5.1 V / 3 A supplies (known-good class) + short (≤ 0.5 m), thick (≥ 20 AWG) micro-USB
    cables for **pi2 first, then pi1, then pi0**; pi3 keeps its clean supply; keep **one spare**
    supply+cable set for swap tests. For pi2 power the SSD **separately from the Pi's 5 V rail** (the SSD is the BOOT
    drive, so keep its data path direct): a powered SSD enclosure, or a separate-power Y-cable /
    data-only adapter. A hub in the boot path is **unverified on Pi 3 / 3B+** — test on pi3 or a spare
    first, never first on pi2; bring SSD and Pi up together (rootdelay already covers slow drives). Optional: an inline USB power meter (~$10).
  - **Method:** the identity-free swap-test ladder (skill `node-power-health` §4): PSU+cable first,
    then USB-SATA adapter, board last. **Never swap boot SSDs between nodes** (hostname, static IP, k3s
    certs and cluster state travel with the disk).
  - **Acceptance:** no live `0x1` and no new `Undervoltage detected` in `dmesg` while load is real (k3s
    settled, jobs running), **24 h of clean `throttle_hex` in `stats.csv`** — an idle reading proves
    nothing. Record the verdict per node here and in the ops manual §8.
  - **Gate:** do not start more agents, unsuspend CronJobs, or refire missed runs while pi2 shows live
    undervolt; the bursts are the wedge trigger.
  - **Later (decision, not part of this fix):** one shared regulated 5 V rail with fused branches —
    architecture review AR-10; needs an enclosed supply and careful mains-side wiring.
  - Detail: `architecture-review-2026-10-10.md` AR-10; skill `node-power-health`; ADR 0011.
- [ ] 🔶 **Protect the existing DB backups while the cluster is down** — the newest dump on pi3
  (`marketdata-2026-10-10.dump`) is **0 bytes** (a failed run); copy the last 2–3 good dumps (~165 MB each) off pi3
  to the workstation (read-only). pi1, the planned second copy, was unreachable ~11:54Z. Detail: review AR-11;
  ops manual §9 (known flaws).
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

- [x] ✅ 2026-10-10 **Telegram v3 live** — `telegram-digest`, new
  `telegram-alerts` (23 CronJobs) and the listener all on
  `local/telegram-digest:v3` (live tags verified); canary
  `telegram-alerts-validate` → `ALERTS-OK 3 line(s) sent`. Detail:
  telegram-bot doc §1a.
- [ ] ⛔ **Apply Telegram v6 — blocked on pi2** (API refused from ~13:50 UTC
  2026-10-10, mid-rollout; no SSH for 6+ min). Image `local/telegram-digest:v6`
  is already imported on pi1 and the manifests carry the tag; live objects are
  still on v5 (working). When the API answers:
  `kubectl apply -f manifests/telegram/cronjob.yaml -f manifests/telegram/deployment.yaml`,
  verify the three live tags, then in-pod check
  `kubectl -n market-data exec deploy/telegram-bot -- python -c "import bot; print(bot.COMMANDS['nifty']('/nifty'))"`
  and bump the manual's tag references v5 → v6.
- [x] ✅ 2026-10-10 **Index long-term reference** (v5): 1/3/5-year averages +
  low/normal/high reading on `/index` `/nifty` `/sensex` `/gold`; index history
  backfilled to 5 years (47,408 rows, no duplicates). Detail: telegram-bot doc
  §1a "v5 / v6". 95 unit tests.
- [ ] 🔶 Index history beyond 5 years needs a fetcher that commits per time range
  (one-transaction backfill hits the lock table) — then 10y+/monthly history for
  a 5-year reading that includes a bear market.
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
- [ ] 🔶 FX history backfill to 1 Jan — `fx_rates` starts 2026-09-30, so `/fx`
  shows no YTD yet (fx-fetcher has no BACKFILL mode today).

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
- [ ] 🔶 **AR-1 (Phase 0)** CronJob safeguards — `concurrencyPolicy: Forbid`, per-job
  `startingDeadlineSeconds`, `activeDeadlineSeconds`, `ttlSecondsAfterFinished` (0 of the
  committed jobs set any today). Edit manifests now; apply only when the cluster is calm.
- [ ] 🔶 **AR-2/AR-3 (Phase 1)** shared job module (DB connect+retry, `write_window()`,
  logging, `main()` wrapper) and a durable `job_runs` table (start/end/rows/status/error).
- [ ] 🔶 **AR-5 (Phase 1→2)** lockfile for every image, then consolidate ~16 images to ~3 by
  dependency profile (ADR candidate; touches ADR 0004).
- [ ] 🔶 **AR-6/AR-7 (Phase 2)** repo layout (`src/ images/ deploy/ db/`) + kustomize base so
  safeguards live in one place; parity-checked, no rebuild for pure moves.
- [ ] 🔶 **AR-8 (Phase 1→2)** read-only DB roles for Grafana/bot, writer role for jobs;
  fixture tests for pure job logic (`tests/test_stocks.py` is the model).
- [ ] 🔶 **AR-9 (Phase 2)** GitHub Actions CI (drift check, tests, lint, gitleaks) and a
  branch/worktree per session so WIP is never committed by the wrong session.
- [ ] 🔶 **AR-4 (Phase 3)** DB `Guaranteed` QoS + readiness probe, bot liveness (StatefulSet
  change restarts the single DB — quiet window only).
- [ ] 🤔 **AR-10 (Phase 3, decisions/hardware)** control-plane `state.db` backup, stronger
  control-plane host, DB-host/GPU-host separation, off-site backups, schedule timezone
  (decide before 2026-11-01, ADR 0002 revisit).
- [ ] 🔶 **AR-11 (Phase 0)** fix `pg-backup` — dump to temp name, verify (size floor + `pg_restore -l`), atomic
  `mv`, prune only verified, keep ≥ 7 verified; second-node + off-site copy; > 36 h staleness alert; re-run the
  restore drill on a ~165 MB dump (docs' 388 KB / 2 s figures are stale). Manifest-only; apply when calm.
- [ ] 🔶 **AR-12 (Phase 1)** repair/verify the 5-min stats logger (one sample on pi0/pi1/pi3; no cron entry seen
  on pi0) — the power fix's 24 h acceptance depends on it; install `nodewatch` on pi0; decide the watcher /
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
  **Status 2026-10-10: interim fix coded in the repo, NOT built or deployed.** `stock_screener.py`
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
  **Status 2026-10-10: coded in the repo, NOT built or deployed.** `failed` now initialised and counted (also printed in
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

- [ ] 🔄 Daily: `/health` checklist (ops manual §7). Automatic: 22 CronJobs.
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
