"""Price-derived daily metrics (Phase F, job 1 of 2).

Per active symbol, from the last 260 bars of stock_prices, computes the §6 metric
set and writes (metric, value) rows keyed to the symbol's latest bar date:
close, ret_1m, ret_6m, ret_12m, vol_180d, max_dd_252d, pos_52w, sma50_ratio,
sma200_ratio, dol_vol_20d. Missing window (new listing) → metric omitted.
"""
import os
import sys

import pandas as pd
import psycopg

BARS = 260


def pct_rank_scale(v):
    return v


def compute(df):
    """df indexed by ts ascending, columns [close, volume]. Returns {metric: val}."""
    out = {}
    c = df["close"]
    out["close"] = float(c.iloc[-1])
    for name, lag in (("ret_1m", 21), ("ret_6m", 126), ("ret_12m", 252)):
        if len(c) > lag and c.iloc[-1 - lag] and not pd.isna(c.iloc[-1 - lag]):
            out[name] = float(c.iloc[-1] / c.iloc[-1 - lag] - 1)
    ret = c.pct_change().dropna()
    if len(ret) >= 120:
        out["vol_180d"] = float(ret.tail(180).std() * (252 ** 0.5))
    if len(c) >= 60:
        w = c.tail(252)
        run_max = w.cummax()
        out["max_dd_252d"] = float((w / run_max - 1).min())
        lo, hi = float(w.min()), float(w.max())
        if hi > lo:
            out["pos_52w"] = (float(c.iloc[-1]) - lo) / (hi - lo)
    for name, n in (("sma50_ratio", 50), ("sma200_ratio", 200)):
        if len(c) >= n:
            out[name] = float(c.iloc[-1] / c.tail(n).mean())
    if len(df) >= 5 and "volume" in df:
        out["dol_vol_20d"] = float((df["close"] * df["volume"]).tail(20).mean())
    return out


def main() -> int:
    limit = int(os.environ.get("UNIVERSE_LIMIT", "0") or 0) or None
    conn = psycopg.connect(
        host=os.environ.get("PGHOST", "timescaledb.market-data.svc.cluster.local"),
        user=os.environ.get("PGUSER", "postgres"),
        password=os.environ["PGPASSWORD"],
        dbname=os.environ.get("PGDATABASE", "postgres"),
    )
    conn.autocommit = True  # no idle transaction across the symbol loop
    with conn.cursor() as cur:
        cur.execute("SELECT symbol FROM universe_constituents WHERE active ORDER BY 1")
        symbols = [r[0] for r in cur.fetchall()]
    if limit:
        symbols = symbols[:limit]
    computed, skipped, written = 0, 0, 0
    for sym in symbols:
        with conn.cursor() as cur:
            cur.execute("SELECT ts, close, volume FROM stock_prices WHERE symbol=%s "
                        "ORDER BY ts DESC LIMIT %s", (sym, BARS))
            rows = cur.fetchall()
        if len(rows) < 5:
            skipped += 1
            continue
        df = pd.DataFrame([(r[0], r[1], r[2]) for r in reversed(rows)],
                           columns=["ts", "close", "volume"]).set_index("ts")
        metrics = compute(df)
        if not metrics:
            skipped += 1
            continue
        ts = df.index[-1].to_pydatetime()
        try:
            with conn.transaction():
                with conn.cursor() as cur:
                    for metric, val in metrics.items():
                        cur.execute("DELETE FROM stock_metrics_daily WHERE symbol=%s "
                                    "AND ts=%s AND metric=%s", (sym, ts, metric))
                        cur.execute("INSERT INTO stock_metrics_daily (symbol, ts, metric, value) "
                                    "VALUES (%s,%s,%s,%s)", (sym, ts, metric, val))
                        written += 1
            computed += 1
        except psycopg.OperationalError as exc:
            print(f"WARN {sym} conn dropped ({exc}); reconnecting, skipping sym", flush=True)
            skipped += 1
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
            conn = psycopg.connect(
                host=os.environ.get("PGHOST", "timescaledb.market-data.svc.cluster.local"),
                user=os.environ.get("PGUSER", "postgres"),
                password=os.environ["PGPASSWORD"],
                dbname=os.environ.get("PGDATABASE", "postgres"),
            )
            conn.autocommit = True
    conn.close()
    print(f"METRICS-OK computed={computed} skipped={skipped} rows={written}", flush=True)
    return 0 if computed else 1


if __name__ == "__main__":
    sys.exit(main())
