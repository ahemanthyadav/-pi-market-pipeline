"""Deterministic intrinsic-value estimates for EVERY active symbol (ADR 0026).

The famous methods, each stored per stock per day in stock_valuations and NULL
whenever its inputs don't apply — no method is forced:
- graham:          sqrt(22.5 * EPS * BVPS) (Graham's 15 P/E x 1.5 P/B bound)
- peer_multiple:   sector-median P/E x EPS; for styles where metric_relevance
                   (schema 16) marks P/E misleading and P/B primary
                   (financials, real estate, commodities) it is median P/B x BVPS
- fcf_yield:       FCF/share / r — zero-growth perpetuity
- dcf:             two-stage FCF DCF — 5 years at the revenue CAGR clamped to
                   [0%, 15%], terminal growth 2.5%
- ddm:             Gordon growth on dividends/share (payers with >=3 years)
- epv:             Greenwald earnings-power value — normalized EBIT (mean of
                   up to 5 annual operating_income) x (1 - 25% tax) / r, minus
                   total debt, per share. NO cash credit (cash isn't ingested),
                   so it leans conservative — pinned in ADR 0026
- residual_income: justified P/B — (ROE - g)/(r - g) x BVPS when ROE > r,
                   multiple capped at 8
- peg_lynch:       PEG = 1 fair value — EPS x 100 x EPS CAGR clamped [5%, 25%]
- damodaran_fcff:  Damodaran two-stage FCFF (ADR 0030): NOPAT with fundamental
                   growth (reinvestment = g/ROC, ROC on book capital), 5y at
                   the revenue CAGR then terminal 2.5%, discounted at WACC
                   (ke = 10y + ERP; kd = 10y + 2% after 25% tax, market-value
                   weights); debt netted, no cash credit (as EPV)
- graham_growth:   Graham's revised 1974 formula EPS x (8.5 + 2g%) x 4.4/Y,
                   g = EPS CAGR clamped [0, 15%], Y = 10y + 1% (AAA proxy)
fair_value = median of whatever produced a number; methods = how many did.

Sector lens comes from sector_styles + metric_relevance (schema 16); annual
histories from financial_facts (EV-9 lines included); shares are implied
(market_cap / close) until shares_outstanding coverage completes. Also writes
the daily sector_metrics aggregates (schema 17) in the same transaction.

DESCRIPTIVE ONLY: nothing here feeds stock_scores/composite without an EV-0
pass (ADR 0026). r = latest 10y (DGS10 / IN_GS_10Y) + 4.5% ERP.

Env: PGHOST, PGUSER, PGPASSWORD, PGDATABASE. OK-marker: VALUATION-OK.
"""

import statistics
import sys
from datetime import datetime, timezone

from mdjob import connect, job_run

ERP = 4.5                                   # equity risk premium, percent
TERMINAL_G = 0.025                          # terminal growth, decimal
TAX = 0.25                                  # EPV normalized tax rate
DCF_YEARS = 5
JPB_CAP = 8.0                               # residual-income multiple cap
DEBT_SPREAD = 0.02                          # synthetic cost-of-debt spread over rf (ADR 0030)
AAA_SPREAD = 1.0                            # AAA-corporate proxy over the 10y, percent (Graham Y)
RR_CAP = 0.9                                # reinvestment-rate ceiling (Damodaran FCFF)
# Rates are per MARKET, not per universe (ADR 0029: five universes, two markets).
FALLBACK_10Y = {"US": 4.5, "IN": 7.0}
TENOR = {"US": "DGS10", "IN": "IN_GS_10Y"}


def market(universe):
    return "IN" if universe.startswith("NIFTY") else "US"
HIST_METRICS = ("total_revenue", "eps", "dividends_paid", "ocf", "capex",
                "operating_income", "fcf")


def discount_rates(cur):
    """{market: decimal rate} from the latest 10y print (rule-9 bounded)."""
    out = {}
    for universe, instrument in TENOR.items():
        cur.execute("SELECT yield FROM bond_yields WHERE instrument=%s "
                    "AND ts >= now() - interval '45 days' ORDER BY ts DESC LIMIT 1",
                    (instrument,))
        row = cur.fetchone()
        tenor = row[0] if row else FALLBACK_10Y[universe]
        if not row:
            print(f"WARN {universe}: no fresh {instrument} — fallback "
                  f"{FALLBACK_10Y[universe]}%", flush=True)
        out[universe] = (tenor + ERP) / 100.0
    return out


