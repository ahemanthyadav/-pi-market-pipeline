"""Natural-language command router for the Telegram bot.

Given free-text user input (e.g. "tcs price", "what's nifty at",
"show me fii flows"), returns (command, args, confidence) where:
  command  — one of the COMMANDS keys in bot.py (or None)
  args     — the text argument to pass to that command
  confidence — "nickname" / "phrase" / "keyword" / None

Routes checked in order:
  1. Exact command prefix (/cmd ...) — passed through unchanged, except when the
     command takes no free-text argument and the args name a stock
     ("/status cub" → /stock CUB.NS)
  2. Multi-word phrase routes ("price of TCS" → stock TCS)
  3. Nickname-first expansion ("facebook price" → stock META)
  4. Keyword-first routes ("tcs price" → stock TCS)
  5. Catch-all nickname anywhere in the text
  6. Caller-supplied `lookup` — the DB-backed universe resolver in bot.py, which
     also covers names that are not in the static nickname map ("cub" → CUB.NS)
  7. None — caller falls back to "unknown command"

The router itself stays pure: `lookup` is injectable so tests need no database.
"""
from __future__ import annotations

import re
from typing import Callable, Optional, Tuple

import nicknames

# Commands whose arguments are real free text (a symbol, company, factor or
# universe). Their args must never be hijacked into /stock: "/news tcs" is news
# about TCS, "/watch cub" adds CUB. Everything else (status, movers, digest,
# nifty …) takes no argument, so "<command> <stock>" means "show me that stock".
ARG_COMMANDS = frozenset({
    "stock", "news", "ask", "watch", "top", "scores", "screener",
    "multibagger", "mb", "sectors", "sector", "world", "index", "fx",
    "usdinr", "route", "adduser", "rmuser",
})

# Words that are never a symbol lookup on their own (command/filler words).
STOP_WORDS = frozenset(nicknames.KEYWORD_COMMANDS) | frozenset({
    "a", "all", "an", "and", "any", "are", "at", "current", "data", "detail",
    "details", "do", "for", "get", "give", "help", "in", "info", "is", "it",
    "latest", "me", "my", "now", "of", "on", "please", "pls", "plz", "report",
    "show", "tell", "the", "today", "what", "whats", "with", "you",
})

MAX_LOOKUP_WORDS = 4   # longer strings are sentences, not stock names


def _strip(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).strip()


def _norm(text: str) -> str:
    return _strip(text).lower()


def _expand_symbol(arg: str) -> str:
    """If arg is a nickname, return the symbol; otherwise return arg unchanged."""
    sym = nicknames.NICKNAMES.get(arg)
    return sym if sym and sym != "none" else arg


def _content(text: str) -> str:
    """The words of `text` that could name a stock (drop command/filler words)."""
    return " ".join(w for w in _norm(text).split() if w not in STOP_WORDS)


def _lookup_symbol(lookup: Optional[Callable[[str], Optional[str]]], text: str) -> Optional[str]:
    """Ask the caller's resolver for a unique symbol; None if no usable match.

    Never raises: a DB blip must not stop the bot from answering.
    """
    if lookup is None:
        return None
    q = _content(text)
    if not q or len(q.split()) > MAX_LOOKUP_WORDS or not re.search(r"[A-Za-z]", q):
        return None
    try:
        return lookup(q) or None
    except Exception:  # noqa: BLE001 — routing is best-effort
        return None


def symbol_from_args(command: str, args: str,
                     lookup: Optional[Callable[[str], Optional[str]]] = None) -> Optional[str]:
    """Symbol when a no-argument command is followed by a stock name, else None.

    Used before dispatch: "/status cub", "/movers cub", "/digest tcs" would
    otherwise ignore the argument. Commands in ARG_COMMANDS keep their argument.
    """
    if not args or command in ARG_COMMANDS:
        return None
    return _lookup_symbol(lookup, args)


def _command(cmd: str, commands=None):
    """Bot command for a typed word, or None. `commands` = bot.COMMANDS keys."""
    if cmd in nicknames.KEYWORD_COMMANDS:
        return nicknames.KEYWORD_COMMANDS[cmd]
    if commands and cmd in commands:
        return cmd
    return None


