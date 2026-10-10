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
Env: PGHOST, PGUSER, PGPASSWORD, PGDATABASE, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.
OK-marker: "ALERTS-OK". Exit 1 only when a message was due and the send failed.
"""

import sys

import stocks
from digest import TELEGRAM_LIMIT, connect, send


def main() -> int:
    conn = connect()
    try:
        with conn.cursor() as cur:
            def q(sql, args=()):
                cur.execute(sql, args)
                return cur.fetchall()
            lines = stocks.alert_sections(q)
    finally:
        conn.close()

    if not lines:
        print("ALERTS-OK nothing changed — no message sent", flush=True)
        return 0
    text = "<b>Changes since the last run</b>\n" + "\n".join(lines)
    if len(text) > TELEGRAM_LIMIT:
        text = text[: TELEGRAM_LIMIT - 1] + "…"
    if not send(text):
        return 1
    print(f"ALERTS-OK {len(lines)} line(s) sent", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
