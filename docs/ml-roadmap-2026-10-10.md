# ML Roadmap — 2026-10-10

> **Status:** plan. Nothing here is built. Items are tracked in `pending-tasks.md` as ML-0…ML-8;
> accepted ones follow the usual build cycle (`pipeline-dev` → `canary-validate` → docs).
> **Scope:** the machine-learning and LLM work that is *not* a ranking signal, plus the shared experiment
> infrastructure. Ranking signals, the measurement harness (EV-0) and the acceptance test live in
> `evidence-based-signals-roadmap.md` (EV-0…EV-18) — this plan **reuses** them and never bypasses them.
> **Decision recorded 2026-10-10:** the LLM layer uses a **hosted LLM API with an API key**, not a local model on
> the RTX 3090. This supersedes the "LLM on the 3090 via Wake-on-LAN" path in roadmap §7 for text generation;
> the 3090 stays available for offline training and heavy batch work.
> **Evidence status of each package is in §9** (what is research-backed, what is engineering practice, what is unproven here).
> Companion docs: `architecture-review-2026-10-10.md` (AR items this depends on), `adr/0007` (sentiment on CPU),
> `adr/0010` (gazetteer-first entities), skills `ml-experiment`, `migration`, `canary-validate`.

## Label legend — how well each idea is backed by research

| Label | Meaning |
|---|---|
| 🟢 **Research-backed** | Peer-reviewed evidence for this *kind* of method on financial data; I opened the source in this session (see §9) |
| 🟡 **Conditional** | Evidence exists, but its conditions (universe, size, costs, method) differ from this project, so transfer is doubtful |
| 🔵 **Engineering practice** | A standard method chosen for reliability or usability; no finance-return claim is made. Judged only by this project's own tests |
| ⚪ **Unproven here** | No evidence of benefit for this use. Experimental; judge strictly by own measurements |
| ⚠️ | A citation I have **not** verified this session (cited from memory) — check before relying on it |

A label describes the backing of the *idea*, never a promise that it will work on this database. Every gate in §3 still
re-tests it here, and nothing reaches the composite without the EV roadmap §5 acceptance test.

## 1. Principles (apply to every work package)

1. **Boring first, measure before adding.** Rules and statistics before models; a model only replaces a rule if it
   beats it out of sample on this database.
2. **No ML return forecast reaches the composite** unless it passes the EV roadmap §5 acceptance test (t > 3, stable
   across halves and universes, positive after costs, incremental to the existing factors). Negative results are
   recorded, not retried.
3. **Time-based splits only, point-in-time inputs, baselines always** (`ml-experiment` skill). Fundamentals are used
   as of `filing_published_at`; Yahoo's partial pre-open bars are excluded from features.
4. **Survivorship is disclosed.** Both universes are *today's* constituents until EV-1 lands; backtests rank ideas
   against each other, they do not estimate achievable return.
5. **ML is an artifact, not a service.** Train offline on the workstation; ship a small versioned model file; score in
   a normal CronJob that follows the house pattern (idempotent DELETE+INSERT, `job_runs`/heartbeat).
6. **Optional enrichment never sits on the critical path.** If an ML or LLM step fails, the deterministic output
   (digest, report, score) is still produced.
7. **Research aid, not investment advice.** Labelled as such wherever outputs are shown.

## 2. What exists (measured 2026-10-10, read-only SELECTs)

| Data | Size and depth | ML implication |
|---|---|---|
| `stock_prices` | 6.34 M rows, 997 symbols, back to 1962 for some (EV roadmap: 465/503 S&P and 321/494 Nifty symbols have 10+ years) | Strongest asset: return, volatility, regime and anomaly work |
| ⚠️ **Price adjustment (DQ-1)** | Stored `close` is split-adjusted but not dividend-adjusted; no corporate-actions table; 3 symbols with > 40 % one-day moves in 60 days | Fix before any backtest or model — returns are wrong across splits/spin-offs and omit dividends |
| `stock_fundamentals` | 211 k rows, 13 metrics, 2006→; US has filing dates, India does not | PIT features for the S&P 500 only |
| `stock_metrics_daily`, `stock_scores` | 9 days (since 2026-10-01) | Derived history must be **rebuilt from prices** (EV-0 harness) |
| `index_prices` | 38 tickers, 1 year | Short; a longer proxy needs a backfill |
| News: `raw_headlines`, `news_sentiment` | 563 headlines, 2 sources, ~10 days; 324 entity links, 163 events | Too small to train on; **start storing features now** |
| FX, yields, flows, intraday | days–weeks | Too short to model |

