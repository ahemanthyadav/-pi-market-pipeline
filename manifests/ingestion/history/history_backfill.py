"""One-shot history backfills H-1..H-5 (2026-10-19, tracker "History backfills"). NOT baked into an image:
the script is mounted from ConfigMap `history-backfill` and each MODE runs on the image that already has its
libraries (manifests/ingestion/history/jobs.yaml).

  MODE=fx       H-1  10 FX pairs, Yahoo daily closes            (fx-fetcher:v1)    -> fx_rates
  MODE=yields   H-2  ^TNX ^FVX ^TYX ^IRX, Yahoo daily closes     (fx-fetcher:v1)    -> bond_yields
  MODE=fred     H-3  DFF -> interest_rates; DGS2/10/30 -> bond_yields, FRED       (rates-fetcher:v1)
  MODE=ta       H-4  RSI/MACD/SMA/Bollinger over all of index_prices            (ta-compute:v1)
  MODE=metrics  H-5  the 10 screener price metrics, WEEKLY (last bar of each week), last YEARS (5) years,
                     with the live stock_metrics.compute() itself                 (screener:v15)

Rules: only dates BEFORE each series' first existing row are written, so live rows are never touched;
idempotent (DELETE of that pre-live range, then INSERT/COPY); ts = 00:00 UTC of the trade/observation date,
like every live writer. Every read of a hypertable is time-bounded (AGENTS rule 9).
Env: PG*, MODE, FRED_API_KEY (fred), YEARS (metrics, 5), START (fx/yields, 1990-01-01).
"""
import importlib.util
import os
import sys
from datetime import datetime, timezone

import pandas as pd
import psycopg

FX = ["USDINR=X", "EURINR=X", "GBPINR=X", "JPYINR=X", "EURUSD=X",
      "GBPUSD=X", "USDJPY=X", "USDCNY=X", "USDCHF=X", "AUDUSD=X"]
YIELDS = ["^TNX", "^FVX", "^TYX", "^IRX"]
FRED = {"DFF": ("interest_rates", "rate_name", "value"),
        "DGS2": ("bond_yields", "instrument", "yield"),
        "DGS10": ("bond_yields", "instrument", "yield"),
        "DGS30": ("bond_yields", "instrument", "yield")}
EPOCH = "1950-01-01"


def connect():
    conn = psycopg.connect(host=os.environ.get("PGHOST", "timescaledb.market-data.svc.cluster.local"),
                           user=os.environ.get("PGUSER", "postgres"), password=os.environ["PGPASSWORD"],
                           dbname=os.environ.get("PGDATABASE", "postgres"))
    conn.autocommit = True
    return conn


def utc_midnight(ts):
    ts = pd.Timestamp(ts)
    return datetime(ts.year, ts.month, ts.day, tzinfo=timezone.utc)


def first_live(cur, table, key_col, key):
    cur.execute(f"SELECT min(ts) FROM {table} WHERE {key_col} = %s AND ts >= %s", (key, EPOCH))
    return cur.fetchone()[0]


def pre_live(points, first):
    """[(ts, value)] -> only finite values strictly before the first live date (pure)."""
    out = []
    for ts, v in points:
        if v is None or pd.isna(v):
            continue
        t = utc_midnight(ts)
        if first is None or t < utc_midnight(first):
            out.append((t, float(v)))
    return out


def write_series(conn, table, key_col, val_col, key, rows, first):
    if not rows:
        return 0
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {table} WHERE {key_col} = %s AND ts >= %s AND ts < %s",
                        (key, rows[0][0], first or datetime(2100, 1, 1, tzinfo=timezone.utc)))
            with cur.copy(f"COPY {table} ({key_col}, ts, {val_col}) FROM STDIN") as cp:
                for ts, v in rows:
                    cp.write_row((key, ts, v))
    return len(rows)


def yahoo(conn, tickers, table, key_col, val_col):
    import yfinance as yf
    data = yf.download(" ".join(tickers), start=os.environ.get("START", "1990-01-01"), interval="1d",
                       group_by="ticker", auto_adjust=False, progress=False, threads=True)
    total = 0
    for t in tickers:
        try:
            closes = data[t]["Close"].dropna()
        except Exception as exc:  # noqa: BLE001 — one series failing must not stop the rest
            print(f"WARN {t}: {exc}", flush=True)
            continue
        with conn.cursor() as cur:
            first = first_live(cur, table, key_col, t)
        rows = pre_live(closes.items(), first)
        n = write_series(conn, table, key_col, val_col, t, rows, first)
        print(f"{t}: {n} rows {rows[0][0].date() if rows else '-'} .. {rows[-1][0].date() if rows else '-'}", flush=True)
        total += n
    return total


def fred(conn):
    from fredapi import Fred
    api = Fred(api_key=os.environ["FRED_API_KEY"])
    total = 0
    for sid, (table, key_col, val_col) in FRED.items():
        try:
            series = api.get_series(sid).dropna()
        except Exception as exc:  # noqa: BLE001
            print(f"WARN {sid}: {exc}", flush=True)
            continue
        with conn.cursor() as cur:
            first = first_live(cur, table, key_col, sid)
        rows = pre_live(series.items(), first)
        n = write_series(conn, table, key_col, val_col, sid, rows, first)
        print(f"{sid}: {n} rows {rows[0][0].date() if rows else '-'} .. {rows[-1][0].date() if rows else '-'}", flush=True)
        total += n
    return total


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ta_series(close, rsi_wilder):
    """Every indicator for every bar — the same formulas as ta-compute.compute() (causal, so the value at
    bar t equals what the live job would have written on day t). Columns = live indicator names."""
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    return pd.DataFrame({"RSI14": rsi_wilder(close), "MACD": macd, "MACD_SIGNAL": signal,
                         "MACD_HIST": macd - signal, "SMA20": sma20, "SMA50": close.rolling(50).mean(),
                         "BB_UPPER": sma20 + 2 * std20, "BB_MIDDLE": sma20, "BB_LOWER": sma20 - 2 * std20})


