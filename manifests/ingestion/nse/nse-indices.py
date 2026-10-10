"""Daily NSE/India indices fetcher via yfinance (validated Yahoo symbols).

Writes into index_prices (same schema as the global batch). Idempotent
DELETE+INSERT per (ticker, ts). Runs 11:15 UTC, after NSE close (10:00 UTC).

Symbol notes (verified 2026-09-29 on the TX2 stack; re-probed 2026-10-09):
- Live: ^NSEI ^NSEBANK ^CNXIT ^CNXPHARMA ^BSESN ^INDIAVIX
         NIFTYMIDCAP150.NS NIFTYSMLCAP250.NS
- RESTORED ^CRSLDX (Nifty 500) 2026-10-09: probed live on Yahoo — 21 valid
  daily bars over 1mo, fresh through today (NIFTY500.NS itself stays dead).
- STILL DROPPED ^CNXAUTO / ^CNXFMCG: stale ghosts (current quote only, no
  history). NIFTYAUTO.NS/NIFTYFMCG.NS also dead. NSE direct/jugaad-data is
  the only remaining avenue — documented in ops manual §12.2.

Env: PGHOST, PGUSER, PGPASSWORD, PGDATABASE. Exit 1 only if zero rows written.
"""

import os
import sys

import pandas as pd
import psycopg
import yfinance as yf

TICKERS = [
    "^NSEI",           # Nifty 50
    "^NSEBANK",        # Nifty Bank
    "^CNXIT",          # Nifty IT
    "^CNXPHARMA",      # Nifty Pharma
    "NIFTYMIDCAP150.NS",
    "NIFTYSMLCAP250.NS",
    "^CRSLDX",         # Nifty 500 (restored 2026-10-09)
    "^BSESN",          # Sensex
    "^INDIAVIX",       # India VIX
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
    for ticker in TICKERS:
        try:
            df = data[ticker].dropna(subset=["Close"])
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
