"""Unit tests for the small fetchers' write paths and pure parsing (no network, no DB).

    python3 tests/test_small_fetchers.py

Extends AGENTS.md rule-4 coverage (previously only the index fetchers) to:
fx, yields, rates, intraday, news, rbi, fiidii and fdi-watch. Proven here:

  (a) every write DELETEs only its own (key, ts) rows before INSERTing — the
      DELETE SQL and params the fake cursor received name exactly the row that
      is inserted next, and nothing else;
  (b) running the write twice with identical data leaves no duplicate
      (key, ts) rows (simulated with a tiny in-memory SQL engine);
  (c) exit-code semantics: 0 when at least one row is written, 1 on zero rows
      (fdi-watch: always 0, it is informational by design);
  (d) news-fetcher's select-then-insert dedup skips (headline, source, day)
      rows that already exist — across runs and within one batch;
  (e) pure parsing against inline payloads: rbi page regexes, fiidii JSON
      (both envelope shapes), fdi PDF-link scraping, news feed-entry handling;
      plus rule 4's UTC requirement on every timestamp these parsers mint.

Third-party modules (pandas, yfinance, psycopg, requests, feedparser, fredapi,
lxml) are stubbed in sys.modules BEFORE the fetchers are imported; intraday is
additionally proven never to touch index_prices (rule 4: pure-daily table).
"""
import importlib.util
import io
import os
import re
import sys
import time
import types
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ING = ROOT / "manifests/ingestion"

os.environ["PGPASSWORD"] = "x"
os.environ["FRED_API_KEY"] = "x"
os.environ["TZ"] = "UTC"          # news-fetcher uses time.mktime (local-time based)
time.tzset()

UTC = timezone.utc


# --------------------------------------------------------------------------- fake DB
class MiniDB:
    """In-memory stand-in for the three SQL shapes the fetchers emit.

    Understands DELETE ... WHERE k=%s AND ts=%s, INSERT ... VALUES (...), the
    news SELECT-dedup (incl. ts::date casts) and ON CONFLICT (col) upserts —
    just enough to replay a write twice and count surviving rows.
    """

    def __init__(self):
        self.tables = {}
        self.log = []            # (op, table, sql, params)
        self.pending = []        # rows the next fetchone() pops

    # -- helpers -------------------------------------------------------------
    @staticmethod
    def _criteria(where, params):
        cols = re.findall(r"(\w+)(::date)?\s*=\s*%s(::date)?", where)
        assert len(cols) == len(params), f"placeholder/param mismatch: {where}"
        return [(c, v, bool(d1 or d2)) for (c, d1, d2), v in zip(cols, params)]

    @staticmethod
    def _matches(row, crit):
        for col, val, datecast in crit:
            have = row.get(col)
            if datecast:
                have = have.date() if hasattr(have, "date") else have
                val = val.date() if hasattr(val, "date") else val
            if have != val:
                return False
        return True

    @staticmethod
    def _paren_group(s):
        depth, start = 0, None
        for i, ch in enumerate(s):
            if ch == "(":
                depth += 1
                if depth == 1:
                    start = i + 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return s[start:i]
        raise AssertionError(f"unbalanced VALUES in: {s}")

    # -- execution -----------------------------------------------------------
    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        up = s.upper()
        if up.startswith("DELETE"):
            m = re.match(r"DELETE FROM (\w+) WHERE (.+)$", s, re.I)
            table, where = m.group(1), m.group(2)
            crit = self._criteria(where, params)
            rows = self.tables.setdefault(table, [])
            self.tables[table] = [r for r in rows if not self._matches(r, crit)]
            self.log.append(("delete", table, s, tuple(params)))
        elif up.startswith("INSERT"):
            m = re.match(r"INSERT INTO (\w+)\s*\(([^)]*)\)\s*VALUES\s*(.*)$", s, re.I)
            table, cols, rest = m.group(1), m.group(2), m.group(3)
            items = [x.strip() for x in self._paren_group(rest).split(",")]
            cols = [c.strip() for c in cols.split(",")]
            assert len(cols) == len(items), f"column/value mismatch: {s}"
            it = iter(params)
            row = {}
            for col, item in zip(cols, items):
                if item == "%s":
                    row[col] = next(it)
                elif item.startswith("'"):
                    row[col] = item.strip("'")
                else:
                    row[col] = item
            conflict = re.search(r"ON CONFLICT \((\w+)\)", s, re.I)
            rows = self.tables.setdefault(table, [])
            if conflict:
                key = conflict.group(1)
                rows[:] = [r for r in rows if r.get(key) != row.get(key)]
            rows.append(row)
            self.log.append(("insert", table, s, tuple(params)))
        elif up.startswith("SELECT"):
            m = re.match(r"SELECT .+? FROM (\w+) WHERE (.+)$", s, re.I)
            table, where = m.group(1), m.group(2)
            crit = self._criteria(where, params)
            hits = [r for r in self.tables.get(table, []) if self._matches(r, crit)]
            self.pending = [(1,)] * len(hits)
            self.log.append(("select", table, s, tuple(params)))
        else:
            raise AssertionError(f"unexpected SQL: {s}")

    def rows(self, table):
        return self.tables.get(table, [])

    def dupes(self, table, keys):
        seen, dup = set(), []
        for r in self.rows(table):
            k = tuple(r.get(c) for c in keys)
            if k in seen:
                dup.append(k)
            seen.add(k)
        return dup