def style_weights(cur):
    """({sector: style}, {(style, metric): weight})."""
    cur.execute("SELECT sector, style FROM sector_styles")
    styles = dict(cur.fetchall())
    cur.execute("SELECT style, metric, weight FROM metric_relevance")
    weights = {(s, m): w for s, m, w in cur.fetchall()}
    return styles, weights


def load_inputs(cur):
    """{symbol: {...latest snapshot inputs...}} in three bulk queries."""
    cur.execute("SELECT symbol, universe, coalesce(sector,'_default') "
                "FROM universe_constituents WHERE active")
    data = {s: {"universe": u, "sector": sec} for s, u, sec in cur.fetchall()}
    cur.execute("SELECT DISTINCT ON (symbol) symbol, close FROM stock_prices "
                "WHERE ts >= now() - interval '14 days' AND close > 0 "
                "ORDER BY symbol, ts DESC")
    for symbol, close in cur.fetchall():
        if symbol in data:
            data[symbol]["close"] = close
    cur.execute("SELECT DISTINCT ON (symbol, metric) symbol, metric, value "
                "FROM stock_fundamentals WHERE ts >= now() - interval '500 days' "
                "AND metric IN ('eps','shareholder_equity','fcf','market_cap','pe','pb',"
                "'ev_ebitda','roe','operating_margin','total_debt') "
                "AND (source='yfinance' OR metric NOT IN ('eps','fcf')) "
                "ORDER BY symbol, metric, ts DESC")
    for symbol, metric, value in cur.fetchall():
        if symbol in data:
            data[symbol][metric] = value
    cur.execute("SELECT DISTINCT ON (symbol, metric) symbol, metric, value "
                "FROM stock_metrics_daily WHERE ts >= now() - interval '14 days' "
                "AND metric IN ('ret_6m','ret_12m') ORDER BY symbol, metric, ts DESC")
    for symbol, metric, value in cur.fetchall():
        if symbol in data:
            data[symbol][metric] = value
    return data


def load_history(cur):
    """{symbol: {metric: [(period_end, value) ascending]}} — ANNUAL rows only,
    first-filed value per period (financial_facts is point-in-time, DQ-2)."""
    cur.execute("SELECT DISTINCT ON (symbol, metric, period_end) "
                "symbol, metric, period_end, value FROM financial_facts "
                "WHERE metric = ANY(%s) AND duration_days BETWEEN 300 AND 400 "
                "ORDER BY symbol, metric, period_end, filed DESC",
                (list(HIST_METRICS),))
    hist = {}
    for symbol, metric, end, value in cur.fetchall():
        hist.setdefault(symbol, {}).setdefault(metric, []).append((end, value))
    for metrics in hist.values():
        for series in metrics.values():
            series.sort()
    return hist


def cagr(series, min_periods=3):
    """Compound annual growth between the first and last positive values."""
    pts = [(d, v) for d, v in series if isinstance(v, (int, float)) and v > 0]
    if len(pts) < min_periods:
        return None
    (d0, v0), (d1, v1) = pts[0], pts[-1]
    years = (d1 - d0).days / 365.25
    if years < 1:
        return None
    return (v1 / v0) ** (1 / years) - 1


def clamp(v, lo, hi):
    return None if v is None else max(lo, min(hi, v))


def latest_annual(hist_m):
    """Last annual value of a series, or None."""
    return hist_m[-1][1] if hist_m else None


def latest_fcf(hist, snap):
    """Annual FCF: EDGAR ocf-capex for the latest shared period; else the fcf
    series (Yahoo leg); else the stock_fundamentals snapshot value."""
    ocf = dict(hist.get("ocf", []))
    capex = dict(hist.get("capex", []))
    shared = sorted(set(ocf) & set(capex))
    if shared:
        end = shared[-1]
        return ocf[end] - capex[end]
    fcf = latest_annual(hist.get("fcf", []))
    return fcf if fcf is not None else snap.get("fcf")


MEDIAN_METRICS = ("pe", "pb", "ev_ebitda", "roe", "operating_margin")
MEDIAN_CAP = {"pe": 200, "pb": 200, "ev_ebitda": 200, "roe": 5, "operating_margin": 1}


MEDIAN_MIN_N = 5   # a "sector median" over fewer inputs is noise, not a view


