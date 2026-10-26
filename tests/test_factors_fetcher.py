"""Unit tests for the factor-returns fetcher (G-20) — no network, no DB.

    python3 tests/test_factors_fetcher.py

mdjob is stubbed BEFORE import (its own behavior is proven in test_mdjob.py);
requests is replaced with a scripted fake serving canned Ken French zips and
IIM-A CSVs. Proves: month-end timestamps, factor-name mapping (WML->MOM,
MF->MKT_RF), NA/sentinel skipping, the annual-section cut-off, and that main()
writes through write_window keyed on (market, factor, freq, ts).
"""
import importlib.util
import io
import sys
import types
import unittest
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FETCHER = ROOT / "manifests/ingestion/factors/factors-fetcher.py"

WRITES = []      # (table, key_cols, rows) every write_window call
RUNS = []        # job names


class _Run:
    rows = 0


class _Ctx:
    def __init__(self, name):
        RUNS.append(name)
        self.run = _Run()

    def __enter__(self):
        return self.run

    def __exit__(self, *exc):
        return False


MDJOB = types.ModuleType("mdjob")
MDJOB.connect = lambda: types.SimpleNamespace(close=lambda: None)
MDJOB.job_run = _Ctx
MDJOB.write_window = lambda conn, table, key_cols, rows, retry=True: (
    WRITES.append((table, list(key_cols), list(rows))) or (len(rows), conn))

KF_5F = """This file was created using the 202608 CRSP database.
Junk line two.

,Mkt-RF,SMB,HML,RMW,CMA,RF
196307,   -0.39,   -0.48,   -0.84,    0.64,   -1.15,    0.27
196308,    5.07,   -0.85,    1.67,  -99.99,   -0.40,    0.25

 Annual Factors: January-December
,Mkt-RF,SMB,HML,RMW,CMA,RF
1964,   16.0,    1.0,    2.0,    3.0,    4.0,    5.0
"""

KF_MOM = """Missing data are indicated by -99.99 or -999.

,Mom
196307,    1.01

 Annual Factors:
1964, 10.0
"""

IIMA_PAGE = '<a href="DATA/2025-12_FourFactors_and_Market_Returns_Monthly_SurvivorshipBiasAdjusted.csv">Monthly</a>'
IIMA_CSV = """Date,SMB,HML,WML,MF,RF
1993-10,2.98,2.58,3.01,NA,NA
1993-11,-9.42,-0.55,12.62,17.62,0.61
"""


def make_zip(text):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("data.csv", text)
    return buf.getvalue()


class FakeResponse:
    def __init__(self, content=b"", text=""):
        self.content, self.text = content, text

    def raise_for_status(self):
        return None


REQUESTS = types.ModuleType("requests")


def _get(url, headers=None, timeout=None):
    if url.endswith("F-F_Research_Data_5_Factors_2x3_CSV.zip"):
        return FakeResponse(content=make_zip(KF_5F))
    if url.endswith("F-F_Momentum_Factor_CSV.zip"):
        return FakeResponse(content=make_zip(KF_MOM))
    if url.endswith("_Monthly_SurvivorshipBiasAdjusted.csv"):
        return FakeResponse(text=IIMA_CSV)
    return FakeResponse(text=IIMA_PAGE)


REQUESTS.get = _get
sys.modules["requests"] = REQUESTS
sys.modules["mdjob"] = MDJOB

spec = importlib.util.spec_from_file_location("factors_fetcher", FETCHER)
ff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ff)


class ParseKenFrench(unittest.TestCase):
    def test_monthly_rows_month_end_ts_and_sentinel_skip(self):
        rows = ff.parse_kf(KF_5F, {"Mkt-RF": "MKT_RF", "RMW": "RMW", "RF": "RF"})
        by = {(ts, f): v for ts, f, v in rows}
        self.assertEqual(by[(date(1963, 7, 31), "MKT_RF")], -0.39)
        self.assertEqual(by[(date(1963, 8, 31), "MKT_RF")], 5.07)
        self.assertNotIn((date(1963, 8, 31), "RMW"), by)      # -99.99 sentinel skipped
        self.assertNotIn((date(1964, 12, 31), "MKT_RF"), by)  # annual section cut off
        self.assertTrue(all(f in ("MKT_RF", "RMW", "RF") for _, f in by))


class EndToEnd(unittest.TestCase):
    def setUp(self):
        WRITES.clear()
        RUNS.clear()

    def test_main_writes_both_markets_with_the_right_keys(self):
        rc = ff.main()
        self.assertEqual(rc, 0)
        self.assertEqual(RUNS, ["factors-fetcher"])
        table, key_cols, rows = WRITES[0]
        self.assertEqual(table, "factor_returns")
        self.assertEqual(key_cols, ["market", "factor", "freq", "ts"])
        markets = {r["market"] for r in rows}
        self.assertEqual(markets, {"US", "IN"})
        self.assertTrue(all(r["freq"] == "M" for r in rows))

    def test_iima_mapping_na_skip_and_month_end(self):
        ff.main()
        rows = [r for r in WRITES[0][2] if r["market"] == "IN"]
        by = {(r["ts"], r["factor"]): r["value"] for r in rows}
        self.assertEqual(by[(date(1993, 11, 30), "MOM")], 12.62)      # WML -> MOM
        self.assertEqual(by[(date(1993, 11, 30), "MKT_RF")], 17.62)   # MF -> MKT_RF
        self.assertNotIn((date(1993, 10, 31), "MKT_RF"), by)          # NA skipped
        self.assertEqual(by[(date(1993, 10, 31), "SMB")], 2.98)
        self.assertTrue(all(r["source"] == "iima" for r in rows))

    def test_us_momentum_file_contributes_mom(self):
        ff.main()
        rows = [r for r in WRITES[0][2]
                if r["market"] == "US" and r["factor"] == "MOM"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["value"], 1.01)
        self.assertEqual(rows[0]["ts"], date(1963, 7, 31))


if __name__ == "__main__":
    unittest.main()
