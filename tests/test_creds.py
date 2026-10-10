#!/usr/bin/env python3
"""Tests for ops-tools/_creds.py token expansion (@@PW@@ and @@KEY@@).

Runs entirely against throwaway files — the real local credentials file is never
read (the module's file paths are redirected to a temp dir).

    python3 tests/test_creds.py
"""
import io
import os
import shlex
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ops-tools"))
import _creds  # noqa: E402


class CredsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "creds").write_text(
            "PI_PASS=pipw\nTX2_PASS=txpw\nFAKE_TOKEN='a b$c d'\nHOSTILE='x; touch /tmp/pwn $(id) `id`'\nEMPTY=\n")
        (self.tmp / "hosts").write_text("PI2_IP=192.0.2.13\nTX2_IP=192.0.2.101\nTX2_TS_IP=198.51.100.7\n")
        self.old = (_creds.ENV_FILE, _creds.HOSTS_FILE)
        _creds.ENV_FILE, _creds.HOSTS_FILE = self.tmp / "creds", self.tmp / "hosts"
        os.environ.pop("SSH_PASS", None)

    def tearDown(self):
        _creds.ENV_FILE, _creds.HOSTS_FILE = self.old

    def test_alias_resolution(self):
        self.assertEqual(_creds.resolve_host("pi2"), "192.0.2.13")
        self.assertEqual(_creds.resolve_host("TX2"), "192.0.2.101")
        self.assertEqual(_creds.resolve_host("203.0.113.9"), "203.0.113.9")  # raw IP passes through
        with self.assertRaises(SystemExit):
            _creds.resolve_host("pi0")  # alias with no entry fails loudly, not silently

    def test_password_is_host_aware(self):
        self.assertEqual(_creds.password_for("pi2", "pi2"), "pipw")
        self.assertEqual(_creds.password_for("tx2", "ahytx2"), "txpw")
        self.assertEqual(_creds.password_for("192.0.2.101", "x"), "txpw")      # by LAN IP
        self.assertEqual(_creds.password_for("198.51.100.7", "x"), "txpw")     # by tailnet IP
        os.environ["SSH_PASS"] = "override"
        self.assertEqual(_creds.password_for("pi2", "pi2"), "override")

    def test_pw_token_is_shell_quoted(self):
        out = _creds.expand("echo @@PW@@ | sudo -S true", "it's a pw")
        self.assertEqual(shlex.split(out.split("|")[0])[1], "it's a pw")        # round-trips intact

    def test_key_token_expands_and_round_trips(self):
        out = _creds.expand("curl -s @@FAKE_TOKEN@@", "pw")
        self.assertEqual(shlex.split(out), ["curl", "-s", "a b$c d"])            # one intact argument

    def test_hostile_value_cannot_inject_a_command(self):
        out = _creds.expand("echo @@HOSTILE@@", "pw")
        argv = shlex.split(out)
        self.assertEqual(len(argv), 2)                                           # still exactly one argument
        self.assertEqual(argv[1], "x; touch /tmp/pwn $(id) `id`")               # carried as inert text

    def test_unknown_token_left_literal_with_warning(self):
        err = io.StringIO()
        with redirect_stderr(err):
            out = _creds.expand("echo @@NOPE@@ @@NOPE@@", "pw")
        self.assertEqual(out, "echo @@NOPE@@ @@NOPE@@")
        self.assertEqual(err.getvalue().count("@@NOPE@@ not found"), 1)           # warned once, not per use

    def test_plain_text_untouched(self):
        self.assertEqual(_creds.expand("uptime; free -m | head -2", "pw"), "uptime; free -m | head -2")


if __name__ == "__main__":
    unittest.main(verbosity=2)