def ta(conn, ta_mod):
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT ticker FROM index_prices WHERE ts >= now() - interval '30 days'")
        tickers = [r[0] for r in cur.fetchall()]
    total = 0
    for t in sorted(tickers):
        with conn.cursor() as cur:
            cur.execute("SELECT ts, close FROM index_prices WHERE ticker = %s AND ts >= %s AND close IS NOT NULL "
                        "ORDER BY ts", (t, EPOCH))
            bars = cur.fetchall()
            cur.execute("SELECT min(ts) FROM technical_indicators WHERE ticker = %s AND ts >= %s", (t, EPOCH))
            first = cur.fetchone()[0]
        if len(bars) < ta_mod.MIN_BARS:
            continue
        df = pd.DataFrame(bars, columns=["ts", "close"]).set_index("ts")
        s = ta_series(df["close"].astype(float), ta_mod.rsi_wilder)
        s = s.iloc[ta_mod.MIN_BARS - 1:]                        # live job needs >= MIN_BARS bars
        if first is not None:
            s = s[s.index < first]
        long = s.stack().dropna()
        if long.empty:
            continue
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("DELETE FROM technical_indicators WHERE ticker = %s AND ts >= %s AND ts < %s",
                            (t, s.index[0], first or datetime(2100, 1, 1, tzinfo=timezone.utc)))
                with cur.copy("COPY technical_indicators (ticker, ts, indicator_name, value) FROM STDIN") as cp:
                    for (ts, name), v in long.items():
                        cp.write_row((t, ts, name, float(v)))
        print(f"{t}: {len(long)} rows {s.index[0].date()} .. {s.index[-1].date()}", flush=True)
        total += len(long)
    return total


def weekly_ends(index):
    """Positions of the last bar of each calendar week (pure)."""
    wk = pd.Series(range(len(index)), index=index)
    return wk.groupby([index.isocalendar().year, index.isocalendar().week]).max().sort_values().tolist()


def metrics(conn, sm):
    years = int(os.environ.get("YEARS", "5"))
    start = pd.Timestamp.now(tz="UTC") - pd.DateOffset(years=years)
    with conn.cursor() as cur:
        cur.execute("SELECT symbol FROM universe_constituents WHERE active ORDER BY 1")
        symbols = [r[0] for r in cur.fetchall()]
    total = 0
    for i, sym in enumerate(symbols, 1):
        with conn.cursor() as cur:
            cur.execute("SELECT ts, close, volume FROM stock_prices WHERE symbol = %s AND ts >= %s ORDER BY ts",
                        (sym, (start - pd.DateOffset(days=420)).to_pydatetime()))
            bars = cur.fetchall()
            cur.execute("SELECT min(ts) FROM stock_metrics_daily WHERE symbol = %s AND ts >= %s", (sym, EPOCH))
            first = cur.fetchone()[0]
        if len(bars) < 60:
            continue
        df = pd.DataFrame(bars, columns=["ts", "close", "volume"]).set_index("ts").astype(float)
        out = []
        idx = pd.DatetimeIndex(df.index)
        for pos in weekly_ends(idx):
            ts = idx[pos]
            if ts < start or (first is not None and ts >= first):
                continue
            window = df.iloc[max(0, pos + 1 - sm.BARS):pos + 1]
            for metric, v in sm.compute(window).items():
                if v is not None and not pd.isna(v):
                    out.append((ts.to_pydatetime(), metric, float(v)))
        if out:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM stock_metrics_daily WHERE symbol = %s AND ts >= %s AND ts < %s",
                                (sym, out[0][0], first or datetime(2100, 1, 1, tzinfo=timezone.utc)))
                    with cur.copy("COPY stock_metrics_daily (symbol, ts, metric, value) FROM STDIN") as cp:
                        for ts, metric, v in out:
                            cp.write_row((sym, ts, metric, v))
        total += len(out)
        if i % 100 == 0:
            print(f"metrics: {i}/{len(symbols)} symbols, {total} rows", flush=True)
    return total


def main() -> int:
    mode = os.environ.get("MODE", "")
    conn = connect()
    if mode == "fx":
        n = yahoo(conn, FX, "fx_rates", "pair", "rate")
    elif mode == "yields":
        n = yahoo(conn, YIELDS, "bond_yields", "instrument", "yield")
    elif mode == "fred":
        n = fred(conn)
    elif mode == "ta":
        n = ta(conn, load("/app/ta-compute.py", "ta_compute"))
    elif mode == "metrics":
        sys.path.insert(0, "/app")
        import stock_metrics
        n = metrics(conn, stock_metrics)
    else:
        print(f"unknown MODE {mode!r}", flush=True)
        return 2
    conn.close()
    print(f"HISTORY-BACKFILL-OK mode={mode} rows={n}", flush=True)
    return 0 if n else 1


if __name__ == "__main__":
    sys.exit(main())
