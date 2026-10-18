#!/usr/bin/env python3
"""Tests for stock_prices.py (DQ-1 split resync, ADR 0013 timestamps).

No database, no network: psycopg/yfinance are stubbed, yf.download / Ticker.history are fakes.

    python3 tests/test_stock_prices.py
"""
import contextlib
import datetime as dt
import io
import os
import sys
import types
import unittest
from pathlib import Path

import pandas as pd

for name in ("psycopg", "yfinance"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["psycopg"].OperationalError = type("OperationalError", (Exception,), {})

SCRIPTS = Path(__file__).resolve().parent.parent / "manifests" / "stock-screener" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import stock_prices as sp  # noqa: E402

UTC = dt.timezone.utc


def bars(dates, splits=None, tz=None, close=10.0):
    idx = pd.DatetimeIndex(pd.to_datetime(dates)).tz_localize(tz) if tz else pd.DatetimeIndex(pd.to_datetime(dates))
    df = pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close, "Volume": 100.0}, index=idx)
    df["Stock Splits"] = 0.0
    for d, r in (splits or {}).items():
        df.loc[pd.Timestamp(d).tz_localize(tz) if tz else pd.Timestamp(d), "Stock Splits"] = r
    return df


class FakeCursor:
    def __init__(self, log):
        self.log = log

    def execute(self, sql, params=()):
        self.log.append((" ".join(sql.split()), params))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeConn:
    def __init__(self):
        self.log = []

    @contextlib.contextmanager
    def transaction(self):
        yield

    def cursor(self):
        return FakeCursor(self.log)

    def close(self):
        pass


class TradeTs(unittest.TestCase):
    def test_naive_index_is_midnight_utc(self):
        self.assertEqual(sp.trade_ts(pd.Timestamp("2026-10-02")), dt.datetime(2026, 10, 2, tzinfo=UTC))

    def test_exchange_local_midnight_keeps_trade_date(self):
        # Ticker.history() style: NSE bar = local midnight = 18:30 UTC of the previous day
        self.assertEqual(sp.trade_ts(pd.Timestamp("2026-09-07", tz="Asia/Kolkata")),
                         dt.datetime(2026, 9, 7, tzinfo=UTC))
        self.assertEqual(sp.trade_ts(pd.Timestamp("2026-10-01", tz="America/New_York")),
                         dt.datetime(2026, 10, 1, tzinfo=UTC))

    def test_write_symbol_stamps_midnight_utc(self):
        conn = FakeConn()
        df = bars(["2026-09-07", "2026-09-08"], tz="Asia/Kolkata")
        self.assertEqual(sp.write_symbol(conn, "TCS.NS", df, "j"), 2)
        stamps = {p[1] for q, p in conn.log if q.startswith("INSERT INTO stock_prices")}
        self.assertEqual(stamps, {dt.datetime(2026, 9, 7, tzinfo=UTC), dt.datetime(2026, 9, 8, tzinfo=UTC)})
        deletes = [p for q, p in conn.log if q.startswith("DELETE FROM stock_prices")]
        self.assertEqual(len(deletes), 2)  # idempotent DELETE+INSERT per (symbol, ts)


class SplitEvents(unittest.TestCase):
    def test_detects_nonzero_split(self):
        ev = sp.split_events(bars(["2026-09-30", "2026-10-01"], splits={"2026-10-01": 6.665}))
        self.assertEqual([(d.date().isoformat(), r) for d, r in ev], [("2026-10-01", 6.665)])

    def test_none_zero_nan_and_one_are_not_splits(self):
        df = bars(["2026-09-30", "2026-10-01", "2026-10-02"])
        df["Stock Splits"] = [0.0, float("nan"), 1.0]
        self.assertEqual(sp.split_events(df), [])

    def test_missing_column_or_frame(self):
        self.assertEqual(sp.split_events(None), [])
        self.assertEqual(sp.split_events(bars(["2026-10-01"]).drop(columns=["Stock Splits"])), [])