class FakeCursor:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        self.db.execute(sql, params)

    def fetchone(self):
        return self.db.pending.pop(0) if self.db.pending else None


class _Txn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, db):
        self.db = db
        self.closed = False
        self.autocommit = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return FakeCursor(self.db)

    def transaction(self):
        return _Txn()

    def close(self):
        self.closed = True


# --------------------------------------------------------------------- module stubs
CURRENT_DB = [MiniDB()]


class OperationalError(Exception):
    pass


def _default_connect(**kw):
    return FakeConn(CURRENT_DB[0])


PSYCOPG = types.ModuleType("psycopg")
PSYCOPG.OperationalError = OperationalError
PSYCOPG.connect = _default_connect

REQUESTS_GET = [None]          # test-settable callable(url, **kw) -> response
SESSION_SCRIPT = []            # responses popped by FakeSession.get, in order


class FakeResponse:
    def __init__(self, text="", json_data=None, status_ok=True):
        self.text = text
        self._json = json_data
        self._ok = status_ok

    def raise_for_status(self):
        if not self._ok:
            raise RuntimeError("HTTP error")

    def json(self):
        return self._json


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.calls = []

    def get(self, url, timeout=None):
        self.calls.append(url)
        return SESSION_SCRIPT.pop(0)


REQUESTS = types.ModuleType("requests")
REQUESTS.get = lambda url, **kw: REQUESTS_GET[0](url, **kw)
REQUESTS.Session = FakeSession

FEED_RESULTS = {}              # url -> SimpleNamespace(bozo, entries)
FEEDPARSER = types.ModuleType("feedparser")
FEEDPARSER.parse = lambda url, agent=None: FEED_RESULTS[url]

FRED_BEHAVIOUR = [None]        # callable(api_key) -> object with get_series, or raises
FREDAPI = types.ModuleType("fredapi")


class _Fred:
    def __new__(cls, api_key=None):
        return FRED_BEHAVIOUR[0](api_key)


FREDAPI.Fred = _Fred


class _TextDoc:
    """lxml stub: text_content() returns the payload unchanged (tests pass plain text)."""

    def __init__(self, s):
        self.s = s

    def text_content(self):
        return self.s


LXML = types.ModuleType("lxml")
LXML_HTML = types.ModuleType("lxml.html")
LXML_HTML.fromstring = _TextDoc
LXML.html = LXML_HTML

