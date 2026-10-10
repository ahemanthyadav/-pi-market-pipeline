"""Daily market digest to Telegram (findings Tier 1 #6, added 2026-10-08).

Reads ONLY existing tables — no new ingestion, no DB writes (house rule: read-only
by default). Composes the 08:00 IST digest and posts it to the Telegram chat.
Index closes are a close/day/YTD table and the watchlist section a table plus
holdings totals (2026-10-10, stocks.py); the watchlist section is skipped
silently while the table is empty or not yet created.
The same Secret also backs the Grafana Telegram contact point
(manifests/grafana/alerting.yaml), so the bot is both the digest and the alert
channel; the token/chat ID stay deployment config, never code.

Env: PGHOST, PGUSER, PGPASSWORD, PGDATABASE, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.
Exit 0 only when the Bot API accepts the message (CronJob failure signal).
"""

import html
import os
import sys
from datetime import datetime, timedelta, timezone

import psycopg
import requests

import stocks

IST = timezone(timedelta(hours=5, minutes=30))
TELEGRAM_LIMIT = 4096

FX_PAIRS = [("USDINR=X", "USD/INR")]
TOP_HEADLINES = 3


def connect():
    conn = psycopg.connect(
        host=os.environ.get("PGHOST", "timescaledb.market-data.svc.cluster.local"),
        user=os.environ.get("PGUSER", "postgres"),
        password=os.environ["PGPASSWORD"],
        dbname=os.environ.get("PGDATABASE", "postgres"),
    )
    conn.autocommit = True  # read-only path: house pattern for SELECTs
    return conn


def fx(cur):
    out = []
    for pair, label in FX_PAIRS:
        cur.execute(
            "SELECT ts, rate FROM fx_rates WHERE pair = %s ORDER BY ts DESC LIMIT 1",
            (pair,),
        )
        row = cur.fetchone()
        if row:
            out.append((label, row[0], row[1]))
        else:
            print(f"WARN no data for {label}", flush=True)
    return out


def sentiment(cur):
    cur.execute(
        "SELECT AVG(sentiment_score) FROM news_sentiment WHERE ts > now() - interval '7 days'"
    )
    return cur.fetchone()[0]


def flows(cur):
    cur.execute(
        "SELECT flow_type, amount FROM capital_flows "
        "WHERE direction = 'net' AND ts = (SELECT max(ts) FROM capital_flows) "
        "ORDER BY flow_type"
    )
    return cur.fetchall()


def stale_feeds(cur):
    cur.execute(
        "SELECT feed, last_data_ts, max_age_hours FROM pipeline_heartbeat "
        "WHERE fresh = false ORDER BY feed"
    )
    return cur.fetchall()


def headlines(cur):
    # Latest scored headlines, no relevance filter: ticker_relevance is a
    # sector/index keyword tag or 'general' (sentiment-score.py), not a level.
    cur.execute(
        "SELECT ts, headline, source FROM news_sentiment "
        "ORDER BY ts DESC LIMIT %s",
        (TOP_HEADLINES,),
    )
    return cur.fetchall()


def watchlist(cur):
    """Compact watchlist lines; [] when the table is empty or missing."""
    def q(sql, args=()):
        cur.execute(sql, args)
        return cur.fetchall()
    try:
        rows = q(stocks.WATCH_SQL)
        if not rows:
            return []
        return stocks.watch_block(rows, stocks.ytd_map(q, [r[0] for r in rows]),
                                  notes=False)
    except psycopg.Error as exc:
        if not stocks.table_missing(exc):
            raise
        print("WARN watchlist table missing — section skipped", flush=True)
        return []


def build_message():
    conn = connect()
    with conn.cursor() as cur:
        def q(sql, args=()):
            cur.execute(sql, args)
            return cur.fetchall()

        lines = [f"<b>Market digest</b>  <i>{datetime.now(IST):%d %b %Y, %H:%M IST}</i>",
                 stocks.quote_table(q, stocks.DIGEST_QUOTES)]

        facts = [(label, f"{rate:,.4f}") for label, _ts, rate in fx(cur)]
        gauge = sentiment(cur)
        if gauge is not None:
            facts.append(("Sentiment, 7-day avg", f"{gauge:+.3f}"))
        facts += [(f"{flow} net, Rs cr", f"{amount:+,.0f}") for flow, amount in flows(cur)]
        if facts:
            lines.append(stocks.kv(facts))

        stale = stale_feeds(cur)
        lines.append(
            "Stale feeds: <b>none</b>" if not stale
            else "<b>Stale feeds</b>\n" + "\n".join(
                f"• {html.escape(feed)} — last data {last:%d %b}" for feed, last, _ in stale
            )
        )

        watched = watchlist(cur)
        if watched:
            lines.append("\n<b>Watchlist</b>\n" + "\n".join(watched))

        tops = headlines(cur)
        if tops:
            lines.append("\n<b>Latest headlines</b>\n" + "\n".join(
                f"• {html.escape(headline)} <i>{html.escape(source or '')}</i>"
                for _, headline, source in tops
            ))

    conn.close()
    text = "\n".join(lines)
    if len(text) > TELEGRAM_LIMIT:
        text = text[: TELEGRAM_LIMIT - 1] + "…"
    return text


def send(text: str) -> bool:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat = os.environ["TELEGRAM_CHAT_ID"]
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text, "parse_mode": "HTML"},
            timeout=30,
        )
    except requests.RequestException as exc:
        print(f"ERROR telegram send failed: {exc}", flush=True)
        return False

    if r.status_code != 200 or not r.json().get("ok"):
        print(f"ERROR telegram {r.status_code}: {r.text[:200]}", flush=True)
        return False
    print(f"digest sent to chat {chat} ({len(text)} chars)", flush=True)
    return True


def main() -> int:
    message = build_message()
    if not message:
        print("ERROR: empty digest", flush=True)
        return 1
    return 0 if send(message) else 1


if __name__ == "__main__":
    sys.exit(main())
