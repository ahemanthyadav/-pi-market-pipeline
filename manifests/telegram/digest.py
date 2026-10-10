"""Daily market digest to Telegram (findings Tier 1 #6, added 2026-10-08).

Reads ONLY existing tables — no new ingestion, no DB writes (house rule: read-only
by default). Composes the 08:00 IST digest and posts it to the Telegram chat.
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

IST = timezone(timedelta(hours=5, minutes=30))
TELEGRAM_LIMIT = 4096

# index_prices tickers already ingested by the daily batch (no new feed added).
CLOSES = [
    ("^NSEI", "Nifty 50"),
    ("^BSESN", "Sensex"),
    ("^GSPC", "S&P 500"),
    ("^VIX", "VIX"),
    ("^INDIAVIX", "India VIX"),
    ("DX-Y.NYB", "DXY"),
    ("GC=F", "Gold fut"),
]
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


def closes(cur):
    """[(label, ts, close, prev_close)] — last two daily rows per ticker."""
    rows = []
    for ticker, label in CLOSES:
        cur.execute(
            "SELECT ts, close FROM index_prices WHERE ticker = %s ORDER BY ts DESC LIMIT 2",
            (ticker,),
        )
        fetched = cur.fetchall()
        if not fetched:
            print(f"WARN no data for {label} ({ticker})", flush=True)
            continue
        ts, close = fetched[0]
        prev = fetched[1][1] if len(fetched) > 1 else None
        rows.append((label, ts, close, prev))
    return rows


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


def build_message():
    conn = connect()
    with conn.cursor() as cur:
        lines = [f"<b>Market digest — {datetime.now(IST):%Y-%m-%d %H:%M IST}</b>", ""]

        for label, ts, close, prev in closes(cur):
            pct = ""
            if prev:
                change = (close - prev) / prev * 100
                pct = f" ({change:+.2f}%)"
            lines.append(f"{label}: <b>{close:,.2f}</b>{pct}  <i>{ts:%d %b}</i>")

        for label, ts, rate in fx(cur):
            lines.append(f"{label}: <b>{rate:,.4f}</b>")

        gauge = sentiment(cur)
        if gauge is not None:
            lines.append(f"\nSentiment (7d avg): <b>{gauge:+.3f}</b>")

        flow_rows = flows(cur)
        if flow_rows:
            lines.append("FII/DII net: " + " · ".join(
                f"{flow} <b>{amount:,.0f}</b> Rs cr" for flow, amount in flow_rows
            ))

        stale = stale_feeds(cur)
        lines.append(
            "\nStale feeds: <b>none</b>" if not stale
            else "\n<b>Stale feeds:</b> " + ", ".join(
                f"{feed} (last data {last:%d %b})" for feed, last, _ in stale
            )
        )

        tops = headlines(cur)
        if tops:
            lines.append("\n" + "\n".join(
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
