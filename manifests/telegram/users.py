"""Multi-user layer for the Telegram image (ADR 0012, 2026-10-12).

Pure logic — no database or network at import time; callers pass `query` / `execute`
callables, so the same code is used by the bot, the digest and the alert jobs and is
unit-tested with fakes (tests/test_multiuser.py).

Model
  * The OWNER is whoever the Secret's TELEGRAM_CHAT_ID names. The owner is always allowed
    and is the only one who can manage users.
  * MEMBERS are rows of `bot_users` (active = true). Adding or removing one needs no Secret
    edit and no restart: /adduser, /rmuser, /users in the owner's chat.
  * Everyone gets their own watchlist/holdings (watchlist.chat_id), their own digest and
    their own change alerts. Market data (indices, screener, FX…) is shared and read-only.
  * An unknown chat is never answered (the bot is public — anyone can message it). The owner
    is told ONCE per chat per day, with a ready-to-send /adduser line.

Failure model: if `bot_users` does not exist yet (schema 09 not applied) or the DB blips,
the registry degrades to "owner only" / last-known members — it never locks the owner out.
"""

import html
import re
import time

MAX_MEMBERS = 20
REQUEST_COOLDOWN = 24 * 3600      # one access notice per unknown chat per day
REQUEST_BURST = (10, 3600)        # ...and at most 10 notices an hour overall (spam guard)
CACHE_TTL = 30                    # seconds the member list is cached

MEMBERS_SQL = "SELECT chat_id, name FROM bot_users WHERE active ORDER BY added_at, chat_id"

ADMIN_USAGE = (
    "<b>Users</b> (owner only)\n"
    "<code>/users</code> — who has access\n"
    "<code>/adduser 123456789 Alice</code> — give a chat access (own watchlist, digest, alerts)\n"
    "<code>/rmuser 123456789</code> — remove access (their watchlist is kept; re-adding restores it)"
)


def valid_chat_id(value) -> bool:
    """Telegram chat ids are integers; groups/supergroups are negative."""
    return bool(re.fullmatch(r"-?[0-9]{5,20}", value or ""))


def table_missing(exc) -> bool:
    return exc.__class__.__name__ in ("UndefinedTable", "UndefinedColumn")


class Registry:
    """Who may talk to the bot: the owner, plus the active members (cached briefly)."""

    def __init__(self, owner, query, ttl=CACHE_TTL, clock=time.monotonic, log=print):
        self.owner = str(owner)
        self._query = query
        self._ttl = ttl
        self._clock = clock
        self._log = log
        self._members = {}
        self._loaded_at = None

    def invalidate(self):
        self._loaded_at = None

    def members(self) -> dict:
        """{chat_id: name}; stale cache on a DB error, empty if never loaded."""
        now = self._clock()
        if self._loaded_at is not None and now - self._loaded_at < self._ttl:
            return self._members
        try:
            self._members = {str(c): n for c, n in self._query(MEMBERS_SQL, ())}
        except Exception as exc:  # noqa: BLE001 - must never lock the owner out
            if not table_missing(exc):
                self._log(f"WARN member list unavailable ({exc.__class__.__name__}); "
                          f"using last known ({len(self._members)})")
        self._loaded_at = now
        return self._members

    def is_owner(self, chat) -> bool:
        return str(chat) == self.owner

    def allowed(self, chat) -> bool:
        chat = str(chat)
        return chat == self.owner or chat in self.members()

    def display(self, chat) -> str:
        chat = str(chat)
        return "owner" if chat == self.owner else self.members().get(chat, "?")

    def recipients(self) -> list:
        return [(self.owner, "owner")] + [(c, n) for c, n in self.members().items()
                                          if c != self.owner]


def recipients_for_jobs(query, owner, log=print) -> list:
    """Digest/alert recipients (owner first). Same degradation as Registry."""
    return Registry(owner, query, ttl=0, log=log).recipients()


# ---------------------------------------------------------------- admin commands

def parse_adduser(text):
    """'/adduser <chat_id> [name…]' → (chat_id, name, error)."""
    parts = text.split(None, 2)
    if len(parts) < 2:
        return None, None, ADMIN_USAGE
    chat = parts[1]
    if not valid_chat_id(chat):
        return None, None, ("That does not look like a chat id (digits, optional leading "
                            "minus).\n" + ADMIN_USAGE)
    name = re.sub(r"\s+", " ", parts[2]).strip()[:40] if len(parts) > 2 else ""
    return chat, name or "user", None


