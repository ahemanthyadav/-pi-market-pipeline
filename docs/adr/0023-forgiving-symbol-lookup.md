# 0023. Forgiving symbol lookup: fuzzy first, AI only as a validated fallback, never writes on a guess

- Date: 2026-10-18
- Status: accepted

## Context
`/stock`, `/news` and `/watch` needed an exact symbol or a name fragment; a typo ("infosis", "microsft") or a nickname
("facebook", "big blue") answered "No stock matching". Options: fuzzy string matching only; send every query to an LLM;
or layers.

## Decision
`resolver.py` runs only when the exact/name lookup finds nothing, cheapest first:
1. **Fuzzy** (standard library `difflib`, no network) against all active universe symbols and normalised company names.
   A clear winner (score ≥ 0.84 and ≥ 0.06 ahead of the runner-up — measured on 25 real queries over the 998-row
   universe) is used with a visible note ("“infosis” → INFY.NS Infosys Ltd."); close calls become "Did you mean …".
2. **AI** (shared llm-gateway, `fast-json`, `BOT_AI_RESOLVE=1`) only when fuzzy cannot decide. Only the typed text and
   the fuzzy hints are sent — never the chat id. The answer counts **only if it is a real symbol in our universe**
   (`.NS` added for bare NSE tickers); cached in-process; 12 s timeout; any failure falls back to step 1's suggestions.
3. **`/watch` never writes on a corrected or AI-matched symbol**: it replies with the reading and asks for the exact
   symbol. Showing a card on a guess is harmless; storing a holding under a guess is not.

## Consequences
- Typos are handled with zero AI cost; AI calls are rare (nicknames, renamed companies — e.g. Zomato → ETERNAL.NS).
- The bot keeps answering when the gateway or provider is down (measured: 1.7 s fallback without a provider key).
- Tests use a real-universe sample (`tests/fixtures/universe_sample.json`: each test query's top candidates — same decisions as the full 998 rows); refresh it when the universe changes a lot.
- Same pattern for future free-text inputs (sector names, index names): deterministic first, AI validated against a
  closed list, never an unvalidated AI answer acting on data.
