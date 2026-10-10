"""Daily stock prices (Phase C) + max-history backfill (Phase D).

Two modes:
- daily (default): chunked yfinance '5d' pull over the active universe — late-data
  tolerant, covers missed days.
- BACKFILL='max': full history, fetched ONE SYMBOL AT A TIME — Yahoo throttles
  multi-symbol max-range chunks into silent multi-minute retries (2026-10-04),
  while per-symbol requests flow. Resumable via the job_state cursor at symbol
  granularity (sorted order; cursor cleared on completion).

Connection discipline (lesson 2026-10-04: a read-phase transaction held open
across long downloads gets dropped by the pod→DB path):
- reads run in autocommit (no idle transaction),
- each symbol's rows commit in one atomic transaction,
- on OperationalError the connection is rebuilt and the symbol retried once.
"""
import os
import sys
import time

import pandas as pd
import psycopg
import yfinance as yf


def connect():
    conn = psycopg.connect(
        host=os.environ.get("PGHOST", "timescaledb.market-data.svc.cluster.local"),
        user=os.environ.get("PGUSER", "postgres"),
        password=os.environ["PGPASSWORD"],
        dbname=os.environ.get("PGDATABASE", "postgres"),
    )
    conn.autocommit = True
    return conn


def get_symbols(cur, limit=None):
    cur.execute("SELECT DISTINCT symbol FROM universe_constituents WHERE active "
                "ORDER BY 1")
    syms = [r[0] for r in cur.fetchall()]
    return syms[:limit] if limit else syms


def write_symbol(conn, symbol, df, job):
    """Atomic per-symbol write + job_state cursor. Returns rows written."""
    written = 0
    with conn.transaction():
        with conn.cursor() as cur:
            for ts, bar in df.iterrows():
                if pd.isna(bar.get("Close")):
                    continue

                def num(col):
                    v = bar.get(col)
                    return None if v is None or pd.isna(v) else float(v)

                vol = bar.get("Volume")
                cur.execute("DELETE FROM stock_prices WHERE symbol=%s AND ts=%s",
                            (symbol, ts.to_pydatetime()))
                cur.execute("INSERT INTO stock_prices (symbol, ts, open, high, low, "
                            "close, volume) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                            (symbol, ts.to_pydatetime(), num("Open"), num("High"),
                             num("Low"), num("Close"),
                             None if vol is None or pd.isna(vol) else int(vol)))
                written += 1
            cur.execute("INSERT INTO job_state (job_name, last_key, updated_at) "
                        "VALUES (%s,%s,now()) ON CONFLICT (job_name) DO UPDATE "
                        "SET last_key=EXCLUDED.last_key, updated_at=now()",
                        (job, symbol))
    return written


def write_resilient(conn, symbol, df, job):
    """Write one symbol; on a dropped connection, rebuild it and retry once.
    Returns (rows, conn)."""
    try:
        return write_symbol(conn, symbol, df, job), conn
    except psycopg.OperationalError as exc:
        print(f"WARN {symbol} conn dropped ({exc}); reconnecting", flush=True)
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
        conn = connect()
        return write_symbol(conn, symbol, df, job), conn


def main() -> int:
    mode = os.environ.get("BACKFILL", "").strip().lower() or "daily"
    period = "max" if mode == "max" else "5d"
    limit = int(os.environ.get("UNIVERSE_LIMIT", "0") or 0) or None
    job = f"stock_prices_{mode}"
    chunk_n = int(os.environ.get("CHUNK", "50"))
    conn = connect()
    with conn.cursor() as cur:
        symbols = get_symbols(cur, limit)
        cur.execute("SELECT last_key FROM job_state WHERE job_name=%s", (job,))
        row = cur.fetchone()
        if row and row[0] and mode == "max":
            symbols = [s for s in symbols if s > row[0]]
            print(f"resuming after {row[0]}: {len(symbols)} symbols left", flush=True)
    if not symbols:
        if mode == "max":
            # Empty post-cursor universe in backfill mode = pass already complete
            # (a previous attempt died between the last symbol and the clear).
            with conn.cursor() as cur:
                cur.execute("UPDATE job_state SET last_key=NULL WHERE job_name=%s",
                            (job,))
            print("pass already complete — cursor cleared", flush=True)
        else:
            print("nothing to do (universe empty)", flush=True)
        return 0
    print(f"mode={mode} period={period} symbols={len(symbols)} chunk={chunk_n}",
          flush=True)
    done, failed, total_rows = 0, 0, 0
    if mode == "max":
        for n, sym in enumerate(symbols, 1):
            try:
                df = yf.Ticker(sym).history(period="max", interval="1d",
                                            auto_adjust=False)
                if df is None or df.empty:
                    print(f"WARN no data {sym}", flush=True)
                    failed += 1
                else:
                    rows, conn = write_resilient(conn, sym,
                                                 df.dropna(subset=["Close"]), job)
                    total_rows += rows
                    done += 1
            except Exception as exc:  # noqa: BLE001
                print(f"WARN {sym} failed: {exc}", flush=True)
                failed += 1
            if n % 25 == 0 or n == len(symbols):
                print(f"{n}/{len(symbols)}: {done} ok, {failed} warn, "
                      f"{total_rows} rows", flush=True)
            time.sleep(0.8)
    else:
        for i in range(0, len(symbols), chunk_n):
            chunk = symbols[i:i + chunk_n]
            data = yf.download(" ".join(chunk), period=period, interval="1d",
                               group_by="ticker", auto_adjust=False, progress=False,
                               threads=True)
            frames = data if len(chunk) > 1 else {chunk[0]: data}
            for sym in chunk:
                try:
                    df = frames[sym].dropna(subset=["Close"]) \
                        if frames[sym] is not None else None
                    if df is None or df.empty:
                        print(f"WARN no data {sym}", flush=True)
                        failed += 1
                        continue
                    rows, conn = write_resilient(conn, sym, df, job)
                    total_rows += rows
                    done += 1
                except Exception as exc:  # noqa: BLE001
                    print(f"WARN {sym} failed: {exc}", flush=True)
                    failed += 1
            print(f"chunk {i // chunk_n + 1}/{(len(symbols) + chunk_n - 1) // chunk_n}: "
                  f"{done} ok, {failed} warn, {total_rows} rows", flush=True)
            time.sleep(3)
    if mode == "max" and done + failed >= len(symbols):
        with conn.cursor() as cur:
            cur.execute("UPDATE job_state SET last_key=NULL WHERE job_name=%s", (job,))
    conn.close()
    print(f"PRICES-OK mode={mode} fetched={done} warn={failed} rows={total_rows}",
          flush=True)
    return 0 if done else 1


if __name__ == "__main__":
    sys.exit(main())
