# Nifty 500 + S&P 500 fundamental analysis — implementation plan

Extension layer on top of the existing k3s + TimescaleDB + Pi workers + Jetson TX2 market-data pipeline. This does **not** replace the current price/sentiment pipeline — it adds a structured fundamental-analysis layer (security master, financial statement ingestion, scoring engine, research dashboard) on top of it.

**Configuration locked in for this plan:**
- Historical fundamentals: **as far back as each source's structured data reaches** — maximum history, no fixed cap (per-source limits in §4: EDGAR structured ~2009→ with older US history existing as unstructured filings = a future parsing project, not a blocker)
- Primary screening style: **Balanced** (quality + growth + value + risk)
- Fundamentals sourcing: **Mixed** (official filings + existing/free normalized sources)
- AI report generation: **Shortlist only** (not all ~1,000 companies)

**Architectural principle preserved throughout:** TimescaleDB remains the source of truth, k3s CronJobs remain the scheduler, Grafana remains the operational UI, and the RTX 3090 is an optional research worker — not a dependency for the core pipeline. No Kafka, Airflow, distributed database, or continuously-running large model is needed for ~1,000 stocks/day.

**Role of this document (2026-10-03 merge):** this is the **target architecture** for the
fundamental-analysis layer. The concrete v1 build order is
`stock-screener-implementation-plan.md` (canary-first rollout, chunked Yahoo prices,
explicit percentile scoring). v1 already adopts this document's three key decisions:
the **security-master upgrade** (ISIN/CIK + membership dates), **point-in-time
fundamentals** (`filing_published_at` separate from period end, never backtest with
future filings), and **SEC EDGAR company-facts as the US fundamentals source**
(yfinance stays as the NSE leg / interim). Everything else below — sector-relative
6-component scoring, classifications, style tags + investor lenses (§13), market
regime layer (§14) — is v2+, built on top of v1's tables, not replacing them.

---

## 1. What this system should answer

Not just a daily price scanner — a system that answers:
- Which companies are fundamentally strong?
- Which are attractively valued relative to their own history and peers?
- Which are improving or deteriorating financially?
- Which have debt, cash-flow, earnings-quality, or governance concerns?
- Which deserve deeper research today?
- Which stocks should be monitored, ranked, or excluded based on investment criteria?

Built as: **data pipeline → fundamental scoring engine → research queue → dashboard**, with AI assisting interpretation rather than inventing financial facts.

---

## 2. Target architecture

1. **Universe and source ingestion** — Nifty 500 + S&P 500 constituent history, prices, financial statements, filings
2. **Normalize and validate** — ticker mapping, fiscal periods, currency, consolidated accounts, freshness checks
3. **Market engine** — returns, valuation, volatility, relative strength
4. **Fundamental engine** — growth, profitability, debt, cash flow, valuation
5. **Ranking and classification engine** — sector-relative scores, risk flags, stock archetypes, confidence and data completeness
6. **Research workspace** — daily shortlist, rankings, alerts, company reports, historical changes, AI-assisted explanations

Core design principle: **prices update daily, but fundamental facts update only when companies report or revise results.** Recalculating valuations daily is useful; treating quarterly financials as newly updated every day is not.

---

## 3. Security master (organize the universe first)

A permanent security master, not reliance on ticker symbols alone:

| Field | Purpose |
|---|---|
| `security_id` | Internal, stable identifier |
| `exchange` | NSE or relevant US listing exchange |
| `symbol` | Exchange-specific ticker |
| `company_name` | Display name |
| `isin` / `cik` | Identifier where available |
| `country`, `currency` | India/INR or US/USD |
| `sector`, `industry` | Peer comparisons |
| `index_memberships` | Nifty 500, S&P 500, or both |
| `valid_from`, `valid_to` | Historical membership tracking |
| `active`, `last_verified_at` | Lifecycle and data quality |

Symbols change, companies delist, index constituents change. For credible historical backtests, use **historical membership**, not today's membership applied retroactively.

