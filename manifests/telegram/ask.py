"""/ask — free-text questions answered from DB facts only (ML-7d family, ADR 0022/0024; 2026-10-19).

Flow: find the subject (stock via the forgiving resolver, index/FX/flows/news by keyword), gather a small
FACTS JSON from the DB (public data only — never chat ids or watchlists), ask the gateway (`general`) to
answer using ONLY those facts, then accept the answer only if every number and direction checks out
(factcheck.py — the same rule as ML-7a). Two failures → the bot shows the facts themselves instead of the
model's prose. A question the facts cannot answer is refused, never guessed. News questions use semantic
search over headline_embeddings (same embedding model only — ADR 0024).

Env: BOT_AI_RESOLVE, LLM_BASE_URL, LLM_API_KEY (Secret llm-gateway-key). Degrades to plain commands when off.
"""
import json
import os
import re

import factcheck
import stocks

NEWS_K = 6
NEWS_DAYS = 21
TOPICS = {
    "news": re.compile(r"\bnews|headline|recent|latest|said|announcement", re.I),
    "flows": re.compile(r"\bfii|\bdii|flow|foreign|institutional", re.I),
    "fx": re.compile(r"\bfx|usdinr|rupee|dollar|euro|yen|currency", re.I),
}


def q_or_none(q, sql, args=()):
    try:
        return q(sql, args)
    except Exception:  # noqa: BLE001 — a missing table must not kill the command
        return None


def stock_facts(q, row):
    sym = row[0]
    m = q_or_none(q, "SELECT metric, value FROM stock_metrics_daily WHERE symbol = %s "
                     "AND ts >= now() - interval '400 days' ORDER BY ts DESC LIMIT 12", (sym,))
    f = {"symbol": sym, "name": row[1], "sector": row[2], "universe": row[3],
         "metrics": {k: v for k, v in (m or [])}}
    sc = q_or_none(q, "SELECT composite, rank FROM stock_scores WHERE symbol = %s "
                      "AND ts >= now() - interval '400 days' ORDER BY ts DESC LIMIT 1", (sym,))
    if sc:
        f["score"] = {"composite": sc[0][0], "rank": sc[0][1]}
    news = news_facts(q, sym, days=NEWS_DAYS, exact=True)
    if news:
        f["recent_headlines"] = news
    return f


def news_facts(q, text, k=NEWS_K, days=NEWS_DAYS, exact=False):
    """Nearest headlines: semantic search when the embedding table has this text's model rows, else LIKE."""
    rows = None
    if not exact and os.environ.get("BOT_AI_RESOLVE") == "1":
        try:
            model, vecs = embed_question(text)
            if vecs:
                rows = q_or_none(
                    q, f"SELECT h.headline, h.ts::date FROM headline_embeddings e "
                    f"JOIN raw_headlines h ON h.id = e.headline_id "
                    f"WHERE e.model = %s AND e.ts >= now() - interval '{int(days)} days' "
                    f"ORDER BY e.embedding <=> %s::vector LIMIT {int(k)}",
                    (model, "[" + ",".join(f"{x:.6g}" for x in vecs[0]) + "]"))
        except Exception:  # noqa: BLE001 — semantic search is an enhancement, not a requirement
            rows = None
    if rows is None:
        rows = q_or_none(
            q, f"SELECT headline, ts::date FROM raw_headlines WHERE ts >= now() - interval '{int(days)} days' "
            f"AND headline ILIKE %s ORDER BY ts DESC LIMIT {int(k)}", (f"%{text}%",))
    return [f"{d}: {h[:200]}" for h, d in (rows or [])]