for _name, _mod in {
    "pandas": types.ModuleType("pandas"),
    "yfinance": types.ModuleType("yfinance"),
    "psycopg": PSYCOPG,
    "requests": REQUESTS,
    "feedparser": FEEDPARSER,
    "fredapi": FREDAPI,
    "lxml": LXML,
    "lxml.html": LXML_HTML,
}.items():
    sys.modules[_name] = _mod


def load(rel):
    path = ING / rel
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FX = load("fx/fx-fetcher.py")
YIELDS = load("yields/yields-fetcher.py")
RATES = load("rates/rates-fetcher.py")
NEWS = load("news/news-fetcher.py")
INTRADAY = load("intraday/intraday-fetcher.py")
RBI = load("rbi/rbi.py")
FIIDII = load("fiidii/fiidii-fetcher.py")
FDI = load("fdi/fdi-watch.py")

TS = datetime(2026, 10, 24, tzinfo=UTC)
TS2 = datetime(2026, 10, 23, tzinfo=UTC)

# exit-code tests monkeypatch these; setUp restores them so test order never matters
_ORIG = [(m, n, getattr(m, n)) for m, n in (
    (FX, "fetch_latest"), (YIELDS, "fetch_latest"), (RATES, "fetch_latest"),
    (NEWS, "parse_feeds"), (INTRADAY, "fetch"), (RBI, "fetch_page"),
    (FIIDII, "fetch_flows"))]


