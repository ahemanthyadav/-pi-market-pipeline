"""Daily batch fetcher: global indices + DXY + metals/energy futures via yfinance.

Writes one row per ticker per day into index_prices (ticker, ts, o/h/l/c, volume).
Idempotent: DELETEs the (ticker, ts) row before INSERT, so re-runs and late
corrections overwrite cleanly. No schema migration needed (no new constraints).

Env: PGHOST, PGUSER, PGPASSWORD, PGDATABASE (defaults suit the in-cluster DB).
Exit 0 unless zero rows were written (signals CronJob failure).
"""

import os
import sys

import pandas as pd
import psycopg
import yfinance as yf

TICKERS = [
    # US
    "^GSPC", "^IXIC", "^DJI", "^RUT", "^VIX",
    "^RUI",  # Russell 1000 (added 2026-10-10; Yahoo probe: 251 daily bars over 1y)
    # Europe
    "^FTSE", "^GDAXI", "^FCHI", "^STOXX50E", "^IBEX",
    "FTSEMIB.MI", "^SSMI", "^AEX",
    # APAC
    "^N225", "^HSI", "000001.SS", "399001.SZ",
    "^KS11", "^TWII", "^AXJO", "^STI",
    # Americas ex-US
    "^GSPTSE", "^BVSP", "^MXX",
    # Dollar index + metals/energy futures
    "DX-Y.NYB", "GC=F", "SI=F", "CL=F",
]


def fetch_latest() -> dict:
    """Return {ticker: (ts, open, high, low, close, volume)} for the latest valid row."""
    period = os.environ.get("FETCH_PERIOD", "5d")  # backfills use 1y
    backfill = os.environ.get("BACKFILL", "0") == "1"
    data = yf.download(
        " ".join(TICKERS),
        period=period,
        interval="1d",
        group_by="ticker",
        auto_adjust=False,
        progress=False,
        threads=True,
    )
    rows = {}
    frames = data if len(TICKERS) > 1 else {TICKERS[0]: data}
    for ticker in TICKERS:
        try:
            df = frames[ticker].dropna(subset=["Close"])
            if df.empty:
                print(f"WARN no data for {ticker}", flush=True)
                continue
            frame = df if backfill else df.iloc[[-1]]
            out = []
            for ts, bar in frame.iterrows():
                ts = ts.to_pydatetime()

                def num(col):
                    val = bar[col]
                    return None if pd.isna(val) else float(val)

                vol = bar["Volume"]
                out.append((
                    ts,
                    num("Open"),
                    num("High"),
                    num("Low"),
                    num("Close"),
                    None if pd.isna(vol) else int(vol),
                ))
            rows[ticker] = out
        except Exception as exc:  # noqa: BLE001 - per-ticker failure must not kill the batch
            print(f"WARN {ticker} failed: {exc}", flush=True)
    return rows


def write_rows(rows: dict) -> int:
    conn = psycopg.connect(
        host=os.environ.get("PGHOST", "timescaledb.market-data.svc.cluster.local"),
        user=os.environ.get("PGUSER", "postgres"),
        password=os.environ["PGPASSWORD"],
        dbname=os.environ.get("PGDATABASE", "postgres"),
    )
    written = 0
    with conn:
        with conn.cursor() as cur:
            for ticker, bars in rows.items():
                for (ts, o, h, low, c, v) in bars:
                    cur.execute(
                        "DELETE FROM index_prices WHERE ticker = %s AND ts = %s",
                        (ticker, ts),
                    )
                    cur.execute(
                        "INSERT INTO index_prices "
                        "(ticker, ts, open, high, low, close, volume) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (ticker, ts, o, h, low, c, v),
                    )
                    written += 1
    conn.close()
    return written


def main() -> int:
    rows = fetch_latest()
    print(f"fetched {len(rows)}/{len(TICKERS)} tickers", flush=True)
    if not rows:
        print("ERROR: zero rows fetched", flush=True)
        return 1
    written = write_rows(rows)
    print(f"wrote {written} rows into index_prices", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
