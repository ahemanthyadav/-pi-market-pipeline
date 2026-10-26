#!/usr/bin/env python3
"""news_embed.py: gateway call shape (fallbacks off, model recorded) and vector formatting. No network, no DB.

    python3 tests/test_news_embed.py
"""
import io
import json
import os
import sys
import types
import unittest
from pathlib import Path

sys.modules.setdefault("psycopg", types.ModuleType("psycopg"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "manifests" / "llm"))
import news_embed as ne  # noqa: E402


class Resp(io.BytesIO):
    def __init__(self, body, headers):
        super().__init__(json.dumps(body).encode())
        self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Embed(unittest.TestCase):
    def setUp(self):
        os.environ.update(LLM_BASE_URL="http://gw/v1", LLM_API_KEY="k")
        self.sent = []
        self._orig = ne.urllib.request.urlopen

    def tearDown(self):
        ne.urllib.request.urlopen = self._orig

    def fake(self, headers, n=2):
        def opener(req, timeout):
            self.sent.append(json.loads(req.data))
            return Resp({"data": [{"index": i, "embedding": [0.1 * i, 0.2]} for i in reversed(range(n))]}, headers)
        ne.urllib.request.urlopen = opener

    def test_fallbacks_disabled_and_model_recorded_in_order(self):
        self.fake({"x-litellm-model-name": "prov/test-embed-1b"})
        model, vecs = ne.embed(["a", "b"])
        self.assertTrue(self.sent[0]["disable_fallbacks"])
        self.assertEqual(model, "test-embed-1b")
        self.assertEqual(vecs[0], [0.0, 0.2])                     # sorted by index

    def test_unknown_model_is_refused(self):
        self.fake({})
        with self.assertRaises(RuntimeError):
            ne.embed(["a", "b"])

    def test_vector_literal(self):
        self.assertEqual(ne.vec_literal([0.5, -1e-7, 2]), "[0.5,-1e-07,2]")


if __name__ == "__main__":
    unittest.main(verbosity=1)
