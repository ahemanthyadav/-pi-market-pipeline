"""One-shot FX daily-close backfill (run via backfill-job.yaml; NOT baked into the image).

fx-fetcher has no history mode, so fx_rates began 2026-09-30 and the Telegram /fx card had no YTD
(its YTD reads the last value before 1 Jan, within a 20-day lookback). This loads daily closes
FETCH_START .. BEFORE_TS for the same 10 pairs and the same conversion as fx-fetcher (ts = the
yfinance index timestamp, rate = Close). Idempotent DELETE+INSERT per (pair, ts); only dates
before BEFORE_TS are touched, so the live daily + hourly rows are never rewritten.

Env: PGHOST, PGUSER, PGPASSWORD, PGDATABASE, FETCH_START (default 2025-12-15), BEFORE_TS (default 2026-09-30).
"""
import os
import sys

import psycopg
import yfinance as yf

TICKERS = ["USDINR=X", "EURINR=X", "GBPINR=X", "JPYINR=X", "EURUSD=X",
           "GBPUSD=X", "USDJPY=X", "USDCNY=X", "USDCHF=X", "AUDUSD=X"]
START = os.environ.get("FETCH_START", "2025-12-15")
BEFORE = os.environ.get("BEFORE_TS", "2026-09-30")


def main() -> int:
    data = yf.download(" ".join(TICKERS), start=START, end=BEFORE, interval="1d",
                       group_by="ticker", auto_adjust=False, progress=False, threads=True)
    conn = psycopg.connect(
        host=os.environ.get("PGHOST", "timescaledb.market-data.svc.cluster.local"),
        user=os.environ.get("PGUSER", "postgres"), password=os.environ["PGPASSWORD"],
        dbname=os.environ.get("PGDATABASE", "postgres"))
    total = 0
    for pair in TICKERS:
        try:
            closes = data[pair]["Close"].dropna()
        except Exception as exc:  # noqa: BLE001 - one pair failing must not stop the rest
            print(f"WARN {pair} failed: {exc}", flush=True)
            continue
        rows = [(pair, ts.to_pydatetime(), float(v)) for ts, v in closes.items()]
        rows = [r for r in rows if r[1].strftime("%Y-%m-%d") < BEFORE]
        with conn.transaction():  # one atomic transaction per pair; do not use `with conn:` (it closes the connection)
            with conn.cursor() as cur:
                for pair_, ts, rate in rows:
                    cur.execute("DELETE FROM fx_rates WHERE pair = %s AND ts = %s", (pair_, ts))
                    cur.execute("INSERT INTO fx_rates (pair, ts, rate) VALUES (%s, %s, %s)", (pair_, ts, rate))
        print(f"{pair}: {len(rows)} rows ({rows[0][1].date() if rows else '-'} .. {rows[-1][1].date() if rows else '-'})", flush=True)
        total += len(rows)
    conn.close()
    print(f"FX-BACKFILL-OK rows={total}", flush=True)
    return 0 if total else 1


if __name__ == "__main__":
    sys.exit(main())