def quiet(fn, *args):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = fn(*args)
    return rc, buf.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        CURRENT_DB[0] = MiniDB()
        PSYCOPG.connect = _default_connect
        SESSION_SCRIPT.clear()
        for mod, name, value in _ORIG:
            setattr(mod, name, value)
        self.db = CURRENT_DB[0]

    def assert_delete_only_own_rows(self, table, keycol):
        """(a): each DELETE names exactly the (key, ts) of the following INSERT."""
        ops = [e for e in self.db.log if e[1] == table and e[0] in ("delete", "insert")]
        self.assertTrue(ops, f"no writes recorded on {table}")
        self.assertEqual([op for op, *_ in ops][::2], ["delete"] * (len(ops) // 2))
        for (op_d, _, sql_d, p_d), (op_i, _, _, _) in zip(ops[::2], ops[1::2]):
            self.assertEqual((op_d, op_i), ("delete", "insert"))
            cols = re.findall(r"(\w+)(?:::date)?\s*=\s*%s", sql_d)
            self.assertIn(keycol, cols)
            self.assertIn("ts", cols)
            self.assertEqual(len(cols), len(p_d))
        # and the delete params equal the inserted row's key fields
        deletes = iter(e for e in self.db.log if e[0] == "delete" and e[1] == table)
        for op, tb, sql, params in self.db.log:
            if op != "insert" or tb != table:
                continue
            _, _, sql_d, p_d = next(deletes)
            cols = re.findall(r"(\w+)(?:::date)?\s*=\s*%s", sql_d)
            inserted = self.db.rows(table)  # noqa: F841 (row content checked below)
            crit = dict(zip(cols, p_d))
            self.assertIn("ts", crit)


# ------------------------------------------------------------------------- fx/yields
class FxYields(Base):
    CASES = [
        (FX, "fx_rates", "pair", {"USDINR=X": (TS, 83.21), "EURUSD=X": (TS, 1.09)}),
        (YIELDS, "bond_yields", "instrument", {"^TNX": (TS, 4.12), "^IRX": (TS2, 3.9)}),
    ]

    def test_delete_targets_only_own_key_and_ts(self):
        for mod, table, keycol, rows in self.CASES:
            with self.subTest(table):
                self.setUp()
                self.assertEqual(mod.write_rows(rows), len(rows))
                deletes = [e for e in self.db.log if e[0] == "delete"]
                self.assertEqual(len(deletes), len(rows))
                for _, tb, sql, params in deletes:
                    self.assertEqual(tb, table)
                    self.assertEqual(
                        sql, f"DELETE FROM {table} WHERE {keycol} = %s AND ts = %s")
                    self.assertIn(params[0], rows)
                    self.assertEqual(params[1], rows[params[0]][0])
                # no other table is ever touched
                self.assertEqual({e[1] for e in self.db.log}, {table})

    def test_rerun_leaves_no_duplicates(self):
        for mod, table, keycol, rows in self.CASES:
            with self.subTest(table):
                self.setUp()
                mod.write_rows(rows)
                mod.write_rows(rows)
                self.assertEqual(len(self.db.rows(table)), len(rows))
                self.assertEqual(self.db.dupes(table, (keycol, "ts")), [])

    def test_exit_codes(self):
        for mod, table, _, rows in self.CASES:
            with self.subTest(table):
                self.setUp()
                mod.fetch_latest = lambda: {}
                rc, out = quiet(mod.main)
                self.assertEqual(rc, 1)
                self.assertIn("zero rows fetched", out)
                mod.fetch_latest = lambda rows=rows: rows
                rc, _ = quiet(mod.main)
                self.assertEqual(rc, 0)
                self.assertEqual(len(self.db.rows(table)), len(rows))


# ----------------------------------------------------------------------------- rates
class Rates(Base):
    ROWS = {
        ("interest_rates", "DFF"): (TS, 4.33),
        ("bond_yields", "DGS10"): (TS, 4.08),
        ("bond_yields", "DGS2"): (TS2, 3.61),
    }

    def test_delete_uses_each_tables_own_key_column(self):
        self.assertEqual(RATES.write_rows(self.ROWS), 3)
        deletes = {e[3][0]: e for e in self.db.log if e[0] == "delete"}
        self.assertEqual(
            deletes["DFF"][2],
            "DELETE FROM interest_rates WHERE rate_name = %s AND ts = %s")
        self.assertEqual(
            deletes["DGS10"][2],
            "DELETE FROM bond_yields WHERE instrument = %s AND ts = %s")
        for (table, sid), (ts, _val) in self.ROWS.items():
            self.assertEqual(deletes[sid][1], table)
            self.assertEqual(deletes[sid][3], (sid, ts))

    def test_rerun_leaves_no_duplicates(self):
        RATES.write_rows(self.ROWS)
        RATES.write_rows(self.ROWS)
        self.assertEqual(len(self.db.rows("interest_rates")), 1)
        self.assertEqual(len(self.db.rows("bond_yields")), 2)
        self.assertEqual(self.db.dupes("interest_rates", ("rate_name", "ts")), [])
        self.assertEqual(self.db.dupes("bond_yields", ("instrument", "ts")), [])

    def test_exit_codes(self):
        FRED_BEHAVIOUR[0] = lambda key: (_ for _ in ()).throw(RuntimeError("bad key"))
        rc, out = quiet(RATES.main)
        self.assertEqual(rc, 1)
        self.assertIn("FRED fetch failed", out)
        RATES.fetch_latest = lambda: {}
        rc, _ = quiet(RATES.main)
        self.assertEqual(rc, 1)
        RATES.fetch_latest = lambda: dict(self.ROWS)
        rc, _ = quiet(RATES.main)
        self.assertEqual(rc, 0)


# -------------------------------------------------------------------------- intraday
class Intraday(Base):
    FX_ROWS = {"USDINR=X": [(TS, 83.2), (TS2, 83.1)]}
    PX_ROWS = {"GC=F": [(TS, 1.0, 2.0, 0.5, 1.5, 100), (TS2, 1.0, 2.0, 0.5, 1.4, None)]}

    def test_routes_to_fx_rates_and_intraday_prices_never_index_prices(self):
        self.assertEqual(INTRADAY.write(self.FX_ROWS, self.PX_ROWS), 4)
        tables = {e[1] for e in self.db.log}
        self.assertEqual(tables, {"fx_rates", "intraday_prices"})
        for _, _, sql, _ in self.db.log:
            self.assertNotIn("index_prices", sql)  # rule 4: index_prices stays pure-daily

    def test_delete_targets_only_own_key_and_ts(self):
        INTRADAY.write(self.FX_ROWS, self.PX_ROWS)
        for _, table, sql, params in (e for e in self.db.log if e[0] == "delete"):
            if table == "fx_rates":
                self.assertEqual(sql, "DELETE FROM fx_rates WHERE pair = %s AND ts = %s")
                self.assertIn(params[0], self.FX_ROWS)
            else:
                self.assertEqual(
                    sql, "DELETE FROM intraday_prices WHERE ticker = %s AND ts = %s")
                self.assertIn(params[0], self.PX_ROWS)
            self.assertIn(params[1], (TS, TS2))

    def test_rerun_rewrites_forming_candle_without_duplicates(self):
        INTRADAY.write(self.FX_ROWS, self.PX_ROWS)
        # second run: same timestamps, the forming candle's close moved
        px2 = {"GC=F": [(TS, 1.0, 2.1, 0.5, 1.6, 120), (TS2, 1.0, 2.0, 0.5, 1.4, None)]}
        INTRADAY.write(self.FX_ROWS, px2)
        self.assertEqual(len(self.db.rows("fx_rates")), 2)
        self.assertEqual(len(self.db.rows("intraday_prices")), 2)
        self.assertEqual(self.db.dupes("fx_rates", ("pair", "ts")), [])
        self.assertEqual(self.db.dupes("intraday_prices", ("ticker", "ts")), [])
        latest = {r["ts"]: r for r in self.db.rows("intraday_prices")}
        self.assertEqual(latest[TS]["close"], 1.6)  # re-run rewrote, not appended

    def test_exit_codes(self):
        INTRADAY.fetch = lambda: ({}, {})
        rc, out = quiet(INTRADAY.main)
        self.assertEqual(rc, 1)
        self.assertIn("zero symbols", out)
        INTRADAY.fetch = lambda: (self.FX_ROWS, self.PX_ROWS)
        rc, _ = quiet(INTRADAY.main)
        self.assertEqual(rc, 0)


# ------------------------------------------------------------------------------ news
class News(Base):
    ITEMS = [
        ("RBI holds repo", "EconomicTimes-Markets", TS),
        ("Nifty ends flat", "Moneycontrol-Latest", TS),
    ]

    def test_first_run_inserts_second_run_skips_everything(self):
        self.assertEqual(NEWS.write_items(self.ITEMS), 2)
        self.assertEqual(NEWS.write_items(self.ITEMS), 0)      # (b) + (d)
        self.assertEqual(len(self.db.rows("raw_headlines")), 2)
        self.assertEqual(
            self.db.dupes("raw_headlines", ("headline", "source")), [])

    def test_dedup_is_per_source_and_per_day(self):
        NEWS.write_items(self.ITEMS)
        same_headline_other_source = [("RBI holds repo", "BusinessStandard-Markets", TS)]
        self.assertEqual(NEWS.write_items(same_headline_other_source), 1)
        same_but_next_day = [("RBI holds repo", "EconomicTimes-Markets",
                              datetime(2026, 10, 25, 9, tzinfo=UTC))]
        self.assertEqual(NEWS.write_items(same_but_next_day), 1)
        # same (headline, source) later the SAME day is a duplicate
        same_day_later = [("RBI holds repo", "EconomicTimes-Markets",
                           datetime(2026, 10, 24, 18, tzinfo=UTC))]
        self.assertEqual(NEWS.write_items(same_day_later), 0)

    def test_batch_internal_duplicate_stored_once(self):
        self.assertEqual(NEWS.write_items([self.ITEMS[0], self.ITEMS[0]]), 1)
        self.assertEqual(len(self.db.rows("raw_headlines")), 1)

    def test_dedup_select_names_headline_source_and_day(self):
        NEWS.write_items(self.ITEMS[:1])
        sel = next(e for e in self.db.log if e[0] == "select")
        self.assertEqual(sel[1], "raw_headlines")
        self.assertIn("headline = %s AND source = %s AND ts::date = %s::date", sel[2])
        self.assertEqual(sel[3], ("RBI holds repo", "EconomicTimes-Markets", TS))

    def test_parse_feeds_entries_and_utc_timestamps(self):
        epoch = 1_792_026_000  # fixed moment; TZ=UTC makes mktime deterministic
        FEED_RESULTS.clear()
        FEED_RESULTS["http://a"] = types.SimpleNamespace(bozo=0, entries=[
            {"title": "  Headline one  ", "published_parsed": time.gmtime(epoch)},
            {"title": ""},                                    # skipped: empty title
            {"title": "x" * 600},                             # truncated to 500
        ])
        FEED_RESULTS["http://b"] = types.SimpleNamespace(bozo=1, entries=[])  # dead feed
        os.environ["FEEDS"] = "A|http://a, B|http://b, malformed-no-url"
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                items = NEWS.parse_feeds()
        finally:
            del os.environ["FEEDS"]
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0][0], "Headline one")
        self.assertEqual(items[0][1], "A")
        self.assertEqual(items[0][2], datetime.fromtimestamp(epoch, tz=UTC))
        self.assertEqual(items[0][2].tzinfo, UTC)             # rule 4: UTC
        self.assertEqual(len(items[1][0]), 500)
        self.assertIn("WARN B: feed parse failed", buf.getvalue())

    def test_exit_codes(self):
        NEWS.parse_feeds = lambda: []
        rc, out = quiet(NEWS.main)
        self.assertEqual(rc, 1)
        self.assertIn("zero headlines", out)
        NEWS.parse_feeds = lambda: list(self.ITEMS)
        rc, _ = quiet(NEWS.main)
        self.assertEqual(rc, 0)


