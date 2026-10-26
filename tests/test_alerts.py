"""Unit tests for the Telegram alert job's decision logic (no network, no DB).

    python3 tests/test_alerts.py

Proves manifests/telegram/alerts.py:
  - stays SILENT when neither the shared screener checks nor any personal
    watchlist check produced a line (no send, exit 0, "nothing changed");
  - fires one personalised message per recipient when there is something to
    say: shared lines go to everyone, watchlist lines only to their owner,
    under the "<b>Changes since the last run</b>" header;
  - truncates at TELEGRAM_LIMIT with a trailing ellipsis;
  - exit semantics come from users.deliver: owner send failure -> 1, a
    member-only failure -> 0, nothing due -> 0;
  - degrades to owner-only when bot_users is missing (schema 09 not applied);
  - closes the DB connection before sending.

`stocks` and `digest` are stubbed in sys.modules BEFORE alerts is imported
(their internals are deliberately not under test here — stocks.py/digest.py
have their own coverage); the real users.py supplies recipients_for_jobs and
deliver, so the fan-out and exit-code logic under test is the production one.
"""
import importlib.util
import io
import os
import sys
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TELEGRAM = ROOT / "manifests/telegram"

OWNER = "999"
os.environ["TELEGRAM_CHAT_ID"] = OWNER

# ------------------------------------------------------------------ scripted state
COMMON = []            # lines stocks.alert_common returns (shared by everyone)
WATCH = {}             # chat -> lines stocks.alert_watch returns
MEMBERS = [[(111, "Alice")]]       # rows the bot_users SELECT returns
MEMBERS_ERROR = [None]             # exception raised by the bot_users SELECT
SENDS = []             # (chat, text) every send() call
SEND_FAIL = set()      # chats whose send() returns False
CONNS = []             # every connection handed out


class UndefinedTable(Exception):
    """Name is what users.table_missing() checks for."""


class FakeCursor:
    def __init__(self):
        self._sql = ""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, args=()):
        self._sql = sql
        if "bot_users" in sql and MEMBERS_ERROR[0] is not None:
            raise MEMBERS_ERROR[0]

    def fetchall(self):
        return list(MEMBERS[0]) if "bot_users" in self._sql else []


class FakeConn:
    def __init__(self):
        self.closed = False

    def cursor(self):
        return FakeCursor()

    def close(self):
        self.closed = True


# --------------------------------------------------- stubs installed BEFORE import
STOCKS = types.ModuleType("stocks")
STOCKS.alert_common = lambda q: list(COMMON)
STOCKS.alert_watch = lambda q, chat: list(WATCH.get(str(chat), []))
# Length-contract stub: the real tag-aware trim_html is proven in test_stocks.py;
# alerts only needs "result ≤ limit, ellipsis when cut".
STOCKS.trim_html = lambda text, limit: text if len(text) <= limit else text[: limit - 1] + "…"

DIGEST = types.ModuleType("digest")
DIGEST.TELEGRAM_LIMIT = 120        # small limit so truncation is easy to exercise


def _connect():
    conn = FakeConn()
    CONNS.append(conn)
    return conn


def _send(text, chat):
    SENDS.append((str(chat), text))
    return str(chat) not in SEND_FAIL


DIGEST.connect = _connect
DIGEST.send = _send

sys.modules["stocks"] = STOCKS
sys.modules["digest"] = DIGEST
sys.path.insert(0, str(TELEGRAM))  # real users.py (pure logic, no DB at import)

spec = importlib.util.spec_from_file_location("alerts", TELEGRAM / "alerts.py")
alerts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(alerts)

HEADER = "<b>Changes since the last run</b>\n"


def run():
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = alerts.main()
    return rc, buf.getvalue()


class Alerts(unittest.TestCase):
    def setUp(self):
        COMMON.clear()
        WATCH.clear()
        SENDS.clear()
        SEND_FAIL.clear()
        CONNS.clear()
        MEMBERS[0] = [(111, "Alice")]
        MEMBERS_ERROR[0] = None

    def test_nothing_changed_sends_nothing(self):
        rc, out = run()
        self.assertEqual(rc, 0)
        self.assertEqual(SENDS, [])
        self.assertIn("ALERTS-OK nothing changed", out)

    def test_shared_change_goes_to_every_recipient(self):
        COMMON.append("• ACME entered top-20 (nifty50)")
        rc, out = run()
        self.assertEqual(rc, 0)
        self.assertEqual([c for c, _ in SENDS], [OWNER, "111"])  # owner first
        for _, text in SENDS:
            self.assertEqual(text, HEADER + "• ACME entered top-20 (nifty50)")
        self.assertIn("ALERTS-OK 2 message(s) for 2 user(s)", out)

    def test_watchlist_lines_reach_only_their_owner(self):
        COMMON.append("• shared line")
        WATCH[OWNER] = ["• OWN-STOCK +6.2% today"]
        WATCH["111"] = ["• ALICE-STOCK crossed its 200-day average"]
        run()
        texts = dict(SENDS)
        self.assertIn("• OWN-STOCK +6.2% today", texts[OWNER])
        self.assertNotIn("ALICE-STOCK", texts[OWNER])
        self.assertIn("• ALICE-STOCK crossed its 200-day average", texts["111"])
        self.assertNotIn("OWN-STOCK", texts["111"])
        for text in texts.values():
            self.assertTrue(text.startswith(HEADER + "• shared line"))

    def test_personal_only_change_messages_only_that_chat(self):
        WATCH["111"] = ["• XYZ -5.4% today"]
        rc, _ = run()
        self.assertEqual(rc, 0)
        self.assertEqual([c for c, _ in SENDS], ["111"])
        self.assertEqual(SENDS[0][1], HEADER + "• XYZ -5.4% today")

    def test_long_message_truncated_at_telegram_limit(self):
        COMMON.append("• " + "x" * 500)
        run()
        for _, text in SENDS:
            self.assertLessEqual(len(text), DIGEST.TELEGRAM_LIMIT)
            self.assertTrue(text.endswith("…"))
            self.assertTrue(text.startswith(HEADER))

    def test_owner_send_failure_exits_1(self):
        COMMON.append("• line")
        SEND_FAIL.add(OWNER)
        rc, _ = run()
        self.assertEqual(rc, 1)

    def test_member_only_send_failure_still_exits_0(self):
        COMMON.append("• line")
        SEND_FAIL.add("111")
        rc, out = run()
        self.assertEqual(rc, 0)
        self.assertIn("rc=0", out)

    def test_missing_bot_users_table_degrades_to_owner_only(self):
        MEMBERS_ERROR[0] = UndefinedTable("relation bot_users does not exist")
        COMMON.append("• line")
        rc, _ = run()
        self.assertEqual(rc, 0)
        self.assertEqual([c for c, _ in SENDS], [OWNER])

    def test_connection_closed_even_when_quiet(self):
        run()
        self.assertEqual(len(CONNS), 1)
        self.assertTrue(CONNS[0].closed)
        COMMON.append("• line")
        run()
        self.assertTrue(all(c.closed for c in CONNS))


if __name__ == "__main__":
    unittest.main()