**Build a daily universe reconciliation job** that identifies additions, removals, symbol changes, missing prices, and missing fundamentals.

---

## 4. Data sources (different strategy per market)

### S&P 500 — SEC filings first
Use the SEC's company submissions and XBRL company-facts APIs for financial statements, filing dates, reported facts, and historical filings — official, machine-readable US sources.
- Official resource: SEC EDGAR API documentation

### Nifty 500 — exchange filings plus normalized fundamentals
Use official corporate filings, integrated financial filings, and exchange reports where accessible. NSE publishes financial filings and disclosures, but don't assume a stable, unrestricted bulk API exists for every field needed.
- Resources: NSE integrated financial filings, NSE reports

**Source priority for low-cost implementation:**
1. Official filings for reported financial facts and reporting dates
2. Existing Yahoo Finance ingestion for daily prices and basic market data, with validation
3. A normalized fundamentals provider if manual parsing of hundreds of Indian filings becomes too costly
4. Company annual reports and earnings releases for facts missing from structured feeds
5. News and AI extraction as supporting evidence, not as the authoritative financial database

**Important caveats:**
- NSE's published corporate-data subscription is a paid product — check access terms before building around exchange data for broader redistribution or commercial use.
- Avoid making one provider responsible for both US and Indian fundamentals — accounting conventions, fiscal calendars, identifiers, and field coverage differ.
- **"As far back as available" has real practical limits per source.** SEC EDGAR's XBRL (structured) data generally only goes back to roughly 2009–2011 when XBRL filing became mandatory — older SEC history exists but as unstructured text filings (10-K/10-Q PDFs/HTML), requiring separate parsing rather than a clean API pull. NSE's electronic filing archive depth is more limited and less standardized than SEC's. Treat "full history" as "as deep as each source's structured data reaches," and flag anything beyond that as a future unstructured-parsing project rather than blocking Phase 2 on it.

---

## 5. What to calculate for every company

Six fundamental analysis categories; a company can belong to several, but gets a primary classification:

| Category | Focus | Key question |
|---|---|---|
| **A. Quality compounders** | ROIC/ROE, operating margins, FCF, earnings consistency, balance-sheet strength, dilution, multi-year growth | Is the business consistently creating value? |
| **B. Value opportunities** | P/E, EV/EBITDA, P/B where appropriate, FCF yield, earnings yield, valuation vs. history/peers | Is the market price reasonable for the business's performance? |
| **C. Growth companies** | Revenue/EPS CAGR, operating-profit growth, forward expectations, reinvestment, cash conversion | Is growth durable, profitable, and reasonably priced? |
| **D. Financially stressed/improving** | Debt-to-equity, interest coverage, debt maturities, OCF vs. earnings, leverage trends, margin deterioration | Is the business deteriorating, recovering, or becoming fragile? |
| **E. Income and dividend stocks** | Dividend yield, payout ratio, FCF coverage, dividend history, debt, consistency | Is the dividend sustainable rather than simply high? |
| **F. Cyclical/special situations** | Normalized margins, inventory, capacity utilization, commodity exposure, earnings volatility, corporate actions, turnaround evidence | Are reported earnings near a cyclical peak, trough, or sustainable level? |

**Sector-specific scorecards are essential** — banks/insurers need different balance-sheet and profitability metrics from manufacturers, retailers, or software companies. Don't force every metric onto every company.

---

## 6. Scoring engine

Calculate individual component scores first, then an overall ranking — keep component scores visible so rankings are explainable.

**Illustrative starting weights (calibrate by sector, validate via historical testing):**

| Component | Weight | What it measures |
|---|---|---|
| Business quality | 25% | Returns on capital, profitability, consistency |
| Growth | 20% | Revenue, earnings and operating-profit trends |
| Valuation | 20% | Relative price, cash-flow yield, valuation history |
| Balance sheet | 15% | Leverage, liquidity, interest coverage |
| Cash-flow quality | 10% | Cash conversion, earnings vs. cash generation |
| Price and trend | 10% | Momentum, drawdown, relative strength |

