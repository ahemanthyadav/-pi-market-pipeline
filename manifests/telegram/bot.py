"""Two-way Telegram listener — Tier 2 interface (2026-10-09, ADR 0009 family).

Long-polling getUpdates loop: CGNAT (F10) makes webhooks impossible, so the
bot pulls. This is the ONLY getUpdates consumer — Telegram 409s a second
poller; the digest CronJob and Grafana's contact point only sendMessage.

Single-user security model: only TELEGRAM_CHAT_ID is ever answered. Telegram
bots are public — anyone who finds @Marketfredbot can message it — so the
allow-list IS the door. Others are logged and silently ignored.

DB access: read-only SELECTs (house rule). Connections open per command and
close after — long-idle pod→DB connections get dropped (F26), so nothing is
held across the sleep between polls. One retry per query.

Commands: /help /status /vix /nifty /sensex /gold /fii /scores /digest
  (/start also maps to help). /digest re-runs digest.build_message() — both
  scripts share this image; the Deployment selects this entrypoint via args.

Crash semantics: offset is in-memory only. On start the backlog is DRAINED
without replying (a restart must not replay old commands); commands are
idempotent reads, so at worst a crash re-answers one message.

Env: PGHOST, PGUSER, PGPASSWORD, PGDATABASE, TELEGRAM_BOT_TOKEN,
TELEGRAM_CHAT_ID. Missing env exits 1 (k3s restarts); Telegram/DB blips are
retried with capped backoff and never fatal.

Validate manually:
  kubectl logs -n market-data deploy/telegram-bot -f   # expect "listening as @"
"""

import html
import os
import sys
import time
from datetime import timedelta, timezone

import psycopg
import requests

from digest import IST, TELEGRAM_LIMIT, build_message

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED = os.environ["TELEGRAM_CHAT_ID"]
API = f"https://api.telegram.org/bot{TOKEN}"


# ---------------------------------------------------------------- DB helpers

def query(sql: str, args: tuple = ()) -> list:
    """Run one read-only SELECT; one reconnect-retry per F26."""
    for attempt in (1, 2):
        try:
            conn = psycopg.connect(
                host=os.environ.get("PGHOST", "timescaledb.market-data.svc.cluster.local"),
                user=os.environ.get("PGUSER", "postgres"),
                password=os.environ["PGPASSWORD"],
                dbname=os.environ.get("PGDATABASE", "postgres"),
            )
            try:
                conn.autocommit = True  # house pattern: SELECTs never hold a txn
                with conn.cursor() as cur:
                    cur.execute(sql, args)
                    return cur.fetchall()
            finally:
                conn.close()
        except psycopg.Error as exc:
            if attempt == 2:
                raise
            print(f"WARN db retry ({exc.__class__.__name__})", flush=True)


# ---------------------------------------------------------------- commands

def last_two(ticker: str):
    rows = query(
        "SELECT ts, close FROM index_prices WHERE ticker = %s ORDER BY ts DESC LIMIT 2",
        (ticker,),
    )
    if not rows:
        return None
    ts, close = rows[0]
    prev = rows[1][1] if len(rows) > 1 else None
    return ts, close, prev


def quote_line(label: str, ticker: str) -> str:
    got = last_two(ticker)
    if not got:
        return f"{label}: no data"
    ts, close, prev = got
    pct = f" ({(close - prev) / prev * 100:+.2f}%)" if prev else ""
    return f"{label}: <b>{close:,.2f}</b>{pct}  <i>{ts:%d %b}</i>"


def cmd_help(_text: str) -> str:
    return (
        "<b>Marketfredbot</b> — read-only commands:\n"
        "/status — pipeline heartbeat freshness\n"
        "/vix — VIX + India VIX\n"
        "/nifty · /sensex · /gold — latest close + day change\n"
        "/fii — latest FII/DII net + 5-session FII trend\n"
        "/scores — screener top-5 today\n"
        "/digest — full daily digest on demand\n"
        "Daily digest: 08:00 IST · alerts: Grafana → this chat"
    )


def cmd_status(_text: str) -> str:
    fresh, stale, last_check = query(
        "SELECT count(*) FILTER (WHERE fresh), count(*) FILTER (WHERE NOT fresh), "
        "max(last_check) FROM pipeline_heartbeat"
    )[0]
    head = f"Pipeline: <b>{fresh} fresh / {stale} stale</b> · last check {last_check:%d %b %H:%M UTC}"
    if stale:
        names = ", ".join(r[0] for r in query(
            "SELECT feed FROM pipeline_heartbeat WHERE NOT fresh ORDER BY feed"))
        head += f"\nStale: <b>{html.escape(names)}</b>"
    return head


