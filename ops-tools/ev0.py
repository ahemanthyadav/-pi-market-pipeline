#!/usr/bin/env python3
"""EV-0 — signal test harness (evidence-based-signals-roadmap.md §5, written before testing).

Monthly rebalance. For each month-end and universe: cross-sectional Spearman IC between a
signal and the NEXT month's total return (from adj_close), quintile spread (Q5−Q1), turnover,
spread net of costs, Fama-MacBeth slope with the screener's other price inputs as controls.
Verdict per §5: (1) Newey-West IC t > 3; (2) same sign in both halves and both universes;
(3) net quintile spread > 0 at 0.2 % (US) / 0.4 % (India) per trade; (4) FM t > 2 with controls
— PARTIAL: price controls only (value/quality/growth history is not point-in-time for India yet).

Known bias, printed in every report: the universe is TODAY's constituents (survivorship) until
EV-1 historical membership exists; `universe_membership_snapshots` started 2026-10-18.

Usage (workstation; DB via a psql command in $PSQL_CMD, like audit-price-adjustments.py):
  PSQL_CMD='kubectl -n market-data exec -i timescaledb-0 -- env PGPASSWORD=… psql -U postgres -d postgres' \\
    uv run --with pandas --with pyarrow python ops-tools/ev0.py export   # -> out/ev0/prices.parquet
  uv run --with pandas --with pyarrow python ops-tools/ev0.py run       # -> out/ev0/report-<date>.md + .csv
"""
import argparse
import datetime as dt
import io
import os
import subprocess
import sys

import numpy as np
import pandas as pd

OUT = "out/ev0"
COST = {"SP500": 0.002, "NIFTY500": 0.004}          # per trade, §5 criterion 3
EXISTING = ["ret_6m", "ret_12m", "pos_52w", "sma200_ratio", "low_vol"]  # composite price inputs
NEW = ["ret_12_1", "near_high", "low_beta", "rev_1m"]                  # EV-3, EV-4, EV-5, reversal
MIN_NAMES = 50


# ---------------------------------------------------------------- export
def export(start):
    cmd = os.environ.get("PSQL_CMD")
    if not cmd:
        sys.exit("set PSQL_CMD (see module docstring)")
    # start is interpolated into SQL run as postgres — accept only a real ISO date
    start = str(dt.date.fromisoformat(str(start)))
    sql = ("COPY (SELECT p.symbol, p.ts::date AS d, p.close, p.adj_close, p.volume, u.universe "
           "FROM stock_prices p JOIN universe_constituents u USING (symbol) "
           f"WHERE p.ts >= '{start}' ORDER BY 1, 2) TO STDOUT WITH CSV HEADER")
    raw = subprocess.run(cmd + " -v ON_ERROR_STOP=1 -c " + _q(sql), shell=True, check=True,
                         capture_output=True).stdout
    df = pd.read_csv(io.BytesIO(raw), parse_dates=["d"])
    os.makedirs(OUT, exist_ok=True)
    df.to_parquet(f"{OUT}/prices.parquet", index=False)
    print(f"exported {len(df)} rows, {df.symbol.nunique()} symbols, {df.d.min().date()}..{df.d.max().date()}")


def _q(s):
    return "'" + s.replace("'", "'\"'\"'") + "'"


# ---------------------------------------------------------------- signals
def signals(px, vol, close):
    """Daily panels (date x symbol) -> {name: panel}. px = the series signals are built on."""
    r = px.pct_change(fill_method=None)
    mkt = r.mean(axis=1)
    hi, lo = px.rolling(252, min_periods=200).max(), px.rolling(252, min_periods=200).min()
    cov = r.rolling(252, min_periods=200).cov(mkt)
    beta = cov.div(mkt.rolling(252, min_periods=200).var(), axis=0)
    return {
        "ret_6m": px / px.shift(126) - 1,
        "ret_12m": px / px.shift(252) - 1,
        "ret_12_1": px.shift(21) / px.shift(252) - 1,
        "near_high": px / hi,
        "pos_52w": (px - lo) / (hi - lo),
        "sma200_ratio": px / px.rolling(200, min_periods=180).mean(),
        "low_vol": -r.rolling(252, min_periods=200).std(),
        "low_beta": -beta,
        "rev_1m": -(px / px.shift(21) - 1),
        "_liq": (close * vol).rolling(63, min_periods=40).median(),
    }