Each component: normalized 0–100 score, preferably using **sector-relative percentiles** (compare a bank's profitability to other banks, not to a software company).

**Example ranking rules:**
- **High-quality candidates:** quality ≥ 75, positive cash-flow trend, no severe financial-risk flags
- **Undervalued research candidates:** attractive sector-relative valuation + acceptable business quality and balance sheet
- **Improving businesses:** improving margins, earnings revisions, or cash flow, with supporting price action where available
- **Risk watchlist:** weak cash conversion, worsening leverage, persistent margin contraction, or unreliable financial data

**Rules that matter more than the exact weights:**
- Missing fundamentals must never silently become zero or a bad score — display data completeness alongside the score
- A serious balance-sheet warning should never be hidden by a high growth score
- Use adjusted prices for splits and dividends where appropriate
- Separate reported values from estimates and calculated ratios
- Keep historical score snapshots to track improving/deteriorating companies over time
- **Never use future filings in historical backtests** — use only information available as of each historical date (point-in-time data discipline)

---

## 7. TimescaleDB schema additions

Add these tables to the existing database; keep current price and technical-indicator tables intact.

| Table | Contents | Update frequency |
|---|---|---|
| `security_master` | Company identifiers, symbols, sector, country, index membership | Daily reconciliation |
| `financial_periods` | Revenue, operating income, net income, EPS, assets, liabilities, equity, debt, cash flow | On new filings |
| `financial_facts_raw` | Original source facts, units, period, filing ID, provenance | On new filings |
| `company_ratios` | P/E, P/B, EV/EBITDA, ROIC, ROE, margins, leverage, cash-flow ratios | Daily or after relevant updates |
| `valuation_history` | Daily valuation metrics and historical percentiles | Daily |
| `fundamental_scores` | Component scores, composite score, classification, flags | Daily |
| `stock_classifications` | Quality/value/growth/income/cyclical/stressed/special-situation labels | Daily or on new filings |
| `filing_events` | Filing date, report period, source, revision, processing status | On new filings |
| `analysis_runs` | Run status, source freshness, row counts, errors, duration | Every run |
| `research_notes` | AI-generated summaries, cited evidence, review status | On demand or after material changes |

**For every financial fact, retain:** `security_id`, `metric`, `value`, `currency`, `period_start`/`period_end`, `fiscal_period`, `filing_published_at`, `source`, `source_document_id`, `is_consolidated`, `is_estimated`, `ingested_at`.

This avoids confusing a quarter *ending* June 30 with a result not actually *published* until August.

**Preserve revisions** rather than overwriting previously reported values — store the original filing and normalized value separately.

---

## 8. Daily execution plan (on the existing cluster)

Pi workers handle API ingestion and Python scoring for ~1,000 stocks; TX2 continues handling the database and the existing CPU sentiment model.

| Timing | Stage | Job |
|---|---|---|
| Daily | Universe | Reconcile stock universe — refresh constituents, mappings, symbol changes, active listings |
| Market close | Prices | Ingest and validate EOD prices — coverage, timestamps, corporate actions, missing symbols |
| After filings | Fundamentals | Incremental financial-statement ingestion — new filings, revisions, normalized units/periods, only affected companies updated |
| Daily | Analytics | Compute ratios and rankings — update valuation ratios from latest price + latest fundamentals, recompute trend metrics and sector-relative scores |
| Daily | Research | Publish daily research shortlist — rank candidates, flag anomalies, identify score changes, generate reports only for companies meriting attention |

**Suggested CronJobs** (logical jobs, not mandatory UTC times — schedule each market's price job after its local close, allow for delayed data publication):

| CronJob | Function |
|---|---|
| `universe-reconcile` | Daily membership and symbol reconciliation — v2 refinement of v1's weekly `universe-refresh` constituent loader (name kept distinct) |
| `us-eod-prices` | S&P 500 daily prices |
| `india-eod-prices` | Nifty 500 daily prices |
| `fundamentals-discovery` | Find new financial filings |
| `fundamentals-normalize` | Normalize and validate new statements |
| `fundamental-ratios` | Recalculate affected ratios and daily valuation |
| `fundamental-ranking` | Generate classifications and rankings |
| `research-shortlist` | Produce reports and alerts |
| `analysis-health-check` | Implemented as **feed extensions to the existing `pipeline-health` CronJob** (heartbeat table) — no parallel monitor |

**Don't fetch all historical financial statements every day.** Bootstrap history once, then ingest incrementally. Recompute ratios daily, but recompute long historical fundamentals only when underlying statements or definitions change.

**Target:** a complete daily ranking run finishing within minutes after data is ready, excluding slower external filing ingestion.

---

## 9. Research dashboard (Grafana or equivalent)

Rather than one enormous table of ~1,000 companies:

1. **Market-wide screener** — all eligible stocks, composite score, quality/growth/valuation/debt-risk scores, sector, latest price, data freshness
2. **Best candidates** — top quality compounders, undervalued quality companies, improving businesses, dividend candidates
3. **Company deep dive** — full available history of revenue, earnings, margins, ROIC/ROE, debt, FCF, valuation history, filing events (depth varies by company/market, per the earliest-year coverage from the universe audit)
4. **Risk and deterioration** — negative cash flow, leverage increases, earnings deterioration, unusually high valuation, missing statements, stale prices
5. **Daily changes** — companies with material ranking changes, new filings, score improvements, risk flags, news events linked to financial evidence

---

## 10. Where AI fits

**Don't** use an LLM to calculate P/E, ROE, debt ratios, or fundamental rankings — those belong in deterministic Python/SQL code.

**Do** use AI for:
- Summarizing a quarterly result against the previous quarter and year
- Extracting management guidance and material risks from filings
- Explaining why a company's score changed
- Identifying risks in annual reports and earnings-call transcripts
- Connecting news events with affected companies, sectors, and financial metrics
- Drafting a company research report with citations to the original filings

**Illustrative example only — not a real company assessment:**

| Metric | Value |
|---|---|
| Quality score | 82/100 |
| Valuation score | 61/100 |
| Growth score | 78/100 |
| Financial risk | Moderate |

Strengths: strong historical profitability; revenue and operating earnings trending upward; cash generation broadly supports reported earnings.
Concerns: current valuation above historical median; recent margin improvement needs further confirmation.
Next research actions: review latest earnings release; compare valuation against sector peers; reassess after the next reported quarter.

In the real system, every claim links to its metric, period, and source filing.

**Hardware split:** RTX 3090 is the better home for heavier document analysis, embeddings, and report generation. TX2 continues handling the database and existing lightweight scheduled workloads. Generate detailed AI reports only for a shortlist of ~20–50 companies/day, not all ~1,000.

---

## 11. Implementation roadmap (phased, to avoid destabilizing the production cluster)

| Phase | Focus | Deliverable |
|---|---|---|
| **1. Universe and data coverage** | Build security master, import constituents, map tickers/identifiers, audit daily price coverage, identify fundamentals data gaps | Coverage report for both indices |
| **2. Fundamental history** | Import annual and quarterly financials as far back as each source has them (varies by company and market — SEC EDGAR often reaches back 20+ years for established filers, NSE electronic filing depth is more limited), retain source facts and filing dates, normalize metrics, validate a sample manually | Reliable financial-period tables |
| **3. Ratios and classifications** | Build sector-specific metrics, quality/value/growth/risk scores, historical ranking snapshots | Complete stock screener |
| **4. Dashboard and alerts** | Build company deep dives, daily changes, stale-data alerts, research queues | Daily research workflow |
| **5. AI research assistant** | Use the RTX 3090 to summarize selected filings, explain score changes, produce evidence-linked company reports | Deeper analysis without added TX2 load |

**Recommended starting point: Phase 1.** Universe coverage and data-source validation is the biggest dependency — a sophisticated scoring model isn't useful if 30% of companies have missing financial statements, or if the same metric means different things across providers.

**Phase 3.5** = style tags & investor lenses (§13). **Phase 3.6** = market regime layer (§14) — the FRED-sourced series (14.2–14.6) can build anytime using the existing `rates-fetcher` pattern + FRED Secret; breadth (14.1) waits on Phase 1/2 constituent prices.

---

## 12. First concrete deliverable — universe audit job

Before any scoring logic, build a standalone universe-audit job producing a report like:

| Metric | Nifty 500 | S&P 500 |
|---|---|---|
| Expected constituents | 500 | 500 |
| Mapped securities | *to measure* | *to measure* |
| Daily price coverage | *to measure* | *to measure* |
| Full-history annual statement coverage (earliest year reached, per company) | *to measure* | *to measure* |
| Full-history quarterly statement coverage (earliest year reached, per company) | *to measure* | *to measure* |
| Missing key financial metrics | *to measure* | *to measure* |
| Ambiguous ticker mappings | *to measure* | *to measure* |
| Source freshness | *to measure* | *to measure* |

These are target measurement categories, not current-state claims.

Once this report identifies real gaps, the next build is the security master, source adapters, and the financial-fact schema (Section 7). SEC EDGAR provides public APIs for US company submissions and XBRL data; NSE's integrated financial filings page exposes company financial submissions and revisions — sensible starting points for both markets.

---

## 13. Investment-style tags and investor-lens screens

A layer on top of the Section 5/6 scoring — instead of (or alongside) a single primary classification, tag each company against **recognized investing styles** and **rule-based approximations of well-known investors' public methodologies**. These reuse data already in the schema (Section 7) plus the existing price/technical tables — no new data sources needed, just new derived views.

### 13.1 Investment style tags

Each stock can carry multiple style tags (not mutually exclusive), each with its own score and the market condition it tends to suit:

| Style | Focus | Horizon | Risk | Key inputs (already in schema) | Favorable regime |
|---|---|---|---|---|---|
| **Value** | Buy undervalued assets | Long-term | Moderate | P/E, P/B, EV/EBITDA vs. sector/history percentile | Volatile or bear markets |
| **Growth** | High growth potential | Medium-long | Moderate-high | Revenue/EPS CAGR, operating-profit growth | Bull markets |
| **Momentum/Trending** | Price trend continuation | Short-medium | High | RSI, MACD, moving averages, relative strength (existing `technical_indicators` table) | Trending markets |
| **Income** | Regular cash flow | Long-term | Low-moderate | Dividend yield, payout ratio, FCF coverage (Category E, Section 5) | Stable markets |
| **Contrarian** | Go against consensus | Varies | High | Oversold technical readings + negative sentiment (existing FinBERT table) + sound fundamentals despite depressed price | Market extremes |
| **Quality/Long-term compounder** | Durable value creation | Long-term | Low-moderate | ROIC/ROE, margin consistency, low dilution (Category A, Section 5) | Any market |
| **Index/benchmark-relative** | Track or compare to market | Long-term | Varies with market | Not a stock tag — a **portfolio-level view**, not computed per company (see note below) | Any market condition |

**Implementation:** a `style_classification` table (`security_id`, `style_name`, `style_score` 0–100, `as_of_date`), populated by a new `style-tagging` CronJob that reads from `fundamental_scores`, `company_ratios`, and the existing `technical_indicators`/sentiment tables — no new ingestion required.

**Note on Index Investing:** this isn't a per-stock screen — it's a portfolio construction philosophy (match the market rather than pick stocks). The closest useful equivalent here is a **benchmark-tracking panel** in Grafana (your portfolio or shortlist's aggregate performance vs. Nifty 500/S&P 500 index returns), not a `style_classification` row. Worth adding as a dashboard panel, not a scoring dimension.

### 13.2 Investor-lens screens

Rule-based approximations of publicly known investing philosophies, built from the same underlying data. **These are simplified, mechanical screens inspired by publicly documented approaches — not verified replications of, or endorsed by, any individual.** Treat them as additional research lenses, same caution as the rest of the scoring system (Section 6's "rules that matter more than exact weights" apply here too).

| Lens | Approximated from | What it screens for |
|---|---|---|
| **Buffett/Munger-style** | ROE consistency, high and stable margins, low debt-to-equity, consistent earnings growth over many years, reasonable price relative to a conservative intrinsic-value estimate | Durable-moat, high-quality businesses at a sensible price — closest match to your existing Category A "Quality compounders" |
| **Graham-style deep value** | Low P/E, low P/B, strong current ratio, low debt, price below a Graham-number-style conservative asset/earnings estimate | Statistically cheap, balance-sheet-safe stocks — overlaps your Category B "Value opportunities" but with stricter safety filters |
| **Lynch-style GARP** | PEG ratio (P/E ÷ earnings growth rate) < ~1, moderate size, consistent earnings growth | "Growth at a reasonable price" — a middle ground between pure Growth and pure Value tags |
| **Greenblatt-style "Magic Formula"** | Rank by combined earnings yield (EBIT/EV) and return on capital (EBIT / (net working capital + net fixed assets)); take the top-ranked combination | A mechanical quality + cheapness combination, distinct from a weighted composite score |
| **Damodaran-style valuation** | A proper DCF: free cash flow to firm, WACC, explicit growth and terminal-value assumptions, compared against current price with a margin-of-safety band | Story-driven intrinsic value rather than relative/ratio-based valuation — more build effort than the ratio-based screens above, since it needs a real DCF engine, not just stored ratios |
| **Contrarian/Marks-style** | Valuation percentile vs. the stock's own historical range + current sentiment/technical oversold readings | Identifies stocks priced near historical valuation extremes, where sentiment is most negative relative to fundamentals |

**Implementation:** an `investor_lens_scores` table (`security_id`, `lens_name`, `lens_score`, `rationale_snapshot`, `as_of_date`), computed by a new `investor-lens-scoring` CronJob. The ratio-based lenses (Buffett, Graham, Lynch, Greenblatt) are straightforward SQL/Python against existing `company_ratios` and `fundamental_scores` — low additional engineering cost. The Damodaran-style DCF lens is meaningfully more work (needs a real valuation model, not just stored ratios) — treat it as a later addition, not part of the initial build.

### 13.3 Dashboard addition

A **Strategy Lenses** dashboard (alongside the five from Section 9): filterable by style tag or investor lens, showing which stocks score highly under each lens, where lenses agree or disagree on the same stock (a stock scoring well under both Buffett-style and Graham-style lenses is a stronger signal than one scoring well under only one), and a benchmark-tracking panel for the Index-investing comparison.

### 13.4 Rollout placement

This layer slots in as **Phase 3.5** — after the core scoring engine (Phase 3) is built and validated, before the dashboard phase (Phase 4), since the style tags and investor lenses are derived views on top of the Section 6 scores rather than a prerequisite for them. The Damodaran DCF lens can be deferred further, into Phase 5 alongside the AI research assistant work, given its higher build cost.

---

## 14. Market indicators & regime markers (macro layer)

Section 6's scores and Section 13's style/lens tags operate at the **individual stock** level. This layer sits above both — market-wide signals that tell you what *regime* the market as a whole is in, which is useful context for interpreting any individual stock's score (a "Value" tag means something different in a cheap, bombed-out market than in an expensive one). Grouped by what each category actually tells you, with only indicators that have a real, obtainable data source — nothing here needs a new paid subscription.

### 14.1 Market breadth (internal market health)

Computed directly from the per-stock daily price data you're already ingesting for the Nifty 500/S&P 500 constituents (Section 8) — no new data source needed, just aggregation.

| Indicator | What it tells you | Computation |
|---|---|---|
| Advance/decline line | Breadth of a rally or selloff — is the move broad or narrow? | Daily count of advancing vs. declining constituents |
| % of stocks above 50-day / 200-day MA | How much of the market is in an uptrend vs. a handful of large names carrying the index | Per-stock MA comparison, aggregated |
| New 52-week highs vs. new 52-week lows | Leading signal of broad strength/weakness, often diverges from the index price before a reversal | Daily count from constituent price history |

### 14.2 Volatility & risk appetite

| Indicator | What it tells you | Source |
|---|---|---|
| VIX / India VIX | Already in your pipeline — near-term fear gauge | Existing `index_prices` table (`^VIX`, `^INDIAVIX`) |
| High-yield credit spread (ICE BofA US High Yield OAS) | Widening spreads signal credit stress before equity markets typically react | FRED (`BAMLH0A0HYM2`) |
| Put/Call ratio (CBOE) | Options positioning — elevated puts can signal fear/hedging, extreme complacency can precede reversals | CBOE published data |

### 14.3 Valuation extremes (market-wide, not single-stock)

| Indicator | What it tells you | Source |
|---|---|---|
| Buffett Indicator (total market cap ÷ GDP) | Historically referenced gauge of whether the overall market is expensive vs. the real economy | Computable from FRED (`WILL5000PR` market cap proxy ÷ `GDP`) |
| Shiller CAPE ratio (S&P 500) | Cyclically-adjusted P/E — smooths out single-year earnings distortions for a longer-view valuation read | Robert Shiller's published dataset (manual/periodic pull, not a clean API) |
| Nifty aggregate P/E vs. historical median | Same idea for the Indian market | NSE-published Nifty P/E/P/B/dividend-yield data |

### 14.4 Yield curve & macro rates

| Indicator | What it tells you | Source |
|---|---|---|
| US 10Y–2Y Treasury spread | Inversion has historically preceded recessions — a widely watched regime marker | FRED (`T10Y2Y`) |
| Real interest rates (nominal rate − inflation) | Tightening/easing financial conditions beyond the headline rate | Derived from existing `interest_rates` table + CPI |

### 14.5 Sentiment & positioning (beyond your existing news sentiment)

| Indicator | What it tells you | Source |
|---|---|---|
| AAII Investor Sentiment Survey (bull/bear spread) | Retail positioning extremes — often contrarian at the extremes | AAII published weekly survey (US-specific) |
| FII/DII net flows | Already in your pipeline — institutional positioning | Existing `capital_flows` table |

### 14.6 Macro indicators (lower frequency, context rather than daily signal)

| Indicator | What it tells you | Source |
|---|---|---|
| CPI / inflation rate (India + US) | Context for rate decisions and real-return calculations | FRED (`CPIAUCSL`) / RBI, MOSPI |
| Unemployment rate (US) | Standard macro health indicator | FRED (`UNRATE`) |
| PMI (manufacturing/services) | Leading indicator for economic momentum | ISM (US) / MOSPI or private PMI surveys (India) — check access terms, some are subscription-gated |
| GDP growth rate | Lower-frequency backdrop, not a trading signal | FRED (`GDP`) / MOSPI |

### 14.7 Regime markers (derived, not raw data)

Simple derived flags that summarize the above into an easy-to-read market state:

| Marker | Derived from |
|---|---|
| Bull/bear regime flag | Index price vs. its own 200-day MA |
| Golden cross / death cross | 50-day MA crossing above/below 200-day MA |
| Drawdown from all-time high | Current index level vs. historical peak |
| Yield curve inverted (Y/N) | 10Y–2Y spread sign |

> India index note: the Nifty 500 index has no reliable Yahoo symbol (live-pipeline
> find). For India regime inputs use `^NSEI` (Nifty 50, already ingested daily) or the
> §14.1 constituent aggregate as the index proxy.

### 14.8 Schema and jobs

- New table `market_indicators` (`indicator_name`, `market` [India/US/Global], `timestamp`, `value`, `source`) — a generic time-series table, since most of these are single-value-per-day series rather than needing per-stock granularity.
- New table `market_regime_flags` (`flag_name`, `market`, `as_of_date`, `value`) for the derived boolean/categorical markers in 14.7.
- New CronJobs: `market-breadth-calc` (daily, depends on constituent price data already being ingested), `macro-indicators-fetch` (daily for FRED-sourced series, weekly/monthly for AAII/CPI/PMI/GDP given their native cadence — don't force low-frequency data into a daily job).

### 14.9 Dashboard addition

A **Market Regime** dashboard: breadth panel (advance/decline, % above MAs, new highs/lows), a volatility/risk panel (VIX + credit spreads + put/call), a valuation-extremes panel (Buffett Indicator, CAPE, Nifty P/E vs. history), and the regime-flag summary (bull/bear, golden/death cross, drawdown, curve inversion) as a single always-visible status strip. This gives useful context when reading the Section 13 style/lens scores — e.g., a wave of new "Value" tags appearing alongside a market-wide valuation extreme is a stronger signal than the same tags appearing in an already-cheap market.

### 14.10 Rollout placement

This slots in as **Phase 3.6** alongside Section 13's Phase 3.5 (parallel work, not dependent on it) — breadth indicators (14.1) do depend on the constituent price ingestion from Phase 1/2 being in place, but the FRED-sourced macro series (14.2–14.6) can be built independently and earlier if useful, since they don't depend on anything else in this plan.

---

## 15. Operational constraints on this cluster (binding — from the live pipeline)

These are not style preferences; each was learned the hard way (see
`market-data-finds-and-projects.md` and the ops manual runbooks):

1. **No container registry.** Every new CronJob image follows the TX2-native build →
   `docker save | gzip` → per-worker `k3s ctr -n k8s.io images import` cycle (pi2's
   import runs detached). Budget this cycle per job; keep images on slim bases.
2. **pi2 fragility.** 1 GB control-plane that wedges under API bursts. Schedules
   staggered, `successfulJobsHistoryLimit: 3 / failedJobsHistoryLimit: 1`, mutations
   one-at-a-time on load < 2, agent restarts one-by-one. This plan's logical jobs land
   gradually across phases — never all at once.
3. **One health system.** `pipeline_heartbeat` + the `pipeline-health` CronJob are the
   single monitor; new data feeds register as heartbeat feed rows (image tag bump),
   not as parallel monitors.
4. **House idempotency vs revisions.** The pipeline's universal row-level
   DELETE+INSERT rule has exactly one sanctioned exception: `financial_facts_raw` +
   statement revisions (append-only with filing provenance, §7). Never DELETE+INSERT
   there; never apply append-only to prices or derived ratios.
5. **Sizing (verified headroom).** EDGAR full-history facts for ~500 companies ≈ low
   hundreds of MB in the 30 GiB PV; `company_ratios`/`valuation_history` ≈ ~1M rows/year.
   EDGAR refresh is cheap — one company-facts call per company (full bootstrap ≈ 500
   calls; incremental a handful/day). Max-history price tables (~4-6M rows) still fit
   comfortably. No DB limit or TX2 RAM-window changes needed.
6. **Per-job canary + validation.** Every job ships with a `kubectl create job
   --from=cronjob/<name>` canary + DB row-count checks (ops-manual §6 cycle) before
   its schedule goes live; long fetches resume via the `job_state` cursor.

## Architectural decisions preserved from the existing pipeline

- TimescaleDB remains the source of truth
- k3s CronJobs remain the scheduler
- Grafana remains the operational UI
- RTX 3090 is an optional research worker, not a dependency
- Keep the existing daily market-data pipeline running independently while this layer is built and validated **in shadow mode**

**Important framing:** the resulting rankings are a research and screening system, not automatic buy/sell instructions. Backtest scoring rules using point-in-time financial data, transaction costs, and historical index membership before relying on them for investment decisions.
