"""Shortlist reports (Phase G) — deterministic templates + existing FinBERT.

Per plan §8: for rank <= SHORTLIST_SIZE per universe, render a markdown report
(valuation vs universe medians, quality block, price block, news-sentiment
block joined from news_sentiment within 3 days) into stock_reports, plus one
combined '__digest__' row. No LLM in v1 — pluggable hook documented in the plan.

v8: the shortlist is each symbol's LATEST scores row (today's run) — the v1-v7
query had no ts filter and reported the union of every historical top-25.

Connection discipline (house pattern, 2026-10-04): autocommit reads, one atomic
transaction per report write, reconnect-and-retry once on a dropped
connection. The earlier shared-cursor/implicit-transaction version died
deterministically ("connection is closed") mid-loop — this layout matches the
proven prices/fundamentals/metrics fetchers.
"""
import os
import sys
from datetime import datetime, timezone

import psycopg

SHORTLIST = int(os.environ.get("SHORTLIST_SIZE", "25"))


def fmt(v, suffix=""):
    try:
        return f"{v:,.2f}{suffix}" if isinstance(v, (int, float)) else "n/a"
    except Exception:  # noqa: BLE001
        return "n/a"


def connect():
    conn = psycopg.connect(
        host=os.environ.get("PGHOST", "timescaledb.market-data.svc.cluster.local"),
        user=os.environ.get("PGUSER", "postgres"),
        password=os.environ["PGPASSWORD"],
        dbname=os.environ.get("PGDATABASE", "postgres"),
    )
    conn.autocommit = True
    return conn


def q1(cur, sql, args=()):
    cur.execute(sql, args)
    return cur.fetchone()


def news_block(cur, sym, name):
    base = sym.replace(".NS", "").replace("-", ".")
    first = name.split()[0] if name else ""
    cur.execute(
        """SELECT headline, sentiment_score FROM news_sentiment
           WHERE ts >= now() - interval '3 days'
             AND (ticker_relevance ILIKE %s OR headline ILIKE %s
                  OR ticker_relevance ILIKE %s OR headline ILIKE %s)
           ORDER BY ts DESC LIMIT 10""",
        (f"%{base}%", f"%{base}%", f"%{first}%", f"%{first}%"))
    rows = cur.fetchall()
    if not rows:
        return "_No matching headlines in the last 3 days._\n", 0.0
    avg = sum(r[1] or 0 for r in rows) / len(rows)
    pos = max(rows, key=lambda r: r[1] or -9)
    neg = min(rows, key=lambda r: r[1] or 9)
    lines = [f"Recent sentiment (FinBERT, 3d): **{avg:+.2f}** over {len(rows)} "
             f"headlines.\n"]
    lines.append(f"- Most positive ({pos[1]:+.2f}): {str(pos[0])[:140]}")
    lines.append(f"- Most negative ({neg[1]:+.2f}): {str(neg[0])[:140]}\n")
    return "\n".join(lines), avg


