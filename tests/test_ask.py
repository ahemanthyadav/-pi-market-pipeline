#!/usr/bin/env python3
"""ask.py: fact-gathering, the number/direction gate, and the degrade-to-facts path. No network, no DB.

    python3 tests/test_ask.py
"""
import os
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
pg = types.ModuleType("psycopg")
pg.Error = type("Error", (Exception,), {})
sys.modules.setdefault("psycopg", pg)
sys.modules.setdefault("requests", types.ModuleType("requests"))
sys.path.insert(0, str(ROOT / "manifests" / "telegram"))
import ask  # noqa: E402
import resolver  # noqa: E402

FACTS = {"symbol": "INFY.NS", "name": "Infosys Ltd.", "sector": "IT", "universe": "NIFTY500",
         "metrics": {"close": 1500.0, "ret_1m": -0.05, "pe": 24.0}}


ROW = ("INFY.NS", "Infosys Ltd.", "IT", "NIFTY500", "INR")

def fake_q(sql, args=()):
    if "upper(symbol) = ANY" in sql:
        return [ROW]
    if "stock_metrics_daily" in sql:
        return [("close", 1500.0), ("ret_1m", -0.05), ("pe", 24.0)]
    if "stock_scores" in sql:
        return [("composite", 12)]
    if "raw_headlines" in sql:
        return [("Infosys wins a 500M dollar deal", "2026-10-16")]
    return []


class Gate(unittest.TestCase):
    def setUp(self):
        resolver._universe.update(rows=None, at=0.0)
        os.environ.pop("BOT_AI_RESOLVE", None)

    def test_clean_answer_passes(self):
        out = ask.answer(fake_q, "TCS", asker=lambda m: "Infosys trades at 24 P/E, down 5% over the month.")
        self.assertIn("Infosys trades at 24 P/E", out)

    def test_invented_number_fails_then_retries(self):
        answers = iter(["Infosys trades at 26 P/E.", "Infosys trades at 24 P/E."])
        out = ask.answer(fake_q, "TCS", asker=lambda m: next(answers))
        self.assertIn("24 P/E", out)

    def test_two_failures_show_the_facts_not_the_prose(self):
        out = ask.answer(fake_q, "TCS", asker=lambda m: "Infosys trades at 26 P/E.")
        self.assertIn("the facts themselves", out)
        self.assertIn("24.0", out)
        self.assertNotIn("26 P/E", out)

    def test_gateway_down_degrades_to_facts(self):
        def down(m):
            raise ConnectionError("gateway down")
        out = ask.answer(fake_q, "TCS", asker=down)
        self.assertIn("the facts themselves", out)

    def test_question_about_a_stock_uses_the_symbol_not_the_whole_phrase(self):
        facts, subj = ask.build_facts(fake_q, "TCS outlook")
        self.assertEqual((facts["symbol"], subj), ("INFY.NS", "INFY.NS"))

    def test_question_with_no_facts_is_refused_not_guessed(self):
        out = ask.answer(lambda sql, args=(): [], "what is the weather", asker=lambda m: self.fail("called"))
        self.assertIn("can only answer", out)

    def test_news_headlines_pass_numbers_only(self):
        # headline text has no sign context: a number quoted from a headline must not need a sign match
        facts = {"headlines": ["Infosys wins a 500M dollar deal"]}
        bad = ask.factcheck.bad_numbers("Infosys won a 500M dollar deal.", facts)
        self.assertEqual(bad, [])
        def news_only(sql, args=()):
            return [("Infosys wins a 500M dollar deal", "2026-10-16")] if "raw_headlines" in sql else []
        out = ask.answer(news_only, "news infosys", asker=lambda m: "Infosys won a 500M dollar deal.")
        self.assertIn("500M", out)


if __name__ == "__main__":
    unittest.main(verbosity=1)
