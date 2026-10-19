"""Forgiving symbol lookup for /stock, /news, /watch (2026-10-18).

Called only when the exact/name lookup in stocks.resolve() finds nothing. Three layers, cheapest first:

1. **Fuzzy** (standard library, no network): the query is compared with every active universe
   symbol (".NS" stripped) and company name ("Ltd.", "Inc." … stripped). A clear winner is used
   directly ("relaince" -> RELIANCE.NS); close calls become a "Did you mean" list.
2. **AI** (only if fuzzy cannot decide, and only when enabled): the typed text alone — never the
   chat id — goes to the shared llm-gateway (`fast-json`) with the fuzzy candidates as hints. The
   answer is accepted only if it is a real symbol in our universe; anything else is ignored.
   Nicknames like "facebook" -> META or "big blue" -> IBM are what this layer is for.
3. Gateway down / disabled / no answer -> the fuzzy suggestions (or "no match") as before.

Env (bot Deployment): BOT_AI_RESOLVE=1 enables layer 2; LLM_BASE_URL, LLM_API_KEY from Secret
llm-gateway-key (ADR 0022). Answers are cached in-process (no repeated calls for the same text).
"""
import json
import os
import re
import time
from difflib import SequenceMatcher

AUTO = 0.84          # fuzzy score needed to pick without asking
MARGIN = 0.06        # ... and lead over the runner-up
SUGGEST = 0.55       # below this a candidate is not worth suggesting
SUFFIX = re.compile(r"\b(ltd|limited|inc|corp|corporation|co|company|plc|the|class [abc]|\(class [abc]\))\b\.?", re.I)
_universe = {"rows": None, "at": 0.0}
_ai_cache = {}


def norm(s):
    s = SUFFIX.sub(" ", (s or "").lower().replace(".ns", " ").replace("&", " and "))
    return re.sub(r"[^a-z0-9 ]+", " ", s).split()


def score(query, symbol, name):
    """0..1 similarity of a typed query to one universe row (pure)."""
    q = " ".join(norm(query))
    if not q:
        return 0.0
    sym = symbol.upper().removesuffix(".NS").lower()
    words = norm(name)
    full = " ".join(words)
    best = max(SequenceMatcher(None, q, sym).ratio(),
               SequenceMatcher(None, q, full).ratio(),
               SequenceMatcher(None, q, " ".join(words[:len(q.split())])).ratio())   # name prefix
    if len(q) >= 4 and full.startswith(q):
        best = max(best, 0.9)
    return best


def universe(q, ttl=3600):
    """Active universe rows, cached for an hour (998 rows — cheap)."""
    if not _universe["rows"] or time.time() - _universe["at"] > ttl:
        rows = q("SELECT symbol, name, sector, universe, currency FROM universe_constituents "
                 "WHERE active ORDER BY symbol")
        if rows:                                  # never cache an empty answer (a DB blip)
            _universe.update(rows=rows, at=time.time())
        return rows or []
    return _universe["rows"]


def fuzzy(rows, query, k=5):
    """[(score, row)] best first, only candidates above SUGGEST."""
    ranked = sorted(((score(query, r[0], r[1]), r) for r in rows), key=lambda x: -x[0])
    return [(s, r) for s, r in ranked[:k] if s >= SUGGEST]


def ai_pick(query, candidates, rows, asker=None):
    """Ask the gateway for the ticker; return a universe row or None. Never raises."""
    if os.environ.get("BOT_AI_RESOLVE") != "1" or not os.environ.get("LLM_API_KEY"):
        return None
    key = " ".join(norm(query))
    if key in _ai_cache:
        sym = _ai_cache[key]
    else:
        hints = ", ".join(f"{r[0]} ({r[1]})" for _s, r in candidates) or "none"
        prompt = (f'A user of a stock bot typed: "{query}". Which listed company do they mean? The bot covers '
                  f"the S&P 500 (plain tickers like AAPL, BRK-B) and the NIFTY 500 (NSE tickers ending in .NS). "
                  f"Fuzzy-match hints from the bot's list: {hints}. Reply as JSON {{\"symbol\": \"TICKER\"}} using the "
                  f"exact ticker format above, or {{\"symbol\": null}} if it is not a company in those indices.")
        try:
            sym = (asker or _ask)(prompt)
        except Exception:  # noqa: BLE001 — the bot must answer even if the gateway is down
            return None
        _ai_cache[key] = sym
    if not sym:
        return None
    by_symbol = {r[0].upper(): r for r in rows}
    s = str(sym).strip().upper()
    return by_symbol.get(s) or by_symbol.get(s + ".NS")      # only a real universe symbol counts


def _ask(prompt):
    import requests
    r = requests.post(os.environ["LLM_BASE_URL"].rstrip("/") + "/chat/completions", timeout=12,
                      headers={"Authorization": "Bearer " + os.environ["LLM_API_KEY"]},
                      json={"model": "fast-json", "temperature": 0, "max_tokens": 40,
                            "response_format": {"type": "json_object"},
                            "messages": [{"role": "user", "content": prompt}]})
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"] or "{}"
    try:
        return json.loads(content).get("symbol")
    except (ValueError, AttributeError):
        m = re.search(r"[A-Z][A-Z0-9&\-]{0,14}(?:\.NS)?", content)
        return m.group(0) if m else None


def suggest(q, query, asker=None):
    """-> (row, note) to show a stock, or (None, message) with suggestions / no match."""
    rows = universe(q)
    cands = fuzzy(rows, query)
    top = cands[0][0] if cands else 0.0
    second = cands[1][0] if len(cands) > 1 else 0.0
    if cands and top >= AUTO and top - second >= MARGIN:
        return cands[0][1], "fuzzy"
    hit = ai_pick(query, cands, rows, asker)
    if hit:
        return hit, "ai"
    if cands:
        return None, "Did you mean:\n" + "\n".join(f"<code>{_esc(r[0])}</code> — {_esc(r[1])}" for _s, r in cands[:4])
    return None, None


def _esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