def month_ends(index):
    s = pd.Series(index, index=index)
    return pd.DatetimeIndex(s.groupby(index.to_period("M")).max().values)


# ---------------------------------------------------------------- statistics
def nw_t(x, lag=6):
    """Newey-West t-statistic of the mean (Bartlett kernel)."""
    x = np.asarray(pd.Series(x).dropna(), float)
    n = len(x)
    if n < 12:
        return np.nan
    m, d = x.mean(), x - x.mean()
    s = d @ d / n
    for k in range(1, min(lag, n - 1) + 1):
        s += 2 * (1 - k / (lag + 1)) * (d[k:] @ d[:-k]) / n
    return m / np.sqrt(s / n) if s > 0 else np.nan


def rank(s):
    return s.rank(pct=True)


def evaluate(sig_me, fwd_me, liq_me, controls_me, cost):
    """Per-month IC / quintile spread / turnover / FM slope for one signal in one universe."""
    rows, prev_long, prev_short = [], None, None
    for t in sig_me.index:
        s, f, liq = sig_me.loc[t], fwd_me.loc[t], liq_me.loc[t]
        ok = s.notna() & f.notna() & liq.notna() & (liq >= liq.quantile(0.2))
        if ok.sum() < MIN_NAMES:
            continue
        s, f = s[ok], f[ok]
        ic = rank(s).corr(rank(f))
        q = pd.qcut(s.rank(method="first"), 5, labels=False)
        long_, short = set(s.index[q == 4]), set(s.index[q == 0])
        spread = f[q == 4].mean() - f[q == 0].mean()
        to_l = 1.0 if prev_long is None else 1 - len(long_ & prev_long) / max(len(long_), 1)
        to_s = 1.0 if prev_short is None else 1 - len(short & prev_short) / max(len(short), 1)
        prev_long, prev_short = long_, short
        fm = np.nan
        X = pd.DataFrame({"sig": rank(s)})
        for c, panel in controls_me.items():
            X[c] = rank(panel.loc[t][ok])
        X = X.dropna()
        if len(X) >= MIN_NAMES:
            y = rank(f.loc[X.index]).values - 0.5
            A = np.column_stack([np.ones(len(X)), X.values - 0.5])
            coef, *_ = np.linalg.lstsq(A, y, rcond=None)
            fm = coef[1]
        rows.append({"t": t, "n": int(ok.sum()), "ic": ic, "spread": spread,
                     "net": spread - cost * 2 * (to_l + to_s), "turnover": (to_l + to_s) / 2,
                     "fm": fm})
    return pd.DataFrame(rows).set_index("t") if rows else pd.DataFrame()


def summarize(m):
    if m.empty:
        return {}
    half = len(m) // 2
    return {"months": len(m), "start": m.index.min().date(), "names": int(m.n.median()),
            "ic_mean": m.ic.mean(), "ic_t_nw": nw_t(m.ic), "ic_h1": m.ic.iloc[:half].mean(),
            "ic_h2": m.ic.iloc[half:].mean(), "spread_ann": m.spread.mean() * 12,
            "net_ann": m.net.mean() * 12, "turnover": m.turnover.mean(), "fm_t_nw": nw_t(m.fm)}