def sector_medians(data):
    """{(universe, sector): {metric: median}} over sane positive values;
    a metric with fewer than MEDIAN_MIN_N inputs stays absent (2026-10-27:
    one thin SP400 name printed as 'Materials P/E 7.2, +209%')."""
    buckets = {}
    for d in data.values():
        key = (d["universe"], d["sector"])
        for m in MEDIAN_METRICS:
            v = d.get(m)
            if isinstance(v, (int, float)) and 0 < v < MEDIAN_CAP[m]:
                buckets.setdefault(key, {}).setdefault(m, []).append(v)
    return {key: {m: statistics.median(vs) for m, vs in ms.items()
                  if len(vs) >= MEDIAN_MIN_N}
            for key, ms in buckets.items()}


def value_one(d, hist, medians, styles, weights, rates):
    """Dict of method values + fair/upside/growth, or None without a close."""
    close = d.get("close")
    if not close:
        return None
    style = styles.get(d["sector"], "default")
    w = lambda metric: weights.get((style, metric), weights.get(("default", metric), 2))  # noqa: E731
    r = rates[market(d["universe"])]
    med = medians.get((d["universe"], d["sector"]), {})

    mcap, eps, equity = d.get("market_cap"), d.get("eps"), d.get("shareholder_equity")
    shares = mcap / close if mcap and mcap > 0 else None
    bvps = equity / shares if shares and equity and equity > 0 else None

    out = {"discount_rate": r, "growth_used": None}
    out["graham"] = ((22.5 * eps * bvps) ** 0.5
                     if eps and eps > 0 and bvps and bvps > 0 else None)
    if w("pe") <= 1 and w("pb") >= 3:
        out["peer_multiple"] = med.get("pb") * bvps if med.get("pb") and bvps else None
    else:
        out["peer_multiple"] = (med.get("pe") * eps
                                if med.get("pe") and eps and eps > 0 else None)

    fcf0 = latest_fcf(hist, d)
    fcf_ok = fcf0 and fcf0 > 0 and shares and w("fcf") > 0
    out["fcf_yield"] = fcf0 / shares / r if fcf_ok else None

    g = clamp(cagr(hist.get("total_revenue", [])), 0.0, 0.15)
    if fcf_ok and g is not None:
        out["growth_used"] = g
        pv, f = 0.0, fcf0
        for t in range(1, DCF_YEARS + 1):
            f *= 1 + g
            pv += f / (1 + r) ** t
        pv += (f * (1 + TERMINAL_G) / (r - TERMINAL_G)) / (1 + r) ** DCF_YEARS
        out["dcf"] = pv / shares
    else:
        out["dcf"] = None

    divs = hist.get("dividends_paid", [])
    d0 = latest_annual(divs)
    gd = clamp(cagr(divs), 0.0, min(0.08, r - 0.01))
    out["ddm"] = (d0 / shares * (1 + gd) / (r - gd)
                  if d0 and d0 > 0 and shares and gd is not None else None)

    ebits = [v for _e, v in hist.get("operating_income", [])[-5:]
             if isinstance(v, (int, float))]
    if ebits and shares:
        epv_equity = (statistics.mean(ebits) * (1 - TAX) / r) - (d.get("total_debt") or 0)
        out["epv"] = epv_equity / shares if epv_equity > 0 else None
    else:
        out["epv"] = None

    roe = d.get("roe")
    if roe and bvps and roe > r:
        jpb = min((roe - TERMINAL_G) / (r - TERMINAL_G), JPB_CAP)
        out["residual_income"] = jpb * bvps
    else:
        out["residual_income"] = None

    ge = clamp(cagr(hist.get("eps", [])), 0.05, 0.25)
    out["peg_lynch"] = (eps * ge * 100
                        if eps and eps > 0 and ge is not None else None)

    # Damodaran FCFF (ADR 0030): fundamental growth — reinvestment = g/ROC —
    # NOPAT-based firm value at WACC, debt netted (no cash credit, like EPV).
    out["damodaran_fcff"] = None
    ebit0 = latest_annual(hist.get("operating_income", []))
    debt = d.get("total_debt") or 0
    if (ebit0 and ebit0 > 0 and shares and mcap and equity and equity > 0
            and g is not None):
        nopat = ebit0 * (1 - TAX)
        roc = nopat / (debt + equity)
        rf = r - ERP / 100.0
        kd = (rf + DEBT_SPREAD) * (1 - TAX)
        wacc = (mcap * r + debt * kd) / (mcap + debt)
        if roc > TERMINAL_G and wacc > TERMINAL_G:
            rr = clamp(g / roc, 0.0, RR_CAP)
            pv, n = 0.0, nopat
            for t in range(1, DCF_YEARS + 1):
                n *= 1 + g
                pv += n * (1 - rr) / (1 + wacc) ** t
            rr_t = clamp(TERMINAL_G / roc, 0.0, RR_CAP)
            tv = n * (1 + TERMINAL_G) * (1 - rr_t) / (wacc - TERMINAL_G)
            pv += tv / (1 + wacc) ** DCF_YEARS
            eq_value = pv - debt
            out["damodaran_fcff"] = eq_value / shares if eq_value > 0 else None

    # Graham's revised growth formula (1974): V = EPS x (8.5 + 2g%) x 4.4 / Y,
    # Y = AAA corporate yield, proxied as the 10y + AAA_SPREAD (ADR 0030).
    gg = clamp(cagr(hist.get("eps", [])), 0.0, 0.15)
    y_pct = (r - ERP / 100.0) * 100 + AAA_SPREAD
    out["graham_growth"] = (eps * (8.5 + 2 * gg * 100) * 4.4 / y_pct
                            if eps and eps > 0 and gg is not None and y_pct > 0
                            else None)

    methods = [v for k, v in out.items()
               if k not in ("discount_rate", "growth_used") and v]
    out["methods"] = len(methods)
    out["fair_value"] = statistics.median(methods) if methods else None
    out["upside_pct"] = ((out["fair_value"] / close - 1) * 100
                         if out["fair_value"] else None)
    return out