def render_report(cur, row, medians):
    (sym, rank, comp, vs, qs, gs, ms, rs, cov, name) = row
    med_v, med_q, med_c = medians
    cur.execute("SELECT metric, value FROM stock_metrics_daily WHERE symbol=%s "
                "ORDER BY ts DESC LIMIT 20", (sym,))
    mets, seen = {}, set()
    for metric, val in cur.fetchall():
        if metric not in seen:
            mets[metric] = val
            seen.add(metric)
    # flow metrics: full-year (yfinance) rows only — EDGAR 10-Q rows are YTD (DQ-2)
    cur.execute("SELECT DISTINCT ON (metric) metric, value FROM stock_fundamentals "
                "WHERE symbol=%s AND (source='yfinance' OR metric NOT IN "
                "('total_revenue','net_income','operating_income','eps','fcf')) "
                "ORDER BY metric, ts DESC", (sym,))
    fund = dict(cur.fetchall())
    # ADR 0026: deterministic fair value + the sector lens (schemas 15/16).
    cur.execute("SELECT fair_value, upside_pct, methods, graham, peer_multiple, "
                "fcf_yield, dcf, ddm, epv, residual_income, peg_lynch "
                "FROM stock_valuations WHERE symbol=%s "
                "AND ts >= now() - interval '7 days' ORDER BY ts DESC LIMIT 1", (sym,))
    val = cur.fetchone()
    cur.execute("SELECT c.sector, coalesce(st.style,'default'), st.note "
                "FROM universe_constituents c LEFT JOIN sector_styles st "
                "ON st.sector = c.sector WHERE c.symbol=%s LIMIT 1", (sym,))
    sec = cur.fetchone() or (None, "default", None)
    cur.execute("SELECT metric, weight, note FROM metric_relevance WHERE style=%s "
                "ORDER BY weight DESC, metric", (sec[1],))
    rel = cur.fetchall()
    nb, sent = news_block(cur, sym, name)
    md = []
    md.append(f"# {name} ({sym}) — shortlist\n")
    if sec[0]:
        md.append(f"Sector: **{sec[0]}**" + (f" — _{sec[2]}_" if sec[2] else ""))
    md.append(f"**Rank {rank}** · composite **{fmt(comp)}** "
              f"(universe median {fmt(med_c)}) · coverage {int((cov or 0) * 100)}%")
    md.append(f"Factors: value {fmt(vs)} (med {fmt(med_v)}) · quality {fmt(qs)} "
              f"(med {fmt(med_q)}) · growth {fmt(gs)} · momentum {fmt(ms)} · "
              f"risk {fmt(rs)}\n")
    md.append("## Valuation")
    md.append(f"- P/E {fmt(fund.get('pe'))} · P/B {fmt(fund.get('pb'))} · "
              f"EV/EBITDA {fmt(fund.get('ev_ebitda'))}")
    mcap = fund.get("market_cap")
    md.append(f"- Market cap: {fmt(mcap / 1e9, suffix='B') if mcap else 'n/a'}")
    if val and val[0]:
        md.append(f"- **Fair value {fmt(val[0])}** ({val[1]:+.0f}% vs close, "
                  f"median of {val[2]} methods — ADR 0026, not advice)")
        names = ("Graham", "Peer multiple", "FCF yield", "DCF", "DDM", "EPV",
                 "Residual income", "PEG")
        md.append("- Methods: " + " · ".join(
            f"{n} {fmt(v)}" for n, v in zip(names, val[3:]) if v))
    if rel:
        md.append("## What matters in this sector")
        for metric, weight, note in rel:
            if weight >= 3:
                md.append(f"- **{metric}**: {note}")
        for metric, weight, note in rel:
            if weight == 0:
                md.append(f"- ~~{metric}~~ (misleading here): {note}")
    md.append("## Quality & growth")
    md.append(f"- ROE {fmt(fund.get('roe'))} · operating margin "
              f"{fmt(fund.get('operating_margin'))}")
    md.append("## Price")
    md.append(f"- Close {fmt(mets.get('close'))} · 6m return {fmt(mets.get('ret_6m'))} "
              f"· 12m return {fmt(mets.get('ret_12m'))}")
    md.append(f"- 52w position {fmt(mets.get('pos_52w'))} · ann. vol "
              f"{fmt(mets.get('vol_180d'))} · max drawdown (1y) "
              f"{fmt(mets.get('max_dd_252d'))}")
    md.append("## News (AI: FinBERT)")
    md.append(nb)
    md.append("---\n_Research/screening output — not investment advice. Data as "
              "ingested; verify before acting._")
    return "\n".join(md), sent