**Compute today:** TX2 runs one model (FinBERT, CPU, `torch 2.14+cpu`, ≤ 1000 headlines/night, GPU idle by design —
ADR 0007). Pis have 905 MB each (≈ 150–700 MB free). Workstation (RTX 3090) is not always on.

## 3. Work packages

Effort: S = under a day · M = a few days · L = a week or more (estimates).

### ML-0 — Experiment infrastructure (shared with EV-0)
**Backing: 🟢 Research-backed** — Bailey, Borwein, López de Prado & Zhu (backtest overfitting; Deflated Sharpe Ratio), verified.
- **Goal:** reproducible experiments with one place to look.
- **Build:** `ml_runs` table (run id, name, git SHA, params, data window + data hash, seed, metrics JSON, artifact
  path/hash, started/ended); a Parquet/DuckDB export for the workstation; a walk-forward splitter with purge/embargo;
  an automated **leakage test** (shift check; PIT filter check); a baseline registry (current composite, equal weight).
  Reuse the EV-0 harness for IC / quintile / cost reporting rather than writing a second one.
- **Where:** workstation + one DB table. **Effort:** M. **Depends on:** EV-0 (harness), `migration` skill.
- **Trial budget (verified, §9):** Bailey, Borwein, López de Prado & Zhu show that with 5 years of data no more than about
  45 independent configurations should be tried before a high in-sample Sharpe is expected by chance; count every trial in
  `ml_runs`, compute the Deflated Sharpe Ratio / Probability of Backtest Overfitting, and cap the search accordingly.
- **Acceptance:** any past run is reproducible from `ml_runs` alone; leakage test fails on a deliberately leaky feature.

### ML-1 — Anomaly detection for data quality and node health
**Backing: 🔵 Engineering practice** — robust statistics ⚠️ (MAD / isolation forest, unverified). The node "wedge signature" part is **⚪ Unproven** — it rests on one outage.
- **Goal:** catch bad data and pre-outage behaviour automatically.
- **v1 (rules + robust statistics, no model):** per-symbol return and volume spikes vs the symbol's own history (MAD
  z-score); partial/zero-volume bars; per-feed row-count and freshness drops; extraction-count drops for scrapers;
  node features from `stats.csv` (free RAM, load, swap, throttle bits, temp) — the wedge signature (free RAM low and
  load climbing) as an early warning. **v2 only if v1 is too noisy:** isolation forest or ARIMA residuals.
- **Output:** `data_anomalies` (kind, subject, ts, score, details) + a Telegram alert for severe items.
- **Where:** Pi CronJob after the 01:45 heartbeat. **Effort:** S–M. **Depends on:** the stats logger repaired (AR-12),
  `job_runs` (AR-3) for run records.
- **Acceptance:** a replay over history flags the known partial-bar days and the 2026-10-09 wedge; ≤ 1 false alert per
  week in steady state; fixture tests cover each rule.

