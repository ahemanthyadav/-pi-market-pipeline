---
name: Report Writer
description: Use when turning analysis results into a readable summary — inverted-pyramid structure, chart embedding and captioning, number formatting, audience calibration.
---

# Report writing

## Structure (inverted pyramid)
1. **TL;DR** — ≤3 sentences: what was asked, what was found, what it means.
2. **Key findings** — 3–5 bullets, each a number + its interpretation.
   Strongest first.
3. **Evidence** — charts (paths under `out/`) + key tables.
4. **Caveats** — data-quality limits; what would change the conclusion.
5. **Next steps** — optional, concrete.

## Numbers
- One consistent precision per quantity: 2 dp for returns, 0 dp for row counts.
- Pair every change with its baseline: "+4.2% (vs 3.1% prior month)".
- Ranges beat false certainty; a confidence interval is a feature.
- State the calendar for dates (IST vs UTC) when data is mixed-market.

## Charts
- Reference by path; every chart gets a one-sentence caption stating the
  takeaway, plus timeframe and source table.
- A chart the TL;DR doesn't need belongs in the appendix, not the body.

## Audience calibration
- Default: technically literate but not project-embedded. Explain
  pipeline-specific terms (heartbeat, FII/DII) at first use.
- Ops audience: start with what's broken / what to watch.
- Analysis audience: start with the finding, not the methodology.

Length target: ≤1 page per 10 charts. Cutting is the job.
