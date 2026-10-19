"""DQ-1 one-off (re-runnable): full corporate-actions history + our own adj_close, per symbol.

For every active symbol: Yahoo's full dividend/split history (`Ticker.actions`, one request)
-> corporate_actions (upsert), then recompute_adj_close() over the whole symbol.
One symbol at a time (Yahoo throttles multi-symbol long ranges — ADR 0003), resumable via
job_state 'corporate_actions_backfill' (cursor cleared when the pass completes).
Re-running is safe: upserts + "only rewrite changed adj_close" updates (ADR 0005).

Env: UNIVERSE_LIMIT (canary), SYMBOLS (comma list overrides the universe), PAUSE (s, 0.6).
"""
import os
import sys
import time

import yfinance as yf

from stock_prices import (action_events, connect, get_symbols, recompute_adj_close,
                          write_corporate_actions)

JOB = "corporate_actions_backfill"


def main() -> int:
    limit = int(os.environ.get("UNIVERSE_LIMIT", "0") or 0) or None
    pause = float(os.environ.get("PAUSE", "0.6"))
    only = [s.strip() for s in os.environ.get("SYMBOLS", "").split(",") if s.strip()]
    conn = connect()
    with conn.cursor() as cur:
        symbols = only or get_symbols(cur, limit)
        cursor = None
        if not only:
            cur.execute("SELECT last_key FROM job_state WHERE job_name=%s", (JOB,))
            row = cur.fetchone()
            cursor = row[0] if row else None
    if cursor:
        symbols = [s for s in symbols if s > cursor]
        print(f"resuming after {cursor}: {len(symbols)} left", flush=True)
    print(f"symbols={len(symbols)}", flush=True)
    done = failed = n_div = n_split = n_adj = 0
    for n, sym in enumerate(symbols, 1):
        try:
            acts = yf.Ticker(sym).actions
            events = action_events(acts) if acts is not None and len(acts) else []
            if events:
                write_corporate_actions(conn, sym, events)
            n_div += sum(1 for e in events if e[1] == "dividend")
            n_split += sum(1 for e in events if e[1] == "split")
            n_adj += recompute_adj_close(conn, sym)
            done += 1
            if not only:
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO job_state (job_name, last_key, updated_at) "
                                "VALUES (%s,%s,now()) ON CONFLICT (job_name) DO UPDATE "
                                "SET last_key=EXCLUDED.last_key, updated_at=now()", (JOB, sym))
        except Exception as exc:  # noqa: BLE001
            print(f"WARN {sym} failed: {exc}", flush=True)
            failed += 1
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
            conn = connect()
        if n % 50 == 0 or n == len(symbols):
            print(f"{n}/{len(symbols)}: ok={done} warn={failed} dividends={n_div} "
                  f"splits={n_split} adj_rows={n_adj}", flush=True)
        time.sleep(pause)
    if not only and not limit and done + failed >= len(symbols):
        with conn.cursor() as cur:
            cur.execute("UPDATE job_state SET last_key=NULL WHERE job_name=%s", (JOB,))
        print("cursor cleared (full pass complete)", flush=True)
    conn.close()
    print(f"ACTIONS-BACKFILL-OK ok={done} warn={failed} dividends={n_div} splits={n_split} "
          f"adj_rows={n_adj}", flush=True)
    return 0 if done else 1


if __name__ == "__main__":
    sys.exit(main())
