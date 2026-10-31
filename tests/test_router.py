#!/usr/bin/env python3
"""Tests for manifests/telegram/router.py — natural-language command router.

No database, no network: pure string matching.

    python3 tests/test_router.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "manifests" / "telegram"))
import router  # noqa: E402


class RouteTest(unittest.TestCase):
    def test_exact_command(self):
        cmd, args, conf = router.route("/stock TCS")
        self.assertEqual(cmd, "stock")
        self.assertEqual(args, "TCS")
        self.assertEqual(conf, "exact")

    def test_price_of(self):
        cmd, args, conf = router.route("price of TCS")
        self.assertEqual(cmd, "stock")
        self.assertEqual(args, "TCS")
        self.assertEqual(conf, "phrase")

    def test_price_for(self):
        cmd, args, conf = router.route("quote for apple")
        self.assertEqual(cmd, "stock")
        self.assertEqual(args, "apple")
        self.assertEqual(conf, "phrase")

    def test_tcs_price_keyword_first(self):
        cmd, args, conf = router.route("tcs price")
        # "tcs" is both a nickname (TCS.NS) and keyword context; nickname wins
        self.assertEqual(cmd, "stock")
        self.assertEqual(args, "TCS.NS")
        self.assertEqual(conf, "nickname")

    def test_price_tcs_keyword_second(self):
        cmd, args, conf = router.route("price tcs")
        self.assertEqual(cmd, "stock")
        self.assertEqual(args, "TCS.NS")
        self.assertEqual(conf, "keyword")

    def test_facebook_nickname(self):
        cmd, args, conf = router.route("facebook price")
        self.assertEqual(cmd, "stock")
        self.assertEqual(args, "META")
        self.assertEqual(conf, "nickname")

    def test_big_blue_nickname(self):
        cmd, args, conf = router.route("big blue price")
        self.assertEqual(cmd, "stock")
        self.assertEqual(args, "IBM")
        self.assertEqual(conf, "nickname")

    def test_nifty_keyword(self):
        cmd, args, conf = router.route("nifty level")
        # "nifty level" matches a phrase route → /nifty command
        self.assertEqual(cmd, "nifty")
        self.assertEqual(args, "")
        self.assertEqual(conf, "phrase")

    def test_fii_flows_phrase(self):
        cmd, args, conf = router.route("show me fii flows")
        self.assertEqual(cmd, "fii")
        self.assertEqual(args, "")
        self.assertEqual(conf, "phrase")

    def test_my_watchlist_phrase(self):
        cmd, args, conf = router.route("my watchlist")
        self.assertEqual(cmd, "watch")
        self.assertEqual(args, "")
        self.assertEqual(conf, "phrase")

    def test_top_growth_sp500_phrase(self):
        cmd, args, conf = router.route("top growth sp500")
        self.assertEqual(cmd, "top")
        self.assertEqual(args, "growth sp500")
        self.assertEqual(conf, "phrase")

    def test_daily_digest_phrase(self):
        cmd, args, conf = router.route("daily digest")
        self.assertEqual(cmd, "digest")
        self.assertEqual(args, "")
        self.assertEqual(conf, "phrase")

    def test_single_word_nickname(self):
        cmd, args, conf = router.route("apple")
        self.assertEqual(cmd, "stock")
        self.assertEqual(args, "AAPL")
        self.assertEqual(conf, "nickname")

    def test_single_word_keyword(self):
        cmd, args, conf = router.route("vix")
        self.assertEqual(cmd, "stock")
        self.assertEqual(args, "^VIX")
        self.assertEqual(conf, "nickname")

    def test_unknown_returns_none(self):
        cmd, args, conf = router.route("random gibberish xyz")
        self.assertIsNone(cmd)
        self.assertIsNone(args)
        self.assertIsNone(conf)

    def test_empty_returns_none(self):
        cmd, args, conf = router.route("")
        self.assertIsNone(cmd)
        self.assertIsNone(args)
        self.assertIsNone(conf)

    def test_format_route(self):
        out = router.format_route("stock", "TCS", "nickname")
        self.assertIn("/stock", out)
        self.assertIn("TCS", out)
        self.assertIn("nickname", out)


if __name__ == "__main__":
    unittest.main()
