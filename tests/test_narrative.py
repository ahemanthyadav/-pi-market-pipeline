#!/usr/bin/env python3
"""ML-7a narrative: the number check and the retry/degrade logic. No network, no DB.

    python3 tests/test_narrative.py
"""
import sys
import types
import unittest
from pathlib import Path

sys.modules.setdefault("psycopg", types.ModuleType("psycopg"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "manifests" / "llm"))
import narrative as n  # noqa: E402

FACTS = {"indices": [{"name": "Nifty 50", "close": 22363.35, "change_pct": -1.21},
                     {"name": "India VIX", "close": 18.4, "change_pct": 6.5}],
         "fx": {"usd_inr": 88.12, "change_pct": 0.15}, "flows_rs_cr": {"FII": -5012, "DII": 3890},
         "sentiment_7d": -0.08}


class NumberCheck(unittest.TestCase):
    def test_faithful_text_passes(self):
        t = "Nifty 50 fell 1.21% to 22,363.35 as FIIs sold Rs 5,012 crore while DIIs bought 3,890; VIX rose 6.5% to 18.4."
        self.assertEqual(n.bad_numbers(t, FACTS), [])

    def test_invented_or_recomputed_numbers_are_caught(self):
        self.assertEqual(n.bad_numbers("Nifty fell 1.5% to 22,363.35.", FACTS), ["1.5"])
        self.assertEqual(n.bad_numbers("Net flows were -1,122 crore.", FACTS), ["-1,122"])   # sum not in facts

    def test_rounding_and_small_counts_allowed(self):
        self.assertEqual(n.bad_numbers("Nifty dropped 1.2% to about 22,363; two of 3 indices fell.", FACTS), [])

    def test_unicode_minus_and_plus(self):
        self.assertEqual(n.bad_numbers("Sentiment −0.08, rupee +0.15%.", FACTS), [])


class Fences(unittest.TestCase):
    def test_code_block_is_removed(self):
        self.assertEqual(n.strip_fences('```json\n{"summary": "x"}\n```'), '{"summary": "x"}')
        self.assertEqual(n.strip_fences('{"summary": "x"}'), '{"summary": "x"}')


class Narrate(unittest.TestCase):
    def test_ok_first_try(self):
        st, s, model, attempts, _ = n.narrate(FACTS, lambda m: ("Nifty 50 fell 1.21%.", "m1"))
        self.assertEqual((st, attempts, model), ("ok", 1, "m1"))

    def test_retry_then_ok_and_retry_message_names_bad_numbers(self):
        seen = []

        def asker(msgs):
            seen.append(msgs)
            return ("Nifty fell 9.99%." if len(seen) == 1 else "Nifty 50 fell 1.21%."), "m1"
        st, s, _, attempts, _ = n.narrate(FACTS, asker)
        self.assertEqual((st, attempts), ("ok", 2))
        self.assertIn("9.99", seen[1][-1]["content"])

    def test_invalid_after_two_bad_answers_never_stores_text(self):
        st, s, _, attempts, detail = n.narrate(FACTS, lambda m: ("Nifty fell 9.99%.", "m1"))
        self.assertEqual((st, s, attempts), ("invalid", None, 2))
        self.assertIn("9.99", detail)

    def test_gateway_down_is_unavailable_not_a_crash(self):
        def asker(msgs):
            raise RuntimeError("unavailable: connection refused")
        st, s, *_ = n.narrate(FACTS, asker)
        self.assertEqual((st, s), ("unavailable", None))


class Bakeoff(unittest.TestCase):
    def setUp(self):
        import bakeoff
        self.b = bakeoff

    def test_run_one_records_first_try_and_final(self):
        calls = []

        def asker(msgs, model):
            calls.append(model)
            return ("Nifty fell 9.99%." if len(calls) == 1 else "Nifty 50 fell 1.21%."), model
        r = self.b.run_one(FACTS, "fast-json.2", asker)
        self.assertEqual((r["first_ok"], r["final_ok"], r["error"]), (False, True, ""))
        self.assertEqual(calls, ["fast-json.2", "fast-json.2"])   # the candidate is pinned per call

    def test_score_and_errors(self):
        res = [{"first_ok": True, "final_ok": True, "latency": 2.0, "error": ""},
               {"first_ok": False, "final_ok": True, "latency": 4.0, "error": ""},
               {"first_ok": False, "final_ok": False, "latency": None, "error": "unavailable"}]
        self.assertEqual(self.b.score(res), {"runs": 3, "first_try_pass": 0.33, "final_pass": 0.67,
                                             "errors": 1, "median_latency_s": 3.0})


if __name__ == "__main__":
    unittest.main(verbosity=1)
