#!/usr/bin/env python3
"""pipeline-health v6 additions: the AI-note feed and the gateway probe. No network, no DB.

    python3 tests/test_health.py
"""
import importlib.util
import sys
import types
import unittest
from pathlib import Path

sys.modules.setdefault("psycopg", types.ModuleType("psycopg"))
spec = importlib.util.spec_from_file_location(
    "health", Path(__file__).resolve().parent.parent / "manifests" / "health" / "pipeline-health.py")
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)


class Resp:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Health(unittest.TestCase):
    def test_ai_note_feed_counts_only_passed_notes(self):
        feed = {f[0]: f for f in h.FEEDS}["llm_narrative"]
        self.assertIn("status = 'ok'", feed[1])
        self.assertGreater(feed[3], 48)          # one missed day must not page

    def test_gateway_probe(self):
        self.assertTrue(h.gateway_ok("u", lambda url, timeout: Resp(200)))
        self.assertFalse(h.gateway_ok("u", lambda url, timeout: Resp(503)))

        def down(url, timeout):
            raise OSError("connection refused")
        self.assertFalse(h.gateway_ok("u", down))

    def test_gateway_upsert_keeps_last_good_time_on_failure(self):
        self.assertIn("COALESCE(EXCLUDED.last_data_ts, pipeline_heartbeat.last_data_ts)", h.GATEWAY_UPSERT)


if __name__ == "__main__":
    unittest.main(verbosity=1)