def verdict(per_uni):
    """§5 criteria 1-4 across universes. per_uni: {universe: summary}."""
    s = [v for v in per_uni.values() if v]
    if not s:
        return "NO DATA", {}
    signs = {np.sign(v[k]) for v in s for k in ("ic_h1", "ic_h2")}
    c = {"1 t>3": all(abs(v["ic_t_nw"]) > 3 for v in s),
         "2 same sign": len(signs) == 1,
         "3 net>0": all(v["net_ann"] * np.sign(v["ic_mean"]) > 0 for v in s),
         "4 FM t>2 (price controls)": all(abs(v["fm_t_nw"]) > 2 for v in s)}
    return ("PASS" if all(c.values()) else "FAIL"), c


# ---------------------------------------------------------------- run
def run(price_cols, start):
    df = pd.read_parquet(f"{OUT}/prices.parquet")
    df = df[df.d >= pd.Timestamp(start) - pd.Timedelta(days=400)]
    results, table = {}, []
    for price_col in price_cols:
        for uni, g in df.groupby("universe"):
            wide = {c: g.pivot(index="d", columns="symbol", values=c).sort_index()
                    for c in ("close", "adj_close", "volume")}
            tr = wide["adj_close"].fillna(wide["close"]).ffill(limit=5)
            px = wide[price_col].fillna(wide["close"]).ffill(limit=5) if price_col == "adj_close" \
                else wide["close"].ffill(limit=5)
            sig = signals(px, wide["volume"], wide["close"])
            me = month_ends(px.index)
            me = me[me >= pd.Timestamp(start)]
            fwd = (tr.loc[me].shift(-1) / tr.loc[me] - 1)
            liq = sig["_liq"].loc[me]
            for name in EXISTING + NEW:
                ctrl = {c: sig[c].loc[me] for c in EXISTING if c != name}
                m = evaluate(sig[name].loc[me], fwd, liq, ctrl, COST.get(uni, 0.003))
                sm = summarize(m)
                results.setdefault((price_col, name), {})[uni] = sm
                if sm:
                    table.append({"price": price_col, "signal": name, "universe": uni, **sm})
    return results, pd.DataFrame(table)


def report(results, table, start):
    today = dt.date.today().isoformat()
    os.makedirs(OUT, exist_ok=True)
    table.to_csv(f"{OUT}/ev0-{today}.csv", index=False)
    L = [f"# EV-0 report — {today}", "",
         f"Monthly rebalance from {start}; forward return = next month's total return (adj_close). "
         "Liquidity: 63-day median dollar volume ≥ the month's 20th percentile. "
         f"Costs per trade: {COST}.", "",
         "> **Survivorship bias:** universe = today's constituents (no EV-1 yet). Results for "
         "price signals are biased toward winners; treat a PASS as necessary, not sufficient.",
         "> Criterion 4 uses price controls only (the other composite price inputs).", "",
         "| price | signal | verdict | universe | months | IC | NW t | IC 1st/2nd half | Q5−Q1 /yr | net /yr | turnover | FM t |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for (price_col, name), per in results.items():
        v, crit = verdict(per)
        for uni, s in per.items():
            if not s:
                continue
            L.append(f"| {price_col} | {name} | **{v}** | {uni} | {s['months']} | {s['ic_mean']:.3f} | "
                     f"{s['ic_t_nw']:.1f} | {s['ic_h1']:.3f}/{s['ic_h2']:.3f} | {s['spread_ann']:.1%} | "
                     f"{s['net_ann']:.1%} | {s['turnover']:.0%} | {s['fm_t_nw']:.1f} |")
        if crit:
            L.append(f"| | | {' · '.join(k + (' ✓' if ok else ' ✗') for k, ok in crit.items())} | | | | | | | | | |")
    path = f"{OUT}/report-{today}.md"
    open(path, "w").write("\n".join(L) + "\n")
    print(path)
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--start", default="1999-01-01")
    r = sub.add_parser("run")
    r.add_argument("--start", default="2001-01-01")
    r.add_argument("--price", nargs="+", default=["adj_close", "close"])
    a = ap.parse_args()
    if a.cmd == "export":
        export(a.start)
    else:
        res, tab = run(a.price, a.start)
        report(res, tab, a.start)


if __name__ == "__main__":
    main()
