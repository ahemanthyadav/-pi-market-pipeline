"""Unit tests for the index fetchers' write path (no network, no database).

    python3 tests/test_index_fetchers.py

Both fetchers must commit one calendar year per transaction and delete only
the exact (ticker, ts) rows they are about to insert.
"""
import importlib.util
import os
import sys
import types
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FETCHERS = {
    "yfinance": ROOT / "manifests/ingestion/yfinance/yfinance-fetcher.py",
    "nse": ROOT / "manifests/ingestion/nse/nse-indices.py",
}


class FakeCursor:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, args):
        self.log.append(("delete", sql, args))

    def executemany(self, sql, batch):
        self.log.append(("insert", sql, list(batch)))


class FakeConn:
    def __init__(self):
        self.log = []
        self.closed = False

    def transaction(self):
        self.log.append(("begin",))
        return FakeCursor(self.log)

    def cursor(self):
        return FakeCursor(self.log)

    def close(self):
        self.closed = True


def load(path, conn):
    """Import a fetcher with its heavy dependencies stubbed out."""
    for name in ("pandas", "yfinance"):
        sys.modules[name] = types.ModuleType(name)
    fake_pg = types.ModuleType("psycopg")
    fake_pg.connect = lambda **kw: conn
    sys.modules["psycopg"] = fake_pg
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bar(y, m, d, close=1.0):
    return (datetime(y, m, d), close, close, close, close, None)


ROWS = {
    "^A": [bar(2019, 12, 30), bar(2019, 12, 31), bar(2020, 1, 2)],
    "^B": [bar(2020, 1, 2), bar(1999, 6, 1)],
}


class WritePath(unittest.TestCase):
    def setUp(self):
        os.environ["PGPASSWORD"] = "x"
        os.environ.pop("BACKFILL", None)

    def each(self):
        for name, path in FETCHERS.items():
            conn = FakeConn()
            yield name, load(path, conn), conn

    def test_batches_are_one_per_year_oldest_first(self):
        for name, mod, _ in self.each():
            with self.subTest(name):
                batches = mod.year_batches(ROWS)
                self.assertEqual([y for y, _ in batches], [1999, 2019, 2020])
                self.assertEqual([len(b) for _, b in batches], [1, 2, 2])
                self.assertTrue(all(row[1].year == y for y, b in batches for row in b))

    def test_one_transaction_per_year(self):
        for name, mod, conn in self.each():
            with self.subTest(name):
                self.assertEqual(mod.write_rows(ROWS), 5)
                kinds = [entry[0] for entry in conn.log]
                self.assertEqual(kinds, ["begin", "delete", "insert"] * 3)
                self.assertTrue(conn.closed)

    def test_delete_names_exactly_the_rows_inserted(self):
        for name, mod, conn in self.each():
            with self.subTest(name):
                mod.write_rows(ROWS)
                deletes = [e for e in conn.log if e[0] == "delete"]
                inserts = [e for e in conn.log if e[0] == "insert"]
                for (_, sql, (tickers, stamps, low, high)), (_, _, batch) in zip(deletes, inserts):
                    self.assertEqual(list(zip(tickers, stamps)), [(r[0], r[1]) for r in batch])
                    self.assertEqual((low, high), (min(stamps), max(stamps)))
                    self.assertIn("p.ticker = k.ticker AND p.ts = k.ts", sql)

    def test_daily_run_is_a_single_small_batch(self):
        for name, mod, conn in self.each():
            with self.subTest(name):
                today = {"^A": [bar(2026, 10, 9)], "^B": [bar(2026, 10, 9)]}
                self.assertEqual(mod.write_rows(today), 2)
                self.assertEqual([e[0] for e in conn.log], ["begin", "delete", "insert"])


if __name__ == "__main__":
    unittest.main()