def main() -> int:
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0,
                                                microsecond=0)
    conn = connect()
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT universe FROM stock_scores ORDER BY 1")
        universes = [r[0] for r in cur.fetchall()]
    n_reports, digest_lines = 0, []
    for universe in universes:
        with conn.cursor() as cur:
            # v8: restrict to each symbol's LATEST scores row (= today's run).
            # Scores carry the per-symbol metric ts, which can differ across
            # symbols (stale/fresh bars), so max(ts) alone misses rows; the old
            # unfiltered query unioned every historical top-25 (51 reports
            # instead of 25 per universe). DISTINCT ON gives the current run.
            cur.execute(
                """WITH latest AS (
                       SELECT DISTINCT ON (symbol) s.*
                       FROM stock_scores s WHERE s.universe=%s
                       ORDER BY s.symbol, s.ts DESC)
                   SELECT l.symbol, l.rank, l.composite, l.value_score,
                          l.quality_score, l.growth_score, l.momentum_score,
                          l.risk_score, l.coverage,
                          coalesce(c.name, l.symbol) AS name
                   FROM latest l
                   LEFT JOIN universe_constituents c
                     ON c.symbol = l.symbol AND c.universe = l.universe
                   WHERE l.rank IS NOT NULL AND l.rank <= %s
                   ORDER BY l.rank""", (universe, SHORTLIST))
            shortlist = cur.fetchall()
        if not shortlist:
            print(f"{universe}: no shortlist rows", flush=True)
            continue
        with conn.cursor() as cur:
            cur.execute(
                """SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY value_score),
                          percentile_cont(0.5) WITHIN GROUP (ORDER BY quality_score),
                          percentile_cont(0.5) WITHIN GROUP (ORDER BY composite)
                   FROM (SELECT DISTINCT ON (symbol) s.*
                         FROM stock_scores s WHERE s.universe=%s
                         ORDER BY s.symbol, s.ts DESC) l""",
                (universe,))
            medians = cur.fetchone()
        print(f"{universe}: {len(shortlist)} shortlisted", flush=True)
        for row in shortlist:
            sym = row[0]
            try:
                with conn.cursor() as cur:
                    report, _ = render_report(cur, row, medians)
                with conn.transaction():
                    with conn.cursor() as cur:
                        cur.execute("DELETE FROM stock_reports WHERE symbol=%s AND ts=%s",
                                    (sym, today))
                        cur.execute("INSERT INTO stock_reports (symbol, ts, report_md) "
                                    "VALUES (%s,%s,%s)", (sym, today, report))
                n_reports += 1
                digest_lines.append(f"| {universe} | {row[1]} | {row[9]} ({sym}) | "
                                    f"{fmt(row[2])} | V {fmt(row[3])} "
                                    f"Q {fmt(row[4])} |")
                print(f"  report ok: {sym} (rank {row[1]})", flush=True)
            except psycopg.OperationalError as exc:
                print(f"WARN {sym} conn dropped ({exc}); reconnecting, retrying",
                      flush=True)
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass
                conn = connect()
                try:
                    with conn.cursor() as cur:
                        report, _ = render_report(cur, row, medians)
                    with conn.transaction():
                        with conn.cursor() as cur:
                            cur.execute("DELETE FROM stock_reports WHERE symbol=%s "
                                        "AND ts=%s", (sym, today))
                            cur.execute("INSERT INTO stock_reports (symbol, ts, "
                                        "report_md) VALUES (%s,%s,%s)",
                                        (sym, today, report))
                    n_reports += 1
                    print(f"  report ok after retry: {sym}", flush=True)
                except Exception as exc2:  # noqa: BLE001
                    print(f"WARN {sym} failed after reconnect: {exc2}", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"WARN {sym} failed: {exc}", flush=True)
    if digest_lines:
        digest = ("# Daily shortlist digest — " + today.strftime("%Y-%m-%d")
                  + "\n\n| Universe | Rank | Stock | Composite | Factors |\n"
                  "|---|---|---|---|---|\n" + "\n".join(digest_lines))
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("DELETE FROM stock_reports WHERE symbol='__digest__' "
                            "AND ts=%s", (today,))
                cur.execute("INSERT INTO stock_reports (symbol, ts, report_md) "
                            "VALUES ('__digest__', %s, %s)", (today, digest))
    # Sector analysis per universe (ADR 0026): today's sector_metrics rendered
    # as one '__sectors__' report row, sorted cheapest-by-median-upside first.
    with conn.cursor() as cur:
        cur.execute(
            """SELECT m.universe, m.sector, m.members, m.median_pe, m.median_pb,
                      m.median_ev_ebitda, m.avg_ret_6m, m.avg_ret_12m,
                      m.median_upside_pct, st.style, st.note
               FROM sector_metrics m LEFT JOIN sector_styles st USING (sector)
               WHERE m.ts >= now() - interval '7 days'
                 AND m.ts = (SELECT max(ts) FROM sector_metrics
                             WHERE ts >= now() - interval '7 days')
               ORDER BY m.universe, m.median_upside_pct DESC NULLS LAST""")
        sector_rows = cur.fetchall()
    if sector_rows:
        md = ["# Sector analysis — " + today.strftime("%Y-%m-%d"),
              "", "_Medians over members; upside = median of each member's "
              "fair-value gap (ADR 0026). Not advice._", ""]
        last_u = None
        for (u, sector, n, pe, pb, ev, r6, r12, up, _style, note) in sector_rows:
            if u != last_u:
                md += [f"## {u}", "", "| Sector | n | P/E | P/B | EV/EBITDA | "
                       "6m | 12m | Upside | Lens |", "|---|---|---|---|---|---|---|---|---|"]
                last_u = u
            md.append(f"| {sector} | {n} | {fmt(pe)} | {fmt(pb)} | {fmt(ev)} | "
                      f"{fmt(r6)} | {fmt(r12)} | "
                      f"{f'{up:+.0f}%' if up is not None else 'n/a'} | "
                      f"{note or ''} |")
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("DELETE FROM stock_reports WHERE symbol='__sectors__' "
                            "AND ts=%s", (today,))
                cur.execute("INSERT INTO stock_reports (symbol, ts, report_md) "
                            "VALUES ('__sectors__', %s, %s)", (today, "\n".join(md)))
        print(f"sector analysis: {len(sector_rows)} sector rows", flush=True)
    conn.close()
    print(f"REPORT-OK reports={n_reports} digest={'yes' if digest_lines else 'no'}",
          flush=True)
    return 0 if n_reports else 1


if __name__ == "__main__":
    sys.exit(main())