def embed_question(text):
    import urllib.request
    body = {"model": "embed", "input": [text[:1000]], "encoding_format": "float", "disable_fallbacks": True}
    req = urllib.request.Request(os.environ["LLM_BASE_URL"].rstrip("/") + "/embeddings",
                                 data=json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + os.environ["LLM_API_KEY"],
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        model = (r.headers.get("x-litellm-model-name") or "").split("/", 1)[-1]
        data = json.load(r)
    return model, [d["embedding"] for d in data["data"]]


def macro_facts(q):
    f = {}
    fx = q_or_none(q, "SELECT pair, rate FROM fx_rates WHERE pair = 'USDINR=X' "
                      "AND ts >= now() - interval '10 days' ORDER BY ts DESC LIMIT 2")
    if fx:
        f["usdinr"] = {"latest": fx[0][1], "prev": fx[1][1] if len(fx) > 1 else None}
    fl = q_or_none(q, "SELECT flow_type, amount FROM capital_flows WHERE direction = 'net' "
                      "AND ts >= now() - interval '10 days' ORDER BY ts DESC LIMIT 4")
    if fl:
        f["flows_rs_cr_latest"] = {t: a for t, a in fl}
    y = q_or_none(q, "SELECT instrument, yield FROM bond_yields WHERE instrument IN ('^TNX','IN_GS_10Y') "
                      "AND ts >= now() - interval '10 days' ORDER BY ts DESC LIMIT 4")
    if y:
        f["yields"] = {i: v for i, v in y}
    return f


def index_facts(q, arg):
    t = stocks.find_index(q, arg)
    if not t:
        return None
    rows = q_or_none(q, "SELECT ts::date, close FROM index_prices WHERE ticker = %s "
                        "AND ts >= now() - interval '10 days' ORDER BY ts DESC LIMIT 3", (t[0],))
    if not rows:
        return None
    f = {"index": t[1], "ticker": t[0], "close": rows[0][1], "prev_close": rows[1][1] if len(rows) > 1 else None}
    ytd = stocks.ytd_map(q, [t[0]])
    if ytd.get(t[0]) is not None:
        f["ytd_pct"] = round(ytd[t[0]], 2)
    return f


def build_facts(q, question):
    """-> (facts, subject) or (None, None) when the question maps to nothing we store."""
    # "TCS outlook" is a question ABOUT TCS: try the whole phrase, then each word as a symbol.
    for cand in [question] + question.split():
        row, _problem, _note = stocks.pick_one_ex(q, cand)
        if row:
            return stock_facts(q, row), row[0]
    if TOPICS["news"].search(question):
        words = [w for w in re.findall(r"[A-Za-z0-9&\-]{3,}", question) if w.lower() not in
                 ("news", "headline", "recent", "latest", "said", "about", "what", "tell", "any")]
        f = {"headlines": news_facts(q, " ".join(words[:3]))}
        return (f, "news") if f["headlines"] else (None, None)
    if TOPICS["flows"].search(question):
        f = macro_facts(q)
        return (f, "flows") if f.get("flows_rs_cr_latest") else (None, None)
    if TOPICS["fx"].search(question):
        f = macro_facts(q)
        return (f, "fx") if f.get("usdinr") else (None, None)
    f = index_facts(q, question)
    return (f, "index") if f else (None, None)


SYSTEM = ("You answer a stock-bot question using ONLY the facts JSON given. Copy numbers exactly as given "
          "or rounded to at most 2 decimals (a percent form of a given value is fine: 0.0259 -> 2.59%); "
          "never compute new numbers (no differences, no averages); never add facts the JSON does not "
          "contain. If the facts cannot answer the question, say exactly what they do show instead of "
          "guessing. 2-4 short sentences. Reply as JSON: {\"answer\": \"...\"}.")


def answer(q, question, asker=None):
    """-> reply text. Never raises: gateway down or two failed checks → show the facts."""
    facts, subject = build_facts(q, question)
    if not facts:
        return ("I can only answer from what the pipeline stores: a stock, an index, FX, flows, or recent "
                "news. Try <code>/ask TCS outlook</code>, <code>/ask nifty this week</code>, "
                "<code>/ask fii flows</code>, <code>/ask news infosys</code>.")
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Question: {question[:300]}\nFacts JSON:\n"
                                        + json.dumps(facts, separators=(",", ":"))}]
    directions = subject != "news"          # headline text carries no sign context — numbers-only check there
    if asker is None:
        asker = _ask
    for attempt in (1, 2):
        try:
            text = asker(msgs)
        except Exception:  # noqa: BLE001 — degrade to the facts table
            return _facts_table(facts, subject)
        bad = factcheck.bad_numbers(text, facts) + (factcheck.wrong_directions(text, facts) if directions else [])
        if text and len(text) <= 900 and not bad:
            return f"<b>{subject}</b> — {stocks.esc(text)}"
        msgs += [{"role": "assistant", "content": json.dumps({"answer": text})},
                 {"role": "user", "content": f"These numbers/directions are not supported by the facts: "
                                             f"{', '.join(bad) or 'too long/empty'}. Rewrite using only the facts JSON."}]
    return _facts_table(facts, subject)


def _ask(prompt_msgs):
    import requests
    r = requests.post(os.environ["LLM_BASE_URL"].rstrip("/") + "/chat/completions", timeout=30,
                      headers={"Authorization": "Bearer " + os.environ["LLM_API_KEY"]},
                      json={"model": "general", "temperature": 0.2, "max_tokens": 800,
                            "response_format": {"type": "json_object"}, "messages": prompt_msgs})
    r.raise_for_status()
    content = factcheck.strip_fences(r.json()["choices"][0]["message"]["content"] or "{}")
    try:
        return json.loads(content).get("answer") or ""
    except (ValueError, AttributeError):
        return ""


def _facts_table(facts, subject):
    lines = [f"<b>{subject}</b> — the facts themselves (AI answer failed the check):"]
    for k, v in facts.items():
        if isinstance(v, dict):
            lines += [f"<code>{k}</code> " + " · ".join(f"{a}={b}" for a, b in v.items())]
        elif isinstance(v, list):
            lines += [f"<code>{k}</code>"] + [f"· {x}" for x in v[:4]]
        else:
            lines.append(f"<code>{k}</code> {v}")
    return "\n".join(lines)
