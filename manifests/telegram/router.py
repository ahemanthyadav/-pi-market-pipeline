"""Natural-language command router for the Telegram bot.

Given free-text user input (e.g. "tcs price", "what's nifty at",
"show me fii flows"), returns (command, args, confidence) where:
  command  — one of the COMMANDS keys in bot.py (or None)
  args     — the text argument to pass to that command
  confidence — "nickname" / "phrase" / "keyword" / None

Routes checked in order:
  1. Exact command prefix (/cmd ...) — passed through unchanged
  2. Multi-word phrase routes ("price of TCS" → stock TCS)
  3. Nickname-first expansion ("facebook price" → stock META)
  4. Keyword-first routes ("tcs price" → stock TCS)
  5. None — caller falls back to "unknown command"

Designed so AI (llm-gateway general capability) can be layered on top later
without changing the routing contract.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

import nicknames


def _strip(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).strip()


def _norm(text: str) -> str:
    return _strip(text).lower()


def _expand_symbol(arg: str) -> str:
    """If arg is a nickname, return the symbol; otherwise return arg unchanged."""
    sym = nicknames.NICKNAMES.get(arg)
    return sym if sym and sym != "none" else arg


def route(text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Route free text to (command, args, confidence).

    Returns (None, None, None) when nothing matches — caller should
    fall back to its existing "unknown command" handling.
    """
    t = _strip(text)
    if not t:
        return None, None, None

    nt = _norm(t)
    words = nt.split()

    # 1. Exact command prefix (/cmd ...) — pass through unchanged
    m = re.match(r"^/(\w+)(@\w+)?\s*(.*)$", t, re.I)
    if m:
        cmd = m.group(1).lower()
        args = m.group(3).strip()
        if cmd in nicknames.KEYWORD_COMMANDS:
            # If any word in args is a nickname, route to stock instead
            arg_words = args.split()
            for word in arg_words:
                if word in nicknames.NICKNAMES:
                    sym = nicknames.NICKNAMES[word]
                    if sym != "none":
                        return "stock", sym, "nickname"
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

    # 3. Nickname-first expansion: "facebook price" → stock META,
    #    "big blue price" → stock IBM (multi-word nickname)
    if words and words[0] in nicknames.NICKNAMES:
        sym = nicknames.NICKNAMES[words[0]]
        if sym == "none":
            return None, None, None
        rest = " ".join(words[1:])
        if rest and rest in nicknames.KEYWORD_COMMANDS:
            cmd = nicknames.KEYWORD_COMMANDS[rest]
            return cmd, sym, "nickname"
        return "stock", sym, "nickname"

    # 3b. Multi-word nickname: "big blue price" → stock IBM
    if len(words) >= 2:
        two_word = words[0] + " " + words[1]
        if two_word in nicknames.NICKNAMES:
            sym = nicknames.NICKNAMES[two_word]
            if sym == "none":
                return None, None, None
            rest = " ".join(words[2:])
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

    return None, None, None


def format_route(command: str, args: str, confidence: str) -> str:
    """Human-readable explanation of a route (for /route command or debugging)."""
    conf_word = {
        "exact": "exact command",
        "phrase": "phrase match",
        "keyword": "keyword match",
        "nickname": "nickname expansion",
    }.get(confidence, confidence)
    arg_part = f" with args <code>{args}</code>" if args else ""
    return f"Routed to <b>/{command}</b>{arg_part} ({conf_word})."


if __name__ == "__main__":
    # Smoke test
    cases = [
        "/stock TCS",
        "tcs price",
        "facebook price",
        "big blue price",
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