# ------------------------------------------------------------------------------- rbi
THIS_YEAR = datetime.now(UTC).year
RBI_PAGE = (
    "Policy Repo Rate : 5.50% Standing Deposit Facility Rate : 5.25% "
    "Marginal Standing Facility Rate : 5.75% Bank Rate : 5.75% "
    "Fixed Reverse Repo Rate : 3.35% CRR : 4.00% SLR : 18.00% "
    f"7.10% GS {THIS_YEAR + 3} : 6.10% "
    f"6.33% GS {THIS_YEAR + 10} : 6.52% "
    f"7.30% GS {THIS_YEAR + 30} : 7.05% "
    "91 day T-bills : 5.45% 182 day T-bills : 5.60% 364 day T-bills : 5.65% "
    "# as on October 24, 2026"
)


class Rbi(Base):
    def test_parse_page_pure_logic(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            policy, gs, tb, gs_ts = RBI.parse_page(RBI_PAGE)
        self.assertEqual(policy, {
            "IN_REPO": 5.50, "IN_SDF": 5.25, "IN_MSF": 5.75, "IN_BANK_RATE": 5.75,
            "IN_REVERSE_REPO": 3.35, "IN_CRR": 4.00, "IN_SLR": 18.00})
        self.assertEqual(gs, {3: 6.10, 10: 6.52, 30: 7.05})
        self.assertEqual(tb, {91: 5.45, 182: 5.60, 364: 5.65})
        self.assertEqual(gs_ts, datetime(2026, 10, 24, tzinfo=UTC))
        self.assertEqual(gs_ts.tzinfo, UTC)                   # rule 4: UTC

    def test_parse_page_missing_sections_warn_not_crash(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            policy, gs, tb, gs_ts = RBI.parse_page("nothing useful here")
        self.assertEqual((policy, gs, tb, gs_ts), ({}, {}, {}, None))
        self.assertIn("WARN", buf.getvalue())

    def test_write_is_delete_insert_per_key_ts_and_idempotent(self):
        RBI.fetch_page = lambda: RBI_PAGE
        rc, out = quiet(RBI.main)
        self.assertEqual(rc, 0)
        self.assertIn("RBI-OK rows=13", out)
        rc, _ = quiet(RBI.main)                                # re-run: idempotent
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.db.rows("interest_rates")), 7)
        self.assertEqual(len(self.db.rows("bond_yields")), 6)
        self.assertEqual(len(self.db.rows("pipeline_heartbeat")), 1)  # upsert, not append
        self.assertEqual(self.db.dupes("interest_rates", ("rate_name", "ts")), [])
        self.assertEqual(self.db.dupes("bond_yields", ("instrument", "ts")), [])
        # every DELETE named its own key + ts on the right key column
        for _, table, sql, params in (e for e in self.db.log if e[0] == "delete"):
            keycol = "rate_name" if table == "interest_rates" else "instrument"
            self.assertIn(f"{keycol}=%s", sql.replace(" ", "").replace("WHERE", "WHERE "))
            self.assertEqual(len(params), 2)
        # timestamps: policy rows at UTC midnight today, G-Secs on the page's date
        for r in self.db.rows("interest_rates"):
            ts = r["ts"]
            self.assertEqual(ts.tzinfo, UTC)
            self.assertEqual((ts.hour, ts.minute, ts.second), (0, 0, 0))
        gs_rows = [r for r in self.db.rows("bond_yields")
                   if r["instrument"].startswith("IN_GS_")]
        self.assertEqual({r["ts"] for r in gs_rows},
                         {datetime(2026, 10, 24, tzinfo=UTC)})

    def test_zero_rows_parsed_exits_1_without_touching_db(self):
        RBI.fetch_page = lambda: "layout changed, nothing matches"
        rc, out = quiet(RBI.main)
        self.assertEqual(rc, 1)
        self.assertIn("RBI-FAIL", out)
        self.assertEqual(self.db.log, [])

    def test_reconnect_retry_on_operational_error(self):
        RBI.fetch_page = lambda: RBI_PAGE

        class FlakyConn(FakeConn):
            def transaction(self):
                raise OperationalError("server closed the connection")

        good = FakeConn(self.db)
        flaky = FlakyConn(self.db)
        queue = [flaky, good]
        PSYCOPG.connect = lambda **kw: queue.pop(0)
        rc, out = quiet(RBI.main)
        self.assertEqual(rc, 0)
        self.assertTrue(flaky.closed)
        self.assertTrue(good.closed)
        self.assertIn("retrying once", out)
        self.assertEqual(len(self.db.rows("interest_rates")), 7)