def parse_rmuser(text):
    """'/rmuser <chat_id>' → (chat_id, error)."""
    parts = text.split()
    if len(parts) != 2 or not valid_chat_id(parts[1]):
        return None, ADMIN_USAGE
    return parts[1], None


def add_user(execute, registry, chat, name, added_by) -> str:
    if registry.is_owner(chat):
        return "That is the owner chat — it already has full access."
    if chat not in registry.members() and len(registry.members()) >= MAX_MEMBERS:
        return f"User limit reached ({MAX_MEMBERS}). Remove someone first."
    execute(
        "INSERT INTO bot_users (chat_id, name, active, added_by) VALUES (%s, %s, true, %s) "
        "ON CONFLICT (chat_id) DO UPDATE SET name = EXCLUDED.name, active = true",
        (chat, name, added_by))
    registry.invalidate()
    return (f"Added <b>{html.escape(name)}</b> (<code>{html.escape(chat)}</code>). They now have "
            "their own watchlist, digest and alerts. Ask them to send /start to the bot.")


def remove_user(execute, registry, chat) -> str:
    if registry.is_owner(chat):
        return "The owner cannot be removed."
    gone = execute("UPDATE bot_users SET active = false WHERE chat_id = %s AND active", (chat,))
    registry.invalidate()
    if not gone:
        return f"<code>{html.escape(chat)}</code> is not an active user."
    return (f"Removed <code>{html.escape(chat)}</code>. Their watchlist is kept; "
            "/adduser restores it.")


def users_text(registry, query) -> str:
    counts = {}
    try:
        counts = {str(c): n for c, n in query(
            "SELECT chat_id, count(*) FROM watchlist GROUP BY chat_id", ())}
    except Exception as exc:  # noqa: BLE001 - counts are decoration
        if not table_missing(exc):
            raise
    lines = ["<b>Users</b>"]
    for chat, name in registry.recipients():
        n = counts.get(chat, 0)
        tag = "owner" if registry.is_owner(chat) else html.escape(name)
        lines.append(f"• {tag} — <code>{html.escape(chat)}</code> · "
                     f"{n} watched symbol{'s' if n != 1 else ''}")
    if len(lines) == 2 and registry.members() == {}:
        lines.append("No other users yet. " + "Add one with /adduser.")
    return "\n".join(lines)


# ---------------------------------------------------------------- access requests

class AccessRequests:
    """Rate-limits the 'someone unknown messaged the bot' notices to the owner."""

    def __init__(self, clock=time.time):
        self._clock = clock
        self._last = {}
        self._recent = []

    def should_notify(self, chat) -> bool:
        now = self._clock()
        if now - self._last.get(chat, -REQUEST_COOLDOWN) < REQUEST_COOLDOWN:
            return False
        limit, window = REQUEST_BURST
        self._recent = [t for t in self._recent if now - t < window]
        if len(self._recent) >= limit:
            return False
        self._last[chat] = now
        self._recent.append(now)
        return True


def request_notice(chat, username, text) -> str:
    who = f"@{username}" if username and not str(username).isdigit() else "a user"
    kind = "group" if str(chat).startswith("-") else "private chat"
    snippet = html.escape((text or "")[:40])
    return (f"<b>Access request</b> from {html.escape(who)} ({kind}) — they sent "
            f"<code>{snippet}</code>.\n"
            f"To allow them: <code>/adduser {html.escape(str(chat))} Name</code>\n"
            "Ignore this to keep them out; you will not be asked again for 24 h.")


# ---------------------------------------------------------------- fan-out (digest, alerts)

def deliver(recipients, owner, make_text, send, log=print) -> int:
    """Send one personalised message per recipient; one person's failure never blocks the rest.

    make_text(chat) -> str | None (None = nothing to send); send(text, chat) -> bool.
    Returns the process exit code: 1 if the owner's message failed, or if every attempted
    send failed; 0 otherwise (member failures are logged as WARN only).
    """
    attempted = ok = 0
    owner_failed = False
    for chat, name in recipients:
        try:
            text = make_text(chat)
        except Exception as exc:  # noqa: BLE001 - isolate per-user build errors
            log(f"ERROR building message for {name}: {exc.__class__.__name__}: {exc}")
            attempted += 1
            owner_failed = owner_failed or str(chat) == str(owner)
            continue
        if text is None:
            continue
        attempted += 1
        if send(text, chat):
            ok += 1
        else:
            if str(chat) == str(owner):
                owner_failed = True
            else:
                log(f"WARN send to {name} failed (blocked the bot, or left the chat?)")
    return 1 if owner_failed or (attempted and not ok) else 0