class DailyRun(unittest.TestCase):
    """main() in daily mode with the split symbol re-fetched in full."""

    def run_main(self, universe, download_df, history, env=None):
        calls = {"download_kwargs": None, "history": []}
        conn = FakeConn()

        class Cur(FakeCursor):
            def fetchall(s):
                return [(x,) for x in universe]

            def fetchone(s):
                return None

        class C(FakeConn):
            def cursor(s):
                return Cur(s.log)

        conn = C()
        yf = sys.modules["yfinance"]

        def download(tickers, **kw):
            calls["download_kwargs"] = kw
            return {t: download_df[t] for t in tickers.split()} if len(tickers.split()) > 1 else download_df[tickers]

        class Ticker:
            def __init__(s, sym):
                s.sym = sym

            def history(s, **kw):
                calls["history"].append((s.sym, kw))
                return history[s.sym]

        yf.download, yf.Ticker = download, Ticker
        sp.connect = lambda: conn
        sp.time.sleep = lambda *_: None
        old = dict(os.environ)
        os.environ.update({"BACKFILL": "", "UNIVERSE_LIMIT": "0", **(env or {})})
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                rc = sp.main()
        finally:
            os.environ.clear()
            os.environ.update(old)
        return rc, out.getvalue(), conn, calls

    def test_split_symbol_is_resynced_in_full_others_are_not(self):
        recent = {"CTVA": bars(["2026-10-12", "2026-10-13"], splits={"2026-10-13": 6.665}),
                  "AAPL": bars(["2026-10-12", "2026-10-13"])}
        full = bars(["2026-09-01", "2026-09-02", "2026-10-12", "2026-10-13"], tz="America/New_York")
        rc, out, conn, calls = self.run_main(["AAPL", "CTVA"], recent, {"CTVA": full})
        self.assertEqual(rc, 0)
        self.assertTrue(calls["download_kwargs"]["actions"])
        self.assertEqual([c[0] for c in calls["history"]], ["CTVA"])
        self.assertEqual(calls["history"][0][1]["period"], "max")
        self.assertIn("SPLIT-RESYNC CTVA 2026-10-13x6.665 rows=4", out)
        self.assertIn("splits_resynced=1", out)
        self.assertTrue(out.strip().splitlines()[-1].startswith("PRICES-OK mode=daily"))
        stamps = {p[1] for q, p in conn.log if q.startswith("INSERT INTO stock_prices") and p[0] == "CTVA"}
        self.assertTrue(all(t.hour == 0 and t.minute == 0 and t.tzinfo == UTC for t in stamps))
        self.assertIn(dt.datetime(2026, 9, 1, tzinfo=UTC), stamps)

    def test_no_splits_means_no_history_fetch(self):
        recent = {"AAPL": bars(["2026-10-13"])}
        rc, out, conn, calls = self.run_main(["AAPL"], recent, {})
        self.assertEqual(rc, 0)
        self.assertEqual(calls["history"], [])
        self.assertIn("splits_resynced=0", out)

    def test_resync_is_capped(self):
        syms = ["S1", "S2", "S3"]
        recent = {s: bars(["2026-10-13"], splits={"2026-10-13": 2.0}) for s in syms}
        full = {s: bars(["2026-10-12", "2026-10-13"]) for s in syms}
        rc, out, conn, calls = self.run_main(syms, recent, full, env={"SPLIT_RESYNC_MAX": "2"})
        self.assertEqual(len(calls["history"]), 2)
        self.assertIn("WARN 3 symbols show splits (> 2)", out)
        self.assertIn("splits_resynced=2", out)

    def test_failed_resync_does_not_fail_the_run(self):
        recent = {"CTVA": bars(["2026-10-13"], splits={"2026-10-13": 6.665})}
        rc, out, conn, calls = self.run_main(["CTVA"], recent, {"CTVA": pd.DataFrame()})
        self.assertEqual(rc, 0)
        self.assertIn("WARN split resync CTVA", out)
        self.assertIn("splits_resynced=0", out)

    def test_dividend_is_recorded_but_never_triggers_resync(self):
        df = bars(["2026-10-12", "2026-10-13"])
        df["Dividends"] = [0.0, 0.26]
        rc, out, conn, calls = self.run_main(["AAPL"], {"AAPL": df}, {})
        self.assertEqual(rc, 0)
        self.assertEqual(calls["history"], [])  # no full-history refetch for a dividend
        self.assertIn("splits_resynced=0", out)
        ca = [p for q, p in conn.log if q.startswith("INSERT INTO corporate_actions")]
        self.assertEqual(ca, [("AAPL", dt.datetime(2026, 10, 13, tzinfo=UTC), "dividend", None, 0.26)])

    def test_split_recorded_as_corporate_action_with_ratio(self):
        recent = {"CTVA": bars(["2026-10-12", "2026-10-13"], splits={"2026-10-13": 6.665})}
        full = bars(["2026-10-12", "2026-10-13"])
        rc, out, conn, calls = self.run_main(["CTVA"], recent, {"CTVA": full})
        ca = [p for q, p in conn.log if q.startswith("INSERT INTO corporate_actions")]
        self.assertEqual(ca, [("CTVA", dt.datetime(2026, 10, 13, tzinfo=UTC), "split", 6.665, None)])

    def test_adj_close_is_not_taken_from_yahoo(self):
        conn = FakeConn()
        df = bars(["2026-10-13"])
        df["Adj Close"] = 9.0
        sp.write_symbol(conn, "AAPL", df, "j")
        ins = [q for q, p in conn.log if q.startswith("INSERT INTO stock_prices")]
        self.assertTrue(ins and all("adj_close" not in q for q in ins))


if __name__ == "__main__":
    unittest.main(verbosity=1)