### ML-2 — News embeddings and story clustering
**Backing: 🔵 Engineering practice** for de-duplication and clustering (standard sentence-embedding methods ⚠️). Any benefit to returns is **⚪ Unproven**; the news sample is ~10 days.
- **Goal:** de-duplicate headlines and group them into stories/event timelines (roadmap Tier 2 #10).
- **Build:** a small sentence-embedding model (e.g. MiniLM class, CPU) embeds each new headline; store vectors in
  `headline_embeddings` as `float4[]` (the TimescaleDB image in use does not bundle pgvector — verify before assuming);
  similarity in Python at this scale. Near-duplicate and story clusters per day; event timeline later.
- **Where:** TX2 CPU, after the 00:15 sentiment job (its 4 Gi window) — model baked into a TX2-only image; Pis never
  load it. **Effort:** M. **Depends on:** AR-5 image profiles (a TX2-only image is fine meanwhile).
- **Start now (cheap):** store embeddings even before using them; value grows with history.
- **Acceptance:** 100 sampled clusters hand-checked, ≥ 90 % coherent; dedup never merges distinct stories in the sample.

### ML-3 — Volatility forecasts
**Backing: 🟢 Research-backed** — Hansen & Lunde (2005), verified; applies to *forecast accuracy*, not to returns.
- **Goal:** better risk inputs for EV-5 (low risk) and EV-6 (risk-scaled momentum).
- **Build:** baselines EWMA and GARCH(1,1), plus **leverage-effect models (GJR-GARCH / EGARCH) for equities** — Hansen & Lunde
  (2005, verified §9) found GARCH(1,1) hard to beat for exchange rates but clearly inferior for a stock (IBM) where
  leverage-effect models won; compare with 30-day realised vol and a naive forecast (QLIKE / MAE). **Where:** Pi CPU nightly or workstation. **Effort:** S–M.
- **Gate:** keep a forecast only if it beats the naive baseline out of sample.

### ML-4 — Market-regime model (descriptive first)
**Backing: ⚪ Unproven here** — regime-switching literature exists but out-of-sample usefulness is mixed ⚠️ (Hamilton, Ang & Bekaert unverified). The index trend filter is cited in the EV roadmap (Moskowitz et al. ⚠️, unverified).
- **Goal:** a regime label for the digest and dashboards.
- **Step 1 (no ML):** EV-7 index trend filter. **Step 2:** Gaussian mixture / HMM on index return, 20-day vol, VIX /
  India VIX, yield-curve slope; 2–3 regimes. Needs a longer index history: build an equal-weight proxy from the stock
  universe (survivorship caveat) or backfill index history.
- **Gate:** shown as *description only*; it may influence anything else only if the EV-0 harness shows factor returns
  differ by regime **out of sample**. **Effort:** M.

### ML-5 — Peer clusters for sector-relative scoring
**Backing: 🟡 Conditional** — Hoberg & Phillips (2016) back *text-based* industries (verified); return-correlation clustering is standard practice but not the researched method ⚠️.
- **Goal:** inputs for the planned sector-relative ranking (target architecture §5–§6).
- **Build:** cluster by return correlation + fundamentals; compare with the official sector in
  `universe_constituents`; use where official sectors are coarse. **Researched alternative for US names:** text-based
  similarity from 10-K product descriptions (Hoberg & Phillips 2016, verified §9) — test it against the correlation clusters. **Where:** workstation → table. **Effort:** S–M.

### ML-6 — Cross-sectional return ranker (hard-gated, likely a negative result)
**Backing: 🟡 Conditional** — Gu, Kelly & Xiu (2020) and Avramov, Cheng & Metzker (2023), both verified: real gains in a broad US cross-section, concentrated in hard-to-arbitrage stocks and reduced by costs. This project's large-cap universe is the weakest fit.
- **Entry conditions (all):** EV-0 harness live; EV-1 (historical membership) landed or the bias explicitly bounded;
  composite v2 (EV-17) exists to beat.
- **Method:** gradient boosting on the *factor z-scores* (not raw prices), monthly walk-forward on an expanding
  window with purge/embargo; final 2 years held out untouched until the end; every variant tried is counted
  (multiple-testing log).
- **Expectation (verified, §9):** the published gains (Gu, Kelly & Xiu 2020) come from a very broad cross-section with 900+
  predictors, favour *shallow* trees/networks, and are concentrated in hard-to-arbitrage stocks and shrink under realistic
  costs (Avramov, Cheng & Metzker 2023). Your ~1,000 large/liquid names are where those gains are weakest — plan for a
  small or null result, use few-leaf boosting, and report results excluding the smallest/illiquid names and after costs.
- **Acceptance:** EV roadmap §5 in full, **incremental** to composite v2. Otherwise record "no" and stop.
- **Where:** train on the workstation; score nightly on a Pi with a few-MB model file (verify arm64 wheels, fall
  back to scikit-learn). **Effort:** L. **Expectation:** modest; the value is the documented answer.

### ML-7 — LLM layer via hosted API (optional enrichment)

> 2026-10-18 (ADR 0022): hosted API only — the RTX 3090 / Strata is out; one OpenAI-compatible endpoint configured by env;
> no agent framework (plain jobs; a small tool loop for ML-7d).
**Backing: 🔵 Engineering practice / product judgement** — no research claim that narration improves decisions. The rule **"the LLM never feeds scoring" is 🟢 research-backed** (Glasserman & Lin 2024, verified). Grounding and the number verifier are engineering controls.
**Decision (2026-10-10): use an LLM API with an API key.** No GPU, no Wake-on-LAN; any Pi can run the job.

| Package | What | Notes |
|---|---|---|
| **ML-7a** 🔵 | Daily market narrative (150–250 words) added to the digest | Input is a **facts JSON** built from the DB: index moves, VIX, FII/DII, movers, sentiment aggregates, shortlist changes |
| **ML-7b** 🔵 | Per-symbol narration for the shortlist (~50 names) | Input is the deterministic report + recent headlines; skip unchanged symbols (content-hash cache) |
| **ML-7c** 🔵 | Story summaries from ML-2 clusters | After ML-2 |
| **ML-7d** 🔵 | Interactive `/ask` in the Telegram bot (**gated**) | Fixed, allow-listed query tools on a read-only role with statement timeout and row limits — **no free-form SQL**; allow-listed chat only |

**Design rules**
- **Key handling:** `LLM_API_KEY` (and `LLM_PROVIDER`, `LLM_MODEL`) live only in the gitignored local credentials file
  and a cluster Secret created out-of-band (`kubectl create secret … --from-literal`, never a manifest) — the same
  rule as the Telegram token (ADR 0009). `.secrets.env.example` carries the placeholder; the pre-commit guard blocks
  the value. Agents never read the real file; use `@@LLM_API_KEY@@` only in commands that *consume* it.
- **Provider-agnostic adapter:** one `LLMClient.generate(messages, max_tokens, temperature=0)` interface; switching or
  adding a fallback provider is a config change. Selection criteria: price, **data-retention / no-training terms on the
  API tier**, structured-output support, rate limits, payment availability, latency. *(Prices and terms were not checked
  for this plan — verify before choosing.)*
- **What may be sent:** public market data, public headlines, ticker symbols, your own aggregated reports. **Never:**
  credentials, IP addresses, hostnames, personal data, DB dumps. A **prompt linter test** fails the build if a prompt
  contains secret-shaped strings or addresses.
- **Untrusted text:** scraped headlines can contain instructions (prompt injection). Treat them as quoted data,
  delimit them, give the model **no tools and no write access** (output is text stored in one table), and validate output.
- **Hallucination guard:** every number and ticker in generated text must match the facts JSON (automated check); on
  mismatch the output is rejected and the deterministic digest is sent. Generated text is labelled *AI-generated* and the
  deterministic report remains the source of truth. The LLM is **never** an input to scoring.
- **Cost controls:** per-run `max_tokens`, a daily token budget and a monthly **$ cap enforced in code** from the
  `llm_calls` table, identical-prompt caching, a circuit breaker, an alert at 80 % of cap, and a kill-switch env var.
  At digest scale the spend is expected to be small (estimate — confirm with the provider's pricing).
- **Audit:** `llm_calls` (ts, kind, provider, model, prompt hash, tokens in/out, cost, status, latency) and
  `llm_outputs` (kind, scope, ts, text, facts hash, verified) with unique keys; idempotent per (date, kind).
- **Where:** a CronJob on pi1 shortly after `stock-report` (02:30 PDT), `requests` only, ~256 Mi, 120 s timeout,
  bounded retries, `activeDeadlineSeconds`. Egress is plain HTTPS through the existing DNS path.
- **Tests (no network):** fake client with recorded responses; golden tests for the facts builder; the verifier;
  the prompt linter; budget enforcement.
- **Acceptance:** 0 unverified numbers across 30 consecutive outputs (automated) plus a weekly human spot check of
  10; stays under the cap; an API outage still yields the normal digest; no secret/address in any prompt; p95
  latency < 60 s.
- **Effort:** ML-7a S–M, 7b M, 7c M, 7d L. **Depends on:** the secret provisioned, `llm_*` tables, `job_runs` (AR-3)
  preferred, AR-1 safeguards on the CronJob.

### ML-8 — TX2 role
**Backing: 🔵 Engineering decision** (ADR 0007); no research involved.
Keep CPU sentiment (ADR 0007) and add ML-2 embeddings there. No GPU work until a measured benefit exists; a TensorRT
or ONNX path and a JetPack 5 reflash stay in the icebox. When the database moves off the TX2 (AR-10) it becomes a
clean ML/edge worker.

### ML-9 — Prediction validation and training pipeline (cross-cutting)
**Backing: 🔵 Engineering practice** for the plumbing; the evaluation method is **🟢** (Bailey et al., verified, §9).
- **Goal:** every daily output that makes a claim is logged write-once, resolved against outcomes on adjusted prices, scored
  against a baseline and monitored; every component that learns is retrained offline, gated, shadowed, then promoted.
- **Full design:** `prediction-validation-and-training-2026-10-10.md` (inventory of what is predicted today, schema, daily jobs,
  per-kind validation rules, training lifecycle, acceptance tests). Items PV-0…PV-3 and TP-0…TP-2.
- **Depends on:** **G-1 / DQ-1** (correct returns), ML-0 (experiment log, splitter), AR-2/AR-3 (shared module, `job_runs`).
- **Effort:** PV-0 M · PV-1 S · PV-2/PV-3/TP-0 M · TP-2 L.

## 4. Phasing

| Phase | Work | Gate |
|---|---|---|
| **A — now** | ML-0 🟢 (with EV-0), ML-1 v1 🔵, start storing embeddings (ML-2 storage 🔵), provision the LLM secret + `llm_*` tables, ML-7a 🔵 behind a flag, **ML-9 / PV-0 prediction ledger right after G-1** 🔵 | Power fix and backups done first; cluster stable |
| **B — weeks** | ML-1 tuning 🔵, ML-2 clustering 🔵, ML-3 🟢, ML-5 🟡, ML-4 descriptive ⚪, ML-7b 🔵 | ML-0 live; EV Phase 1 results in |
| **C — after EV Phases 1–2 and EV-1** | ML-6 🟡 (hard-gated) | EV §5 acceptance |
| **D — optional** | ML-7c/7d 🔵, ML-8 🔵 refinements | ML-2 history exists; ADR for `/ask` boundaries |

## 5. Data and deployment pattern

- **New tables** (additive; natural keys + unique indexes per house convention; `migration` skill, backup first):
  `ml_runs`, `data_anomalies`, `headline_embeddings`, `vol_forecasts`, `regime_labels`, `peer_clusters`,
  `model_scores` (symbol, ts, model_version, score), `llm_calls`, `llm_outputs`.
- **Images:** an `ml-light` profile (numpy, pandas, scikit-learn, and a boosting library if arm64 wheels exist — no
  torch) for Pi scoring; the existing TX2 image profile for embeddings; the LLM job uses the light profile.
- **Artifacts:** small model files outside git (pi1 SSD or the future backup host), hash recorded in `ml_runs`;
  never baked silently into an image under an existing tag (tag discipline).
- **Operations:** every job writes `job_runs`/heartbeat, has AR-1 safeguards, a canary run, and an alert path.

## 6. Risks

| Risk | Mitigation |
|---|---|
| Overfitting / data snooping | Baselines, walk-forward, held-out final window, multiple-testing log, EV §5 gate |
| Survivorship and look-ahead bias | EV-1; PIT fundamentals; leakage test; disclose limits |
| LLM hallucination | Facts-JSON grounding, automated number check, labelled output, deterministic fallback |
| Prompt injection via scraped text | Delimited untrusted data, no tools/write access, output validation |
| Data leakage to a third party | Allow-list of what may be sent, prompt linter, provider terms checked |
| Cost creep or provider outage | Hard $ cap in code, circuit breaker, optional fallback provider, digest unaffected |
| Added load on a fragile cluster | Schedule off peak, AR-1 deadlines, keep ML-2 on the TX2, nothing on pi2 |
| Time spent on low-value models | Phase gates; ML-6 explicitly expects a possible "no" |

## 7. Decisions needed / ADR candidates

1. ML experiment tracking and artifact storage (ML-0).
2. Embeddings storage (`float4[]` vs a pgvector-capable image) (ML-2).
3. **LLM via hosted API: provider, data-retention terms, budget cap, what may be sent** (ML-7) — new ADR.
4. Boundaries of the interactive `/ask` tools (ML-7d) before building it.
5. The standing rule that ML never feeds the composite without the EV §5 gate.

## 8. Caveats

- Counts are from read-only queries on 2026-10-10; effort labels are estimates; LLM pricing/terms were not checked.
- India has thinner evidence and no filing dates for fundamentals; results there will be weaker.
- Model choices named here (MiniLM class, GARCH, gradient boosting) are starting points, not commitments.

## 9. Evidence status of each package (checked 2026-10-10)

Labels are defined in the legend near the top of this document.

"Verified" = I opened the source (abstract/text) in this session. "Unverified" = cited from memory; check before
relying on a figure. **Backing means "worked on someone else's data" — every gate above still re-tests it on this database.**

| Package | Backing | Status | What it implies |
|---|---|---|---|
| 🟢 **ML-0** experiment discipline, trial budget | Strong. Bailey, Borwein, López de Prado & Zhu, *The Probability of Backtest Overfitting*; Bailey & López de Prado, *The Deflated Sharpe Ratio* (J. Portfolio Management 40(5), 2014): hold-out is unreliable for backtests; with 5 years of data ≲ 45 independent trials | **Verified** | Count trials; use DSR/PBO; budget the search |
| 🔵 **ML-1** anomaly detection (data + nodes) | Engineering practice. Robust (MAD) statistics and isolation forests are standard methods, but there is no finance-return claim here | Unverified citations; **no research needed** | Validate on your own replay. The node "wedge signature" rests on **one** outage — unproven until more events accrue |
| 🔵 / ⚪ **ML-2** news embeddings / clustering | Method-level only (sentence embeddings; topic detection and tracking). No evidence that it improves returns | Unverified; **benefit unproven, sample tiny** | Store embeddings now; judge by hand-checked cluster quality, not returns |
| 🟢 **ML-3** volatility forecasts | Good. Hansen & Lunde (J. Applied Econometrics 20(7), 2005): 330 models; GARCH(1,1) not beaten for FX, **inferior for IBM returns where leverage-effect models win** | **Verified** | Include GJR-GARCH/EGARCH for equities (plan updated); keep EWMA/GARCH baselines |
| ⚪ **ML-4** regime model | Trend filter: published (Moskowitz, Ooi & Pedersen 2012 via the EV roadmap). HMM/mixture regimes: academic literature exists, out-of-sample usefulness is mixed | **Unverified** | Descriptive only until EV-0 shows an out-of-sample difference (already gated) |
| 🟡 **ML-5** peer clusters | Partial. Hoberg & Phillips (J. Political Economy 124(5), 2016): *text-based* (10-K) industries explain rival lists better than standard classes. Return-correlation clustering is standard but **not the researched method** | Hoberg–Phillips **verified**; correlation clustering unverified | Test text-based similarity for US names too (plan updated) |
| 🟡 **ML-6** GBM/NN return ranker | Real but conditional. Gu, Kelly & Xiu (RFS 33(5), 2020): trees and networks improve out-of-sample prediction (monthly stock-level R² ≈ 0.33–0.40%); decile long-short Sharpe 1.35 (value-weighted). Avramov, Cheng & Metzker (Management Science 69(5), 2023): profits concentrate in hard-to-arbitrage stocks and shrink after costs and without microcaps | **Verified** | Weakest fit for large-cap universes; expect small/null; keep the hard gate |
| 🔵 (rule: 🟢) **ML-7** LLM narration | No return-prediction claim relied on. Glasserman & Lin (J. Financial Data Science 6(1), 2024): LLM news-sentiment signals suffer look-ahead bias and a "distraction effect" | **Verified** | Supports "LLM never in scoring". Narration benefit is a product judgement, not a research result; grounding + verifier are engineering controls |
| 🔵 **ML-8** TX2 role | Engineering decision (ADR 0007) | n/a | none |

**Plan changes from this check:** ML-0 gets an explicit trial budget; ML-3 adds leverage-effect models; ML-5 adds a text-based
test; ML-6 expectations are lowered and the evaluation must exclude small/illiquid names and include costs.

**Not verified this session (cited from memory — check before use):** Hamilton (1989) and Ang & Bekaert (2002) on regime
switching; Liu et al. (2008) isolation forest; Leys et al. (2013) on MAD; Reimers & Gurevych (2019) Sentence-BERT; Tetlock
(2007); Moskowitz, Ooi & Pedersen (2012); the EV roadmap's own reference list (which says the same about itself).