def _mean(vals):
    vals = [v for v in vals if isinstance(v, (int, float))]
    return sum(vals) / len(vals) if vals else None


def sector_rows(data, medians, upsides, today):
    """sector_metrics rows: medians + equal-weighted returns + median upside."""
    groups = {}
    for symbol, d in data.items():
        groups.setdefault((d["universe"], d["sector"]), []).append(symbol)
    rows = []
    for (universe, sector), symbols in sorted(groups.items()):
        med = medians.get((universe, sector), {})
        ups = [upsides[s] for s in symbols if upsides.get(s) is not None]
        rows.append((universe, sector, today, len(symbols),
                     med.get("pe"), med.get("pb"), med.get("ev_ebitda"),
                     med.get("roe"), med.get("operating_margin"),
                     _mean(data[s].get("ret_6m") for s in symbols),
                     _mean(data[s].get("ret_12m") for s in symbols),
                     statistics.median(ups) if len(ups) >= MEDIAN_MIN_N else None))
    return rows


METHOD_COLS = ("graham", "peer_multiple", "fcf_yield", "dcf", "ddm", "epv",
               "residual_income", "peg_lynch", "damodaran_fcff", "graham_growth")


def main() -> int:
    with job_run("stock-valuation") as run:
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0,
                                                   microsecond=0)
        conn = connect()
        try:
            with conn.cursor() as cur:
                rates = discount_rates(cur)
                styles, weights = style_weights(cur)
                data = load_inputs(cur)
                hist = load_history(cur)
            medians = sector_medians(data)
            rows, skipped, upsides = [], 0, {}
            for symbol, d in sorted(data.items()):
                out = value_one(d, hist.get(symbol, {}), medians, styles,
                                weights, rates)
                if out is None:
                    skipped += 1
                    continue
                upsides[symbol] = out["upside_pct"]
                rows.append((symbol, today, d["universe"], d["close"],
                             *[out[c] for c in METHOD_COLS],
                             out["fair_value"], out["upside_pct"], out["methods"],
                             out["discount_rate"], out["growth_used"]))
            sectors = sector_rows(data, medians, upsides, today)
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM stock_valuations WHERE ts = %s", (today,))
                    cur.executemany(
                        "INSERT INTO stock_valuations (symbol, ts, universe, close, "
                        "graham, peer_multiple, fcf_yield, dcf, ddm, epv, "
                        "residual_income, peg_lynch, damodaran_fcff, graham_growth, "
                        "fair_value, upside_pct, methods, "
                        "discount_rate, growth_used) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
                        "%s,%s)",
                        rows)
                    cur.execute("DELETE FROM sector_metrics WHERE ts = %s", (today,))
                    cur.executemany(
                        "INSERT INTO sector_metrics (universe, sector, ts, members, "
                        "median_pe, median_pb, median_ev_ebitda, median_roe, "
                        "median_op_margin, avg_ret_6m, avg_ret_12m, median_upside_pct) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", sectors)
            run.rows = len(rows)
            valued = sum(1 for r in rows if r[12] is not None)
        finally:
            conn.close()
        print(f"VALUATION-OK {len(rows)} symbols ({valued} with a fair value, "
              f"{skipped} without a recent close) + {len(sectors)} sector rows",
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
