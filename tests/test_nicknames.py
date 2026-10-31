#!/usr/bin/env python3
"""Tests for manifests/telegram/nicknames.py — nickname → symbol map.

No database, no network.

    python3 tests/test_nicknames.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "manifests" / "telegram"))
import nicknames  # noqa: E402


class NicknameTest(unittest.TestCase):
    def test_known_india_nickname(self):
        self.assertEqual(nicknames.NICKNAMES["reliance"], "RELIANCE.NS")
        self.assertEqual(nicknames.NICKNAMES["tcs"], "TCS.NS")
        self.assertEqual(nicknames.NICKNAMES["hdfc bank"], "HDFCBANK.NS")
        self.assertEqual(nicknames.NICKNAMES["infosys"], "INFY.NS")

    def test_known_us_nickname(self):
        self.assertEqual(nicknames.NICKNAMES["apple"], "AAPL")
        self.assertEqual(nicknames.NICKNAMES["facebook"], "META")
        self.assertEqual(nicknames.NICKNAMES["big blue"], "IBM")
        self.assertEqual(nicknames.NICKNAMES["tesla"], "TSLA")

    def test_index_nickname(self):
        self.assertEqual(nicknames.NICKNAMES["nifty"], "^NSEI")
        self.assertEqual(nicknames.NICKNAMES["sensex"], "^BSESN")
        self.assertEqual(nicknames.NICKNAMES["vix"], "^VIX")
        self.assertEqual(nicknames.NICKNAMES["dow"], "^DJI")

    def test_commodity_fx_nickname(self):
        self.assertEqual(nicknames.NICKNAMES["gold"], "GC=F")
        self.assertEqual(nicknames.NICKNAMES["usdinr"], "USDINR=X")
        self.assertEqual(nicknames.NICKNAMES["dxy"], "DX-Y.NYB")

    def test_none_for_unknown(self):
        self.assertNotIn("randomcompany", nicknames.NICKNAMES)

    def test_command_aliases(self):
        self.assertEqual(nicknames.COMMAND_ALIASES["price"], "stock")
        self.assertEqual(nicknames.COMMAND_ALIASES["news"], "news")
        self.assertEqual(nicknames.COMMAND_ALIASES["fii"], "fii")

    def test_keyword_commands(self):
        self.assertEqual(nicknames.KEYWORD_COMMANDS["stock"], "stock")
        self.assertEqual(nicknames.KEYWORD_COMMANDS["vix"], "vix")
        self.assertEqual(nicknames.KEYWORD_COMMANDS["watch"], "watch")

    def test_phrase_routes(self):
        self.assertEqual(nicknames.PHRASE_ROUTES["price of"], ("stock", "{arg}"))
        self.assertEqual(nicknames.PHRASE_ROUTES["my watchlist"], ("watch", ""))
        self.assertEqual(nicknames.PHRASE_ROUTES["top growth"], ("top", "growth {arg}"))


if __name__ == "__main__":
    unittest.main()
