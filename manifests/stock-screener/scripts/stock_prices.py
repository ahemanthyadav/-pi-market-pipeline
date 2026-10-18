"""Daily stock prices (Phase C) + max-history backfill (Phase D).

Two modes:
- daily (default): chunked yfinance '5d' pull over the active universe — late-data
  tolerant, covers missed days.
- BACKFILL='max': full history, fetched ONE SYMBOL AT A TIME — Yahoo throttles
  multi-symbol max-range chunks into silent multi-minute retries (2026-10-04),
  while per-symbol requests flow. Resumable via the job_state cursor at symbol
  granularity (sorted order; cursor cleared on completion).

Timestamps (ADR 0013): every row is stamped 00:00 UTC on the exchange's trade date.
yf.download() returns a tz-naive date index, but Ticker.history() returns tz-aware
exchange-local midnights — trade_ts() normalises both, so no path can reintroduce
the DQ-4 mixed conventions.

Split handling (DQ-1, 2026-10-14): Yahoo back-adjusts OHLC for splits/spin-offs but our
older rows keep the pre-split scale. The daily pull asks for actions and, when a symbol
shows a non-zero 'Stock Splits' in the 5-day window, re-fetches that symbol's full
history and rewrites it (same idempotent DELETE+INSERT per (symbol, ts)). Capped at
SPLIT_RESYNC_MAX symbols per run (a Yahoo glitch must not turn into a mass backfill).
Dividends (total return) are still not modelled.

Connection discipline (lesson 2026-10-04: a read-phase transaction held open
across long downloads gets dropped by the pod→DB path):
- reads run in autocommit (no idle transaction),
- each symbol's rows commit in one atomic transaction,
- on OperationalError the connection is rebuilt and the symbol retried once.
"""
import datetime as dt
import os
import sys
import time

import pandas as pd
import psycopg
import yfinance as yf


def trade_ts(ts):
    """00:00 UTC on the bar's trade date (ADR 0013), whatever tz the index carries."""
    return dt.datetime(ts.year, ts.month, ts.day, tzinfo=dt.timezone.utc)


def split_events(df):
    """[(date, ratio)] for non-zero 'Stock Splits' rows (NaN/0 = no split)."""
    if df is None or "Stock Splits" not in getattr(df, "columns", ()):
        return []
    col = df["Stock Splits"].fillna(0)
    return [(ts, float(v)) for ts, v in col.items() if v and float(v) != 1.0]


def action_events(df):
    """[(date, action_type, value)] for splits and dividends — the corporate_actions rows.
    Only splits trigger a history resync; dividends are recorded, nothing more."""
    events = [(ts, "split", r) for ts, r in split_events(df)]
    if df is not None and "Dividends" in getattr(df, "columns", ()):
        for ts, v in df["Dividends"].fillna(0).items():
            if v and float(v) != 0.0:
                events.append((ts, "dividend", float(v)))
    return events


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
                bar_ts = trade_ts(ts)
                cur.execute("DELETE FROM stock_prices WHERE symbol=%s AND ts=%s",
                            (symbol, bar_ts))
                cur.execute("INSERT INTO stock_prices (symbol, ts, open, high, low, "
                            "close, volume) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                            (symbol, bar_ts, num("Open"), num("High"),
                             num("Low"), num("Close"),
                             None if vol is None or pd.isna(vol) else int(vol)))
                written += 1
            cur.execute("INSERT INTO job_state (job_name, last_key, updated_at) "
                        "VALUES (%s,%s,now()) ON CONFLICT (job_name) DO UPDATE "
                        "SET last_key=EXCLUDED.last_key, updated_at=now()",
                        (job, symbol))
    return written


def write_corporate_actions(conn, symbol, events):
    """Upsert split/dividend rows (DQ-1). Splits fill `ratio`, dividends fill `amount`.
    adj_close is deliberately NOT written here: per data-foundations draft §2/§3.1 it must be
    our own total-return series computed from close + corporate_actions, not Yahoo's
    Adj Close (rewritten backwards on every dividend; stale in rows the 5-day job skips)."""
    with conn.transaction():
        with conn.cursor() as cur:
            for ts, action_type, value in events:
                ratio = value if action_type == "split" else None
                amount = value if action_type == "dividend" else None
                cur.execute(
                    "INSERT INTO corporate_actions (symbol, ts, action_type, ratio, amount, source) "
                    "VALUES (%s,%s,%s,%s,%s,'yfinance') "
                    "ON CONFLICT (symbol, ts, action_type) DO UPDATE "
                    "SET ratio=EXCLUDED.ratio, amount=EXCLUDED.amount",
                    (symbol, trade_ts(ts), action_type, ratio, amount))


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
    split_syms = {}
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
                               threads=True, actions=True)
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
                    events = split_events(df)
                    if events:
                        split_syms[sym] = events
                    actions = action_events(df)
                    if actions:
                        try:
                            write_corporate_actions(conn, sym, actions)
                        except Exception as exc:  # noqa: BLE001 — prices already committed
                            print(f"WARN {sym} corporate_actions write failed: {exc}",
                                  flush=True)
                except Exception as exc:  # noqa: BLE001
                    print(f"WARN {sym} failed: {exc}", flush=True)
                    failed += 1
            print(f"chunk {i // chunk_n + 1}/{(len(symbols) + chunk_n - 1) // chunk_n}: "
                  f"{done} ok, {failed} warn, {total_rows} rows", flush=True)
            time.sleep(3)
    resynced = 0
    if split_syms:
        cap = int(os.environ.get("SPLIT_RESYNC_MAX", "25"))
        if len(split_syms) > cap:
            print(f"WARN {len(split_syms)} symbols show splits (> {cap}); resyncing "
                  f"the first {cap} only — review the rest", flush=True)
        for sym, events in sorted(split_syms.items())[:cap]:
            desc = ",".join(f"{d.date()}x{r:g}" for d, r in events)
            try:
                full = yf.Ticker(sym).history(period="max", interval="1d",
                                              auto_adjust=False)
                if full is None or full.empty:
                    print(f"WARN split resync {sym} ({desc}): no history", flush=True)
                    continue
                rows, conn = write_resilient(conn, sym, full.dropna(subset=["Close"]),
                                             "stock_prices_split")
                resynced += 1
                print(f"SPLIT-RESYNC {sym} {desc} rows={rows}", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"WARN split resync {sym} ({desc}) failed: {exc}", flush=True)
            time.sleep(0.8)
    if mode == "max" and done + failed >= len(symbols):
        with conn.cursor() as cur:
            cur.execute("UPDATE job_state SET last_key=NULL WHERE job_name=%s", (job,))
    conn.close()
    print(f"PRICES-OK mode={mode} fetched={done} warn={failed} rows={total_rows} "
          f"splits_resynced={resynced}", flush=True)
    return 0 if done else 1


if __name__ == "__main__":
    sys.exit(main())
