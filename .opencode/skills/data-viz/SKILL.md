---
name: Data Visualization
description: Use when making charts or dashboards — matplotlib defaults, chart-type choice, colors, labeling, and when Grafana beats a static plot. Charts save to out/.
---

# Data visualization defaults

## Static plots (matplotlib)
- figsize (10, 4)–(10, 6), dpi 150; save to `out/<nn-descriptive>.png` — never
  only display inline.
- One message per chart. The title states the takeaway ("Nifty 50 up 12% since
  June"), not the column names.
- Direct-label lines instead of a legend when there are ≤6 series; use a legend
  only when series can't be separated.
- Date axes: clean year/month tick formatting; light y-grid only, never both axes.
- Colors: colorblind-safe palette (Okabe-Ito). Reserved semantics: red =
  negative, green = positive — only for signed quantities like returns/flows.
- Annotate events (regime shifts, feed deaths) with thin vertical lines + small
  labels.

## Chart choice
- Over time → line chart. Bars only for ≤12 discrete points.
- Distribution → histogram; ECDF when honesty about tails matters.
- Two quantities + time → two stacked panels sharing an x-axis. Never dual
  y-axes; if unavoidable, color each axis to its series and say so in the caption.
- Correlation → scatter with alpha for volume; fit a robust line (Theil-Sen)
  when outliers are present, not OLS.

## Grafana vs static
- Grafana for recurring operational views (freshness, row counts, prices).
  Dashboards must ship `"time": {"from": "now-90d", "to": "now"}` — daily data
  renders empty under the 6h default (manual §8 gotcha).
- Static for one-off analysis and reports. Before adding Grafana panels,
  confirm the postgres datasource uses `jsonData.database` (Grafana 12 only
  reads it there — top-level `database:` silently breaks browser panels).

## Report embedding
- Every chart needs: the timeframe covered, the source query or table, and a
  one-sentence caption stating the takeaway. A chart without a caption is a bug.
