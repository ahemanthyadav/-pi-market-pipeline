"""Two-way Telegram listener — Tier 2 interface (2026-10-09, ADR 0009 family).

Long-polling getUpdates loop: CGNAT (F10) makes webhooks impossible, so the
bot pulls. This is the ONLY getUpdates consumer — Telegram 409s a second
poller; the digest CronJob and Grafana's contact point only sendMessage.

Security model (ADR 0012, multi-user since 2026-10-12): the owner (the Secret's
TELEGRAM_CHAT_ID) plus the active rows of `bot_users` are answered; everyone has their
OWN watchlist, digest and alerts. Telegram bots are public — anyone who finds
@Marketfredbot can message it — so the allow-list IS the door. Unknown chats are logged and
never answered; the owner gets one "access request" notice per chat per day with a
ready-made /adduser line. Only the owner can /adduser /rmuser /users.

DB access: read-only SELECTs (house rule) with TWO exceptions the bot owns — /watch add|rm
writes `watchlist` (keyed by chat), and the owner's /adduser|/rmuser write `bot_users`.
Connections open per command and close after — long-idle pod→DB connections
get dropped (F26), so nothing is held across the sleep between polls. One
retry per query.

Commands: /help /status /vix /nifty /sensex /gold /fii /scores /digest
  /stock /news /watch /top /movers /track /macro /world /index /fx /multibagger (stock/watchlist/screener
  views live in stocks.py, 2026-10-10). /start also maps to help. /digest
  re-runs digest.build_message() — the scripts share this image; the
  Deployment selects this entrypoint via args.

Crash semantics: offset is in-memory only. On start the backlog is DRAINED
without replying (a restart must not replay old commands); commands are
idempotent reads, so at worst a crash re-answers one message.

Env: PGHOST, PGUSER, PGPASSWORD, PGDATABASE, TELEGRAM_BOT_TOKEN,
TELEGRAM_CHAT_ID (the owner). Missing env exits 1 (k3s restarts); Telegram/DB blips are
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

import stocks
import users
from digest import IST, TELEGRAM_LIMIT, build_message

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
OWNER = os.environ["TELEGRAM_CHAT_ID"]
ALLOWED = OWNER   # back-compat alias for the single-user name
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


def execute(sql: str, args: tuple = ()) -> int:
    """One atomic write to the bot-owned watchlist table; returns rowcount."""
    conn = psycopg.connect(
        host=os.environ.get("PGHOST", "timescaledb.market-data.svc.cluster.local"),
        user=os.environ.get("PGUSER", "postgres"),
        password=os.environ["PGPASSWORD"],
        dbname=os.environ.get("PGDATABASE", "postgres"),
    )
    try:
        conn.autocommit = True
        with conn.transaction():  # house pattern: one short write unit
            with conn.cursor() as cur:
                cur.execute(sql, args)
                return cur.rowcount
    finally:
        conn.close()


REGISTRY = users.Registry(OWNER, query)
REQUESTS = users.AccessRequests()


# ---------------------------------------------------------------- commands

def cmd_help(_text: str, chat: str = None) -> str:
    text = _help_text()
    if chat is None or REGISTRY.is_owner(chat):
        text += ("\n/users · /adduser · /rmuser — manage who has access (owner)")
    return text


def _help_text() -> str:
    return (
        "<b>Marketfredbot</b> — read-only commands:\n"
        "/status — pipeline heartbeat freshness\n"
        "/vix — VIX + India VIX\n"
        "/nifty · /sensex · /gold — close, day, YTD, 52w range, trend\n"
        "/fii — latest FII/DII net + 5-session FII trend\n"
        "/scores — screener top-5 today\n"
        "/stock TCS — price, trend, score, valuation, news for one stock\n"
        "/news TCS — tagged headlines + sentiment\n"
        "/top growth sp500 — best by value|quality|growth|momentum|risk\n"
        "/multibagger sp500 — small, fast-growing, high-return candidates\n"
        "/movers — who entered/left the screener top-20\n"
        "/track — how the screener's picks have done\n"
        "/watch — YOUR watchlist + holdings P&amp;L (add/rm); private to this chat\n"
        "/world — every index: close, day, 1m, YTD (/world asia)\n"
        "/index nikkei — one index in depth: 1w–1y, 52w range, trend, RSI\n"
        "/fx — USD/INR and the other pairs\n"
        "/macro — gold in INR, yield spreads, FII vs Nifty\n"
        "/digest — your daily digest on demand\n"
        "Daily digest: 08:00 IST · change alerts after the screener run (shared screener "
        "changes + your own watchlist)"
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
    return "<b>Volatility</b>\n" + stocks.quote_table(query, ["^VIX", "^INDIAVIX"])


def cmd_nifty(_text: str) -> str:
    return stocks.index_card(query, "^NSEI", "Nifty 50")


def cmd_sensex(_text: str) -> str:
    return stocks.index_card(query, "^BSESN", "Sensex")


def cmd_gold(_text: str) -> str:
    return stocks.index_card(query, "GC=F", "Gold futures (USD/oz)")


def cmd_index(text: str) -> str:
    return stocks.index_text(query, text.partition(" ")[2].strip())


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
    return stocks.top_text(query, "composite", "NIFTY500", 5)


def cmd_digest(_text: str, chat: str = None) -> str:
    return build_message(chat or OWNER)


def _arg(text: str) -> str:
    return text.partition(" ")[2].strip()


def cmd_stock(text: str) -> str:
    row, problem = stocks.pick_one(query, _arg(text))
    return problem or stocks.stock_card(query, row)


def cmd_news(text: str) -> str:
    row, problem = stocks.pick_one(query, _arg(text))
    return problem or stocks.news_text(query, row)


def cmd_top(text: str) -> str:
    factor, universe, problem = stocks.parse_top(text)
    return problem or stocks.top_text(query, factor, universe)


def cmd_multibagger(text: str) -> str:
    words = text.lower().split()[1:]
    if len(words) > 1 or (words and words[0] not in stocks.UNIVERSES):
        return "Usage: <code>/multibagger [nifty|sp500]</code>"
    return stocks.multibagger_text(query, stocks.UNIVERSES[words[0]] if words else "NIFTY500")


def cmd_movers(_text: str) -> str:
    return stocks.movers_text(query)


def cmd_track(_text: str) -> str:
    return stocks.track_text(query)


def cmd_macro(_text: str) -> str:
    return stocks.macro_text(query)


def cmd_world(text: str) -> str:
    region, problem = stocks.parse_world(text)
    return problem or stocks.world_text(query, region)


def cmd_fx(_text: str) -> str:
    return stocks.fx_text(query)


def cmd_watch(text: str, chat: str = None) -> str:
    chat = str(chat or OWNER)          # no chat (runbook one-liners) = the owner
    action, arg, qty, cost, note, problem = stocks.parse_watch(text)
    try:
        if problem:
            return problem
        if action == "list":
            return stocks.watch_text(query, chat)
        row, problem = stocks.pick_one(query, arg)
        if problem:
            return problem
        symbol = row[0]
        if action == "rm":
            gone = execute("DELETE FROM watchlist WHERE chat_id = %s AND symbol = %s",
                           (chat, symbol))
            return f"Removed {html.escape(symbol)}." if gone else (
                f"{html.escape(symbol)} was not on the watchlist.")
        # Re-adding keeps an existing position/note unless new values are given.
        execute(
            "INSERT INTO watchlist (chat_id, symbol, qty, avg_cost, note) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (chat_id, symbol) DO UPDATE SET "
            "qty = COALESCE(EXCLUDED.qty, watchlist.qty), "
            "avg_cost = COALESCE(EXCLUDED.avg_cost, watchlist.avg_cost), "
            "note = COALESCE(EXCLUDED.note, watchlist.note)",
            (chat, symbol, qty, cost, note),
        )
        held = f" — {qty:g} @ {cost:,.2f}" if qty else ""
        return f"Watching <b>{html.escape(row[1])}</b> ({html.escape(symbol)}){held}."
    except psycopg.Error as exc:
        if stocks.table_missing(exc):
            return ("Watchlist table not ready yet (schema 09 multi-user — "
                    "schema-configmap.yaml → schema job).")
        raise


def cmd_users(_text: str, chat: str = None) -> str:
    return users.users_text(REGISTRY, query)


def cmd_adduser(text: str, chat: str = None) -> str:
    target, name, problem = users.parse_adduser(text)
    if problem:
        return problem
    try:
        return users.add_user(execute, REGISTRY, target, name, str(chat or OWNER))
    except psycopg.Error as exc:
        if stocks.table_missing(exc):
            return "bot_users table not created yet (schema 09 — run the schema job)."
        raise


def cmd_rmuser(text: str, chat: str = None) -> str:
    target, problem = users.parse_rmuser(text)
    if problem:
        return problem
    try:
        return users.remove_user(execute, REGISTRY, target)
    except psycopg.Error as exc:
        if stocks.table_missing(exc):
            return "bot_users table not created yet (schema 09 — run the schema job)."
        raise


# Commands that need to know WHO is asking get (text, chat); the rest stay (text) so
# one-liners like COMMANDS['nifty']('/nifty') keep working. ADMIN is owner-only.
PERSONAL = {"start", "help", "digest", "watch", "users", "adduser", "rmuser"}
ADMIN = {"users", "adduser", "rmuser"}

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
    "stock": cmd_stock,
    "news": cmd_news,
    "top": cmd_top,
    "movers": cmd_movers,
    "multibagger": cmd_multibagger,
    "mb": cmd_multibagger,
    "track": cmd_track,
    "macro": cmd_macro,
    "world": cmd_world,
    "index": cmd_index,
    "fx": cmd_fx,
    "usdinr": cmd_fx,
    "watch": cmd_watch,
    "users": cmd_users,
    "adduser": cmd_adduser,
    "rmuser": cmd_rmuser,
}


# ---------------------------------------------------------------- transport

def send(text: str, chat: str = None) -> None:
    if len(text) > TELEGRAM_LIMIT:
        text = text[: TELEGRAM_LIMIT - 1] + "…"
    r = requests.post(f"{API}/sendMessage",
                      json={"chat_id": str(chat or OWNER), "text": text, "parse_mode": "HTML"},
                      timeout=30)
    if r.status_code != 200 or not r.json().get("ok"):
        print(f"ERROR sendMessage {r.status_code}: {r.text[:200]}", flush=True)


def handle(update: dict) -> None:
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return
    chat = str(msg.get("chat", {}).get("id", ""))
    text = (msg.get("text") or "").strip()

    if not REGISTRY.allowed(chat):
        who = (msg.get("from") or {})
        username = who.get("username")
        print(f"IGNORED chat={chat} user={username or who.get('id')} "
              f"text={text[:40]!r}", flush=True)
        if text and REQUESTS.should_notify(chat):   # tell the owner once; never answer them
            send(users.request_notice(chat, username, text), OWNER)
        return

    if not text:
        return
    cmd = text.split()[0].lstrip("/").split("@")[0].lower()
    handler = COMMANDS.get(cmd)
    if handler is None:
        send(f"Unknown command. {chr(10)}" + cmd_help("", chat), chat)
        return
    if cmd in ADMIN and not REGISTRY.is_owner(chat):
        send("That command is for the owner only.", chat)
        return
    try:
        send(handler(text, chat) if cmd in PERSONAL else handler(text), chat)
        print(f"answered /{cmd}", flush=True)
    except Exception as exc:  # noqa: BLE001 - one bad query must not kill the loop
        print(f"ERROR /{cmd}: {exc}", flush=True)
        send("Command failed — see logs (kubectl logs deploy/telegram-bot).", chat)


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


MENU = [
    ("stock", "Price, trend, score, valuation, news — /stock TCS"),
    ("watch", "Your watchlist + holdings P&L (add / rm)"),
    ("top", "Best by factor — /top growth sp500"),
    ("multibagger", "Small, fast-growing, high-return candidates"),
    ("movers", "Entered / left the screener top-20"),
    ("track", "How the screener's picks have done"),
    ("news", "Tagged headlines + sentiment — /news TCS"),
    ("world", "All world indices: day, 1m, YTD — /world asia"),
    ("index", "One index in depth — /index nikkei"),
    ("fx", "USD/INR and other currency pairs"),
    ("macro", "Gold in INR, yield spreads, FII vs Nifty"),
    ("scores", "Screener top-5"),
    ("digest", "Daily digest on demand"),
    ("status", "Pipeline heartbeat freshness"),
    ("vix", "VIX + India VIX"),
    ("nifty", "Nifty 50"),
    ("sensex", "Sensex"),
    ("gold", "Gold futures"),
    ("fii", "FII/DII net flows"),
    ("help", "All commands"),
]


def register_menu() -> None:
    """Best-effort: the Telegram command menu follows the code, not BotFather."""
    try:
        r = requests.post(f"{API}/setMyCommands", timeout=15, json={
            "commands": [{"command": c, "description": d} for c, d in MENU]})
        if r.status_code != 200 or not r.json().get("ok"):
            print(f"WARN setMyCommands {r.status_code}: {r.text[:120]}", flush=True)
    except (requests.RequestException, ValueError) as exc:
        print(f"WARN setMyCommands failed ({exc.__class__.__name__})", flush=True)


def main() -> int:
    me = requests.get(f"{API}/getMe", timeout=15).json().get("result", {})
    register_menu()
    print(f"listening as @{me.get('username')} for owner chat {OWNER[:2]}*** "
          f"+ {len(REGISTRY.members())} member(s)", flush=True)
    poll_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
