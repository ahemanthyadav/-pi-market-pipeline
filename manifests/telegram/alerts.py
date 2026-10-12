"""Daily change alerts to Telegram (added 2026-10-10).

The digest reports LEVELS every morning; this reports CHANGES, and stays
silent when there are none:
  - names that entered / left the screener top-20 (per universe)
  - watchlist: day move >= 5%, 50/200-day average crossings
  - watchlist: tagged news events (headline_events) in the last 24 h

Stateless by design — each check compares the latest data with the row
before it and only fires when the latest row is dated today or yesterday
(UTC), so a weekend or a stalled feed cannot repeat Friday's alert.
Read-only: SELECTs only (the watchlist is written by bot.py's /watch).

Schedule: after stock-screener (02:15 node-local) — see cronjob.yaml.
Env: PGHOST, PGUSER, PGPASSWORD, PGDATABASE, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (the owner;
other users come from bot_users — ADR 0012). Each user gets the shared screener changes
plus their OWN watchlist alerts; a user with nothing to report gets no message.
OK-marker: "ALERTS-OK". Exit 1 only when a message was due and the send failed.
"""

import os
import sys

import stocks
import users
from digest import TELEGRAM_LIMIT, connect, send


def main() -> int:
    owner = os.environ["TELEGRAM_CHAT_ID"]
    conn = connect()
    try:
        with conn.cursor() as cur:
            def q(sql, args=()):
                cur.execute(sql, args)
                return cur.fetchall()
            recipients = users.recipients_for_jobs(q, owner)
            common = stocks.alert_common(q)                      # shared by everyone
            personal = {chat: stocks.alert_watch(q, chat) for chat, _ in recipients}
    finally:
        conn.close()

    def make_text(chat):
        lines = common + personal.get(chat, [])
        if not lines:
            return None
        text = "<b>Changes since the last run</b>\n" + "\n".join(lines)
        return text[: TELEGRAM_LIMIT - 1] + "…" if len(text) > TELEGRAM_LIMIT else text

    rc = users.deliver(recipients, owner, make_text, send)
    sent = sum(1 for chat, _ in recipients if common + personal.get(chat, []))
    if not sent:
        print("ALERTS-OK nothing changed — no message sent", flush=True)
    else:
        print(f"ALERTS-OK {sent} message(s) for {len(recipients)} user(s) rc={rc}", flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