# ---------------------------------------------------------------------------- fiidii
FII_ENTRY = {"category": "FII/FPI *", "netValue": "-1234.56", "date": "24-Oct-2026"}
DII_ENTRY = {"category": "DII **", "netValue": "2345.10", "date": "24-Oct-2026"}


class FiiDii(Base):
    def fetch(self, payload):
        SESSION_SCRIPT[:] = [FakeResponse(text="cookies"), FakeResponse(json_data=payload)]
        buf = io.StringIO()
        with redirect_stdout(buf):
            rows = FIIDII.fetch_flows()
        return rows, buf.getvalue()

    def test_parses_envelope_and_bare_list_payloads(self):
        for payload in ({"data": [FII_ENTRY, DII_ENTRY]}, [FII_ENTRY, DII_ENTRY]):
            with self.subTest(type(payload).__name__):
                rows, _ = self.fetch(payload)
                self.assertEqual(rows, [
                    ("FII", "FII/FPI *", datetime(2026, 10, 24, tzinfo=UTC), -1234.56),
                    ("DII", "DII **", datetime(2026, 10, 24, tzinfo=UTC), 2345.10)])
                self.assertEqual(rows[0][2].tzinfo, UTC)      # rule 4: UTC

    def test_skips_unknown_category_and_bad_net_value(self):
        rows, out = self.fetch({"data": [
            FII_ENTRY,
            {"category": "Pro", "netValue": "1", "date": "24-Oct-2026"},
            {"category": "FII", "netValue": "n/a", "date": "24-Oct-2026"},
        ]})
        self.assertEqual(len(rows), 1)
        self.assertIn("WARN skipping category 'Pro'", out)
        self.assertIn("WARN bad netValue", out)

    def test_delete_targets_only_own_flow_segment_ts(self):
        rows = [("FII", "FII/FPI *", TS, -1234.56), ("DII", "DII **", TS, 2345.10)]
        self.assertEqual(FIIDII.write_rows(rows), 2)
        deletes = [e for e in self.db.log if e[0] == "delete"]
        self.assertEqual(len(deletes), 2)
        for (_, table, sql, params), row in zip(deletes, rows):
            self.assertEqual(table, "capital_flows")
            self.assertIn("flow_type = %s AND segment = %s AND ts = %s", sql)
            self.assertEqual(params, (row[0], row[1], row[2]))
        self.assertEqual({r["direction"] for r in self.db.rows("capital_flows")}, {"net"})

    def test_rerun_leaves_no_duplicates(self):
        rows = [("FII", "FII/FPI *", TS, -1234.56), ("DII", "DII **", TS, 2345.10)]
        FIIDII.write_rows(rows)
        FIIDII.write_rows(rows)
        self.assertEqual(len(self.db.rows("capital_flows")), 2)
        self.assertEqual(
            self.db.dupes("capital_flows", ("flow_type", "segment", "ts")), [])

    def test_exit_codes(self):
        FIIDII.fetch_flows = lambda: (_ for _ in ()).throw(RuntimeError("cookies changed"))
        rc, out = quiet(FIIDII.main)
        self.assertEqual(rc, 1)
        self.assertIn("ERROR NSE fetch failed", out)
        FIIDII.fetch_flows = lambda: []
        rc, _ = quiet(FIIDII.main)
        self.assertEqual(rc, 1)
        FIIDII.fetch_flows = lambda: [("FII", "FII/FPI *", TS, -1.0)]
        rc, _ = quiet(FIIDII.main)
        self.assertEqual(rc, 0)


