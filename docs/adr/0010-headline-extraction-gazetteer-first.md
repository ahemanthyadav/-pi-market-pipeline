# 0010. Headline extraction v1: gazetteer-first, deterministic — no model on the TX2

- Date: 2026-10-09
- Status: accepted (deployed — headline-ner:v3 live, 00:45 PDT daily)

## Context
Findings Tier 1 #2 asks for entity/event extraction over `raw_headlines` to feed
the v2 intelligence layer (per-company sentiment, event timelines; GraphRAG later
per architecture §8). Two hosting options existed: model-based NER (spaCy or an
LLM) on the TX2, or a deterministic gazetteer. The roadmap (§7) places
"News/Event/Entity extraction" in the future RTX 3090 AI layer, while the
tracker sells the TX2 path as a quick win with measured headroom (findings §1.4:
CPU 1–3%, ~4–5 GB RAM outside the FinBERT window).

## Decision
1. **v1 ships gazetteer-only extraction, no ML model.** The gazetteer is
   `ticker_names` (1,044 rows, covers both stock universes + indices + FX):
   every entity row is an INSTRUMENT-linked match, so downstream joins to
   prices/scores/sentiment are exact, not fuzzy.
2. **Match rules are code, auditable and measured**: legal-suffix-stripped full
   names; unambiguous first-token and two-token short-form variants; curated
   aliases (google→GOOG, facebook→META); a common-word stoplist tuned from the
   first canary's measured false positives ("Stock Market LIVE" headlines →
   Live Nation ×25, broker "target price" notes → Target Corp ×4; single-token
   stoplisted names like "Target" drop their full-name variant too — v3).
3. **Events v1 = a 16-type keyword taxonomy** (results, rating_action, ma,
   order_win, regulatory, rate_decision, …) — the taxonomy lives in
   `headline_ner.py`, not the schema; event rows link the single company
   mentioned when exactly one appears.
4. **The TX2 runs it** (00:45 PDT, after the FinBERT window): the job is
   regex+psycopg only — a 185 MB image, seconds of CPU, zero model-drift risk.
   Model-based NER (spaCy ORG/PERSON, LLM extraction) stays on the 3090-layer
   roadmap and can WRITE INTO THE SAME TABLES later with `source`-style
   provenance if needed.

## Consequences
- Extraction is reproducible and testable (10-case logic test + canary DB
  verification); the tables (`headline_entities`, `headline_events`) are plain,
  derived, and rebuilt by full rescan each run — no cursor, no drift.
- Recall is bounded by the gazetteer: companies outside both universes and
  non-instrument entities (persons, RBI, sectors) are NOT captured in v1 —
  a deliberate scope line; the events taxonomy partially covers macro actors
  (rate_decision).
- False-positive pressure concentrates in common-word name collisions; the
  stoplist is the tuning surface and is measured before extended (v1→v2→v3
  took 380→323 entity rows, TGT/LYV/O zeroed).
- Per-company sentiment (findings #10) can be built now: entities join
  `news_sentiment` on headline_id.
