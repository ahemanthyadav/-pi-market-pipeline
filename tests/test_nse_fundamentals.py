#!/usr/bin/env python3
"""NSE fundamentals parsers (G-6) against REAL captured filings in tests/fixtures/nse/ (public data;
the XBRL fixture is trimmed to the contexts + tags we read). No network, no DB.

    python3 tests/test_nse_fundamentals.py
"""
import datetime as dt
import json
import sys
import types
import unittest
from pathlib import Path

for name in ("psycopg", "requests"):
    sys.modules.setdefault(name, types.ModuleType(name))
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "manifests" / "stock-screener" / "scripts"))
import nse_fundamentals as nf  # noqa: E402

FX = ROOT / "tests" / "fixtures" / "nse"
RECS = json.loads((FX / "list_records.json").read_text())   # TCS 2008, TCS 2014, TCS 2023, HDFCBANK 2008, HDFCBANK 2023


def as_dict(rows):
    return {m: v for m, s, e, v in rows}


class OldHtml(unittest.TestCase):
    def test_tcs_2008_quarter(self):
        rows = nf.parse_old_html(RECS[0], (FX / "old_tcs_2008q.html").read_text(errors="replace"))
        d = as_dict(rows)
        self.assertAlmostEqual(d["total_revenue"], 727704.00 * 1e5)       # "Income from Operation" (no s)
        self.assertAlmostEqual(d["net_income"], 136206.00 * 1e5)          # consolidated line preferred
        self.assertAlmostEqual(d["eps"], 13.92)
        self.assertAlmostEqual(d["finance_costs"], 1031.00 * 1e5)
        self.assertEqual({(s, e) for _m, s, e, _v in rows}, {(dt.date(2008, 10, 1), dt.date(2008, 12, 31))})

    def test_bank_page_uses_total_income_and_no_finance_cost(self):
        d = as_dict(nf.parse_old_html(RECS[3], (FX / "old_hdfcbank_2008q.html").read_text(errors="replace")))
        self.assertAlmostEqual(d["total_revenue"], 540789.00 * 1e5)
        self.assertAlmostEqual(d["net_income"], 62174.00 * 1e5)
        self.assertAlmostEqual(d["eps"], 14.60)
        self.assertNotIn("finance_costs", d)   # a bank's "interest" is its business, not a finance cost


class Json(unittest.TestCase):
    def test_tcs_2014(self):
        d = as_dict(nf.parse_json(RECS[1], json.loads((FX / "json_tcs_2014q.json").read_text())))
        self.assertAlmostEqual(d["total_revenue"], 2450114 * 1e5)
        self.assertAlmostEqual(d["net_income"], 532755 * 1e5)              # re_con_pro_loss first
        self.assertAlmostEqual(d["eps"], 27.2)
        self.assertAlmostEqual(d["profit_before_tax"], 721208 * 1e5)
        self.assertAlmostEqual(d["finance_costs"], 1798 * 1e5)

    def test_tcs_2023_new_format(self):
        d = as_dict(nf.parse_json(RECS[2], json.loads((FX / "json_tcs_2023q.json").read_text())))
        self.assertAlmostEqual(d["total_revenue"], 6058300 * 1e5)
        self.assertAlmostEqual(d["eps"], 30.29)

    def test_bank_revenue_is_total_income(self):
        d = as_dict(nf.parse_json(RECS[4], json.loads((FX / "json_hdfcbank_2023q.json").read_text())))
        self.assertAlmostEqual(d["total_revenue"], 11501551 * 1e5)
        self.assertAlmostEqual(d["net_income"], 1725787 * 1e5)
        self.assertNotIn("finance_costs", d)


class Xbrl(unittest.TestCase):
    def test_tcs_integrated_quarter_and_ytd(self):
        rec = json.loads((FX / "integrated_record.json").read_text())
        rows = nf.parse_xbrl((FX / "xbrl_tcs_integrated.xml").read_bytes(), nf._d(rec["qe_Date"]))
        rev = {(e - s).days: v for m, s, e, v in rows if m == "total_revenue"}
        self.assertEqual(rev, {91: 731880000000.0, 182: 1454630000000.0})   # quarter + year-to-date, rupees
        ni = {(e - s).days: v for m, s, e, v in rows if m == "net_income"}
        self.assertIn(91, ni)
        self.assertTrue(all(e == dt.date(2026, 9, 30) for _m, _s, e, _v in rows))  # no comparatives


class Plan(unittest.TestCase):
    def test_consolidated_preferred_standalone_only_when_missing(self):
        a = {"fromDate": "01-Oct-2008", "toDate": "31-Dec-2008"}
        recs = [("list", {**a, "consolidated": "Non-Consolidated", "seqNumber": "1"}),
                ("list", {**a, "consolidated": "Consolidated", "seqNumber": "2"}),
                ("list", {"fromDate": "01-Jul-2008", "toDate": "30-Sep-2008",
                          "consolidated": "Non-Consolidated", "seqNumber": "3"})]
        got = {r["seqNumber"]: src for _k, r, src in nf.plan(recs)}
        self.assertEqual(got, {"2": "nse_cons", "3": "nse_sa"})

    def test_restated_filing_of_same_period_is_kept(self):
        a = {"fromDate": "01-Apr-2015", "toDate": "31-Mar-2016", "consolidated": "Consolidated"}
        got = sorted(r["seqNumber"] for _k, r, _s in nf.plan([("list", {**a, "seqNumber": "1006219"}),
                                                              ("list", {**a, "seqNumber": "1020766"})]))
        self.assertEqual(got, ["1006219", "1020766"])   # original 2016 + Ind-AS restatement 2018

    def test_gross_income_preferred_over_net_sales(self):
        rec = {"bank": "N", "fromDate": "01-Apr-2013", "toDate": "31-Mar-2014"}
        d = as_dict(nf.parse_json(rec, {"resultsData": {"re_net_sale": "166952", "re_gro_inc": "8180936"}}))
        self.assertAlmostEqual(d["total_revenue"], 8180936 * 1e5)   # TCS FY2014

    def test_missing_filing_date_is_estimated_late(self):
        rec = {"filingDate": "-", "broadCastDate": "-", "exchdisstime": "-", "toDate": "31-Dec-2006"}
        self.assertEqual(nf.filed_on("list", rec), dt.date(2007, 3, 1))   # period end + 60 days
        self.assertEqual(nf.filed_on("list", {**rec, "broadCastDate": "20-Jan-2007 18:01:02"}), dt.date(2007, 1, 20))

    def test_dates_and_sentinels(self):
        self.assertEqual(nf._d("30-SEP-2026"), dt.date(2026, 9, 30))
        self.assertEqual(nf._d("21-Apr-2008 19:18"), dt.date(2008, 4, 21))
        self.assertIsNone(nf._f("-999.00"))
        self.assertIsNone(nf._f("-"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