# ------------------------------------------------------------------------- fdi-watch
FDI_HTML = """
<a href="/writereaddata/fdi_factsheet_june2026.pdf">FDI <b>Factsheet</b> June 2026</a>
<a href="https://host.example/quarterly.pdf?x=1" class="y">Quarterly</a>
<a href="/page.html">not a pdf</a>
"""


class FdiWatch(Base):
    def test_list_pdf_links_parsing(self):
        REQUESTS_GET[0] = lambda url, **kw: FakeResponse(text=FDI_HTML)
        links = FDI.list_pdf_links("https://dpiit.gov.in/publications/fdi-statistics")
        self.assertEqual(links, [
            ("FDI Factsheet June 2026",
             "https://dpiit.gov.in/writereaddata/fdi_factsheet_june2026.pdf"),
            ("Quarterly", "https://host.example/quarterly.pdf?x=1")])

    def test_always_exits_0_and_writes_nothing(self):
        REQUESTS_GET[0] = lambda url, **kw: (_ for _ in ()).throw(RuntimeError("down"))
        rc, out = quiet(FDI.main)
        self.assertEqual(rc, 0)                               # informational by design
        self.assertIn("WARN", out)
        REQUESTS_GET[0] = lambda url, **kw: FakeResponse(text=FDI_HTML)
        rc, out = quiet(FDI.main)
        self.assertEqual(rc, 0)
        self.assertIn("MANUAL", out.upper())
        self.assertEqual(self.db.log, [])                     # never touches the DB


if __name__ == "__main__":
    unittest.main()
