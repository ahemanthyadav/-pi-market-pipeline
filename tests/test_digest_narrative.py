#!/usr/bin/env python3
"""Digest v9: the optional AI summary section (ML-7a). No network, no DB.

    python3 tests/test_digest_narrative.py
"""
import os
import sys
import types
import unittest
from pathlib import Path

pg = types.ModuleType("psycopg")
pg.Error = type("Error", (Exception,), {})
sys.modules["psycopg"] = pg
sys.modules.setdefault("requests", types.ModuleType("requests"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "manifests" / "telegram"))
import digest  # noqa: E402


class Cur:
    def __init__(self, row=None, exc=None):
        self.row, self.exc, self.sql = row, exc, []

    def execute(self, sql, args=()):
        self.sql.append((sql, args))
        if self.exc:
            raise self.exc

    def fetchone(self):
        return self.row


class Narrative(unittest.TestCase):
    def setUp(self):
        os.environ["DIGEST_NARRATIVE"] = "1"

    def tearDown(self):
        os.environ.pop("DIGEST_NARRATIVE", None)

    def test_ok_note_is_returned_and_only_status_ok_is_queried(self):
        cur = Cur(("Nifty 50 fell 1.21%.",))
        self.assertEqual(digest.narrative(cur), "Nifty 50 fell 1.21%.")
        self.assertIn("status = 'ok'", cur.sql[0][0])

    def test_switched_off_means_no_query_at_all(self):
        os.environ["DIGEST_NARRATIVE"] = "0"
        cur = Cur(("x",))
        self.assertIsNone(digest.narrative(cur))
        self.assertEqual(cur.sql, [])

    def test_missing_note_or_table_is_silent(self):
        self.assertIsNone(digest.narrative(Cur(None)))
        UndefinedTable = type("UndefinedTable", (pg.Error,), {})   # psycopg.errors.UndefinedTable
        self.assertIsNone(digest.narrative(Cur(exc=UndefinedTable('relation "llm_narratives" does not exist'))))

    def test_other_db_errors_still_raise(self):
        other = pg.Error("connection lost")
        with self.assertRaises(pg.Error):
            digest.narrative(Cur(exc=other))


if __name__ == "__main__":
    unittest.main(verbosity=1)
