#!/usr/bin/env python3
"""Tests for pull-backups.py --prune-local (no network: paramiko is stubbed).

    python3 tests/test_pull_backups.py
"""
import hashlib
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.modules.setdefault("paramiko", types.ModuleType("paramiko"))
OPS = Path(__file__).resolve().parent.parent / "ops-tools"
sys.path.insert(0, str(OPS))
spec = importlib.util.spec_from_file_location("pull_backups", OPS / "pull-backups.py")
pb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pb)


class PruneLocal(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def mk(self, day, good=True, sidecar=True):
        name = f"marketdata-{day}.dump"
        path = os.path.join(self.d, name)
        with open(path, "wb") as f:
            f.write(day.encode())
        if sidecar:
            h = hashlib.sha256(day.encode()).hexdigest() if good else "0" * 64
            with open(path + ".sha256", "w") as f:
                f.write(f"{h}  {name}\n")

    def days(self):
        return sorted(n[11:21] for n in os.listdir(self.d) if n.endswith(".dump"))

    def run_prune(self, keep=2):
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            pb.prune_local(self.d, keep, "2026-10-18")

    def test_keeps_newest_verified_and_never_touches_older_or_unverified(self):
        for day in ["2026-10-13", "2026-10-17", "2026-10-18", "2026-10-19", "2026-10-20", "2026-10-21"]:
            self.mk(day)
        self.mk("2026-10-22", good=False)
        self.mk("2026-10-23", sidecar=False)
        self.run_prune()
        self.assertEqual(self.days(), ["2026-10-13", "2026-10-17", "2026-10-20", "2026-10-21",
                                       "2026-10-22", "2026-10-23"])
        self.assertFalse(os.path.exists(os.path.join(self.d, "marketdata-2026-10-18.dump.sha256")))

    def test_idempotent(self):
        for day in ["2026-10-18", "2026-10-19", "2026-10-20"]:
            self.mk(day)
        self.run_prune()
        first = self.days()
        self.run_prune()
        self.assertEqual(self.days(), first)
        self.assertEqual(first, ["2026-10-19", "2026-10-20"])

    def test_ignores_unrelated_files(self):
        self.mk("2026-10-20")
        open(os.path.join(self.d, "SHA256SUMS"), "w").close()
        open(os.path.join(self.d, "marketdata-2026-10-19.dump.part"), "w").close()
        self.run_prune(keep=0)
        self.assertTrue(os.path.exists(os.path.join(self.d, "SHA256SUMS")))
        self.assertTrue(os.path.exists(os.path.join(self.d, "marketdata-2026-10-19.dump.part")))


if __name__ == "__main__":
    unittest.main(verbosity=1)
