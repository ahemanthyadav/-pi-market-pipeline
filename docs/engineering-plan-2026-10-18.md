# Engineering plan — 2026-10-18

> Owner direction (2026-10-18): UPS not needed; redesign dedup only if it adds value; plan and do the large
> engineering work. Status per item is kept in `pending-tasks.md` (the tracker); this file is the order and
> the reasoning. No IPs or secrets here (AGENTS rules 7–8).

## 0. Decisions taken
- **UPS — not needed** (owner). Accepted consequence: a mains loss takes every node and the pi0 watcher down
  together; recovery is automatic (verified 2026-10-18).
- **Dedup — retired, not redesigned.** Measured 2026-10-18: each Pi holds 1–2 GB of user data on a 229 GB SSD
  (5–7 % used); TX2 `sda4` is 12 % used, mostly images/DB. There is nothing worth deduplicating across nodes,
  and the design targets drives that do not exist. Code kept in `piCluster/cluster/` with a RETIRED note.

## 1. Order (dependencies first; each step canaried before the next)
| # | Work | Why first | Ships as |
|---|---|---|---|
| 1 | **AR-4** DB readiness probe + Guaranteed QoS | restarts the single DB — do it before long backfills | StatefulSet spec |
| 2 | **DQ-1** corporate-actions history backfill + **own `adj_close`** (total return) | returns/momentum are wrong across dividends; EV-0 needs it | `screener:v12` + one-off Job |
| 3 | **G-1** `price_anomalies` writer (>40 % jumps, restated history) | makes bad bars visible instead of silently scored | `screener:v12` |
| 4 | **G-2a** weekly membership snapshots | survivorship record starts accruing only once it exists | `screener:v12` + seed |
| 5 | **DQ-2** `financial_facts` writer (duration-aware, first filing) | fixes YTD-vs-annual and point-in-time; blocks EV-9…15 | `screener:v12` + full pass |
| 6 | **DQ-2** screener reads duration-aware TTM (flag, then flip) | the actual score fix; diff top-50 before/after | env flag, no rebuild to flip |
| 7 | **EV-0** signal-test harness + first price-signal tests (EV-3/4/5/7) | gate for every scoring/ML change | `ops-tools/ev0/` (workstation) |
| 8 | **AR-8** read-only DB role for Grafana, scoped role for the bot | least privilege on the tailnet-exposed readers | Secret + datasource/env |
| 9 | news/sentiment unique constraints | last tables without a dedup guard | depends on finding |
| 10 | **AR-6/7** repo layout + kustomize base | pure refactor; do last, parity-checked | repo only |

## 1a. Outcome (2026-10-18, 13:10 UTC)
| # | Result |
|---|---|
| 1 AR-4 | ✅ Guaranteed QoS + readiness probe, 17 s downtime |
| — chunk merge (found on the way) | ✅ stock_prices 3,382 → 107, index_prices 300 → 84 chunks; planning 34 s → 34 ms |
| 2 DQ-1 adj_close + actions | ✅ backfill 998/998, 0 NULL adj_close; sanity vs dividend yields OK |
| 3 price_anomalies | ✅ writer live (v12), restated → resync |
| 4 G-2a snapshots | ✅ first snapshot 998 rows |
| 5 DQ-2 facts writer | ✅ 305k EDGAR facts / 502 cos; MSFT acceptance check passed |
| 6 DQ-2 reader | ✅ flipped live after dry-run diff (SP500 46/50, NIFTY 50/50); stale-series bug found + guarded (v13) |
| 7 EV-0 | ✅ built + run; nothing passes §5; NIFTY 12-1 momentum strong; US blocked on EV-1 survivorship |
| 8 AR-8 | ✅ grafana_ro, telegram_app live (pipeline-job writer role deferred, reasoned) |
| 9 news constraints | ✅ live without a rebuild (writers already safe) |
| 10 AR-6/7 | ◐ intent via CI safeguard test; path move declined (reasoned) |

## 2. Explicitly not in this pass (gated by their own plans)
ML-0…ML-7, regime layer, 3090/GraphRAG, composite v2 (EV-17/18): `ml-roadmap-2026-10-10.md` and the EV
roadmap hard-gate them on EV-0 results, EV-1 historical membership and composite v2 passing EV §5. Building
them before step 7 produces numbers nobody can trust. Re-plan after the first EV-0 report.

## 3. Rules for every step
- Additive schema only; idempotent writers (ADR 0005); `00:00 UTC` trade-date stamps (ADR 0013).
- One image per rebuild cycle, tarball saved to the TX2 store, checksums at each hop; pi3 then pi1.
- Never `crictl rmi --prune`. pi2 load < 3 before any mutation.
- A step is done only when its canary output and DB check are recorded in the tracker.