def route(text: str, lookup: Optional[Callable[[str], Optional[str]]] = None,
          commands=None) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Route free text to (command, args, confidence).

    `lookup` is an optional callable str → symbol, used for stock names that the
    static nickname map does not know (bot.py passes the universe resolver).
    `commands` is the bot's command set, so "/status …" is recognised even when
    the word is missing from the keyword map.
    Returns (None, None, None) when nothing matches.
    """
    t = _strip(text)
    if not t:
        return None, None, None

    nt = _norm(t)
    words = nt.split()

    # 1. Exact command prefix (/cmd ...) — pass through unchanged
    m = re.match(r"^/(\w+)(@\w+)?\s*(.*)$", t, re.I)
    if m:
        cmd = _command(m.group(1).lower(), commands)
        args = m.group(3).strip()
        if cmd:
            # If any word in args is a nickname, route to stock instead
            arg_words = args.split()
            for word in arg_words:
                if word in nicknames.NICKNAMES:
                    sym = nicknames.NICKNAMES[word]
                    if sym != "none":
                        return "stock", sym, "nickname"
            # A command with no real argument ("/status cub", "/movers cub")
            # whose args name a stock means that stock.
            if args and cmd not in ARG_COMMANDS:
                sym = _lookup_symbol(lookup, args)
                if sym:
                    return "stock", sym, "lookup"
            return cmd, args, "exact"
        # Not a real command — treat the rest as regular text for nickname/keyword checks
        t = args
        nt = _norm(t)
        words = nt.split()

    # 2. Multi-word phrase routes (longest phrase wins)
    best_phrase = None
    best_len = 0
    for phrase, (cmd, tmpl) in nicknames.PHRASE_ROUTES.items():
        if nt.startswith(phrase + " ") or nt == phrase:
            if len(phrase) > best_len:
                best_phrase = phrase
                best_len = len(phrase)
                route_cmd, route_tmpl = cmd, tmpl
    if best_phrase is not None:
        # Extract arg from original text (preserve case), at same position
        arg = t[len(best_phrase):].strip()
        args = route_tmpl.replace("{arg}", arg).strip() if "{arg}" in route_tmpl else route_tmpl
        return route_cmd, args, "phrase"

    # 3. Nickname-first expansion: "tcs price" → stock TCS,
    #    "hdfc bank price" → stock HDFCBANK (multi-word nickname)
    if words and words[0] in nicknames.NICKNAMES:
        sym = nicknames.NICKNAMES[words[0]]
        if sym == "none":
            return None, None, None
        rest = " ".join(words[1:])
        if rest and rest in nicknames.KEYWORD_COMMANDS:
            cmd = nicknames.KEYWORD_COMMANDS[rest]
            return cmd, sym, "nickname"
        return "stock", sym, "nickname"

    # 3b. Multi-word nickname: "hdfc bank price" → HDFCBANK, "tata motors pv" → TMPV
    #     longest prefix wins, so a 3-word name is never cut to its first two words
    for n in (3, 2):
        if len(words) >= n and " ".join(words[:n]) in nicknames.NICKNAMES:
            sym = nicknames.NICKNAMES[" ".join(words[:n])]
            if sym == "none":
                return None, None, None
            rest = " ".join(words[n:])
            if rest and rest in nicknames.KEYWORD_COMMANDS:
                cmd = nicknames.KEYWORD_COMMANDS[rest]
                return cmd, sym, "nickname"
            return "stock", sym, "nickname"

    # 4. Keyword-first routes: "tcs price" → stock TCS
    if len(words) >= 2:
        first, second = words[0], words[1]
        if first in nicknames.KEYWORD_COMMANDS:
            cmd = nicknames.KEYWORD_COMMANDS[first]
            arg_word = words[1]
            args = _expand_symbol(arg_word)
            if len(words) > 2:
                args = args + " " + " ".join(words[2:])
            return cmd, args, "keyword"
        if second in nicknames.KEYWORD_COMMANDS:
            cmd = nicknames.KEYWORD_COMMANDS[second]
            arg_word = words[0]
            args = _expand_symbol(arg_word)
            if len(words) > 2:
                args = args + " " + " ".join(words[2:])
            return cmd, args, "keyword"

    # 5. Single word that is a keyword command
    if len(words) == 1 and words[0] in nicknames.KEYWORD_COMMANDS:
        return nicknames.KEYWORD_COMMANDS[words[0]], "", "keyword"

    # 6. Single word that is a nickname → stock
    if len(words) == 1 and words[0] in nicknames.NICKNAMES:
        sym = nicknames.NICKNAMES[words[0]]
        if sym == "none":
            return None, None, None
        return "stock", sym, "nickname"

    # 7. Catch-all: any word in the text is a nickname → stock with that symbol
    for word in words:
        if word in nicknames.NICKNAMES:
            sym = nicknames.NICKNAMES[word]
            if sym == "none":
                continue
            return "stock", sym, "nickname"

    # 8. Universe lookup (DB-backed, injected): "cub" → CUB.NS, "city union" → CUB.NS
    sym = _lookup_symbol(lookup, t)
    if sym:
        return "stock", sym, "lookup"

    return None, None, None


def format_route(command: str, args: str, confidence: str) -> str:
    """Human-readable explanation of a route (for /route command or debugging)."""
    conf_word = {
        "exact": "exact command",
        "phrase": "phrase match",
        "keyword": "keyword match",
        "nickname": "nickname expansion",
        "lookup": "universe lookup",
    }.get(confidence, confidence)
    arg_part = f" with args <code>{args}</code>" if args else ""
    return f"Routed to <b>/{command}</b>{arg_part} ({conf_word})."


if __name__ == "__main__":
    # Smoke test
    cases = [
        "/stock TCS",
        "tcs price",
        "facebook price",
        "hdfc bank price",
        "what's nifty at",
        "show me fii flows",
        "top growth sp500",
        "my watchlist",
        "daily digest",
        "vix level",
        "gold price",
        "usd inr rate",
        "apple",
        "random gibberish xyz",
    ]
    for c in cases:
        cmd, args, conf = route(c)
        print(f"{c!r:35} → {cmd} {args!r} ({conf})")