def cmd_vix(_text: str) -> str:
    return quote_line("VIX", "^VIX") + "\n" + quote_line("India VIX", "^INDIAVIX")


def cmd_nifty(_text: str) -> str:
    return quote_line("Nifty 50", "^NSEI")


def cmd_sensex(_text: str) -> str:
    return quote_line("Sensex", "^BSESN")


def cmd_gold(_text: str) -> str:
    return quote_line("Gold fut", "GC=F")


def cmd_fii(_text: str) -> str:
    latest = query(
        "SELECT flow_type, amount FROM capital_flows "
        "WHERE direction = 'net' AND ts = (SELECT max(ts) FROM capital_flows) "
        "ORDER BY flow_type"
    )
    trend = query(
        "SELECT ts::date, amount FROM capital_flows "
        "WHERE flow_type = 'FII' AND direction = 'net' "
        "ORDER BY ts DESC LIMIT 5"
    )
    lines = [" · ".join(f"{f} <b>{a:,.0f}</b>" for f, a in latest) + " Rs cr"]
    lines += [f"{d}: {a:,.0f}" for d, a in reversed(trend)]
    return "\n".join(lines)


def cmd_scores(_text: str) -> str:
    rows = query(
        "SELECT COALESCE(t.name, s.symbol), s.composite, s.rank "
        "FROM stock_scores s LEFT JOIN ticker_names t ON t.ticker = s.symbol "
        "WHERE s.ts = (SELECT max(ts) FROM stock_scores) AND s.eligible "
        "ORDER BY s.rank NULLS LAST LIMIT 5"
    )
    if not rows:
        return "No scored rows yet (screener runs 02:15 node-local)"
    return "Screener top-5 (latest run):\n" + "\n".join(
        f"{rank}. <b>{html.escape(str(name))}</b> — {comp:.1f}"
        for name, comp, rank in rows
    )


def cmd_digest(_text: str) -> str:
    return build_message()


COMMANDS = {
    "start": cmd_help,
    "help": cmd_help,
    "status": cmd_status,
    "vix": cmd_vix,
    "nifty": cmd_nifty,
    "sensex": cmd_sensex,
    "gold": cmd_gold,
    "fii": cmd_fii,
    "scores": cmd_scores,
    "digest": cmd_digest,
}


# ---------------------------------------------------------------- transport

def send(text: str) -> None:
    if len(text) > TELEGRAM_LIMIT:
        text = text[: TELEGRAM_LIMIT - 1] + "…"
    r = requests.post(f"{API}/sendMessage",
                      json={"chat_id": ALLOWED, "text": text, "parse_mode": "HTML"},
                      timeout=30)
    if r.status_code != 200 or not r.json().get("ok"):
        print(f"ERROR sendMessage {r.status_code}: {r.text[:200]}", flush=True)


def handle(update: dict) -> None:
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return
    chat = str(msg.get("chat", {}).get("id", ""))
    text = (msg.get("text") or "").strip()

    if chat != ALLOWED:
        who = (msg.get("from") or {})
        print(f"IGNORED chat={chat} user={who.get('username') or who.get('id')} "
              f"text={text[:40]!r}", flush=True)
        return

    if not text:
        return
    cmd = text.split()[0].lstrip("/").split("@")[0].lower()
    handler = COMMANDS.get(cmd)
    if handler is None:
        send(f"Unknown command. {chr(10)}" + cmd_help(""))
        return
    try:
        send(handler(text))
        print(f"answered /{cmd}", flush=True)
    except Exception as exc:  # noqa: BLE001 - one bad query must not kill the loop
        print(f"ERROR /{cmd}: {exc}", flush=True)
        send("Command failed — see logs (kubectl logs deploy/telegram-bot).")


def poll_forever() -> None:
    offset = None
    drain = True  # first fetch: skip the backlog, never replay old commands
    failures = 0
    while True:
        params = {"timeout": 25}
        if offset is not None:
            params["offset"] = offset
        try:
            r = requests.get(f"{API}/getUpdates", params=params, timeout=30)
            updates = r.json().get("result", [])
            failures = 0
        except (requests.RequestException, ValueError) as exc:
            failures += 1
            wait = min(60, 3 * failures)
            print(f"WARN getUpdates failed ({exc.__class__.__name__}), retry in {wait}s",
                  flush=True)
            time.sleep(wait)
            continue

        if updates:
            offset = updates[-1]["update_id"] + 1
        if drain:
            if updates:
                print(f"drained {len(updates)} backlog update(s)", flush=True)
            drain = False
            continue

        for update in updates:
            handle(update)


def main() -> int:
    me = requests.get(f"{API}/getMe", timeout=15).json().get("result", {})
    print(f"listening as @{me.get('username')} for chat {ALLOWED[:2]}***", flush=True)
    poll_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
