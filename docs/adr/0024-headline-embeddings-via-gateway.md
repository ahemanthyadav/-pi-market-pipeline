# 0024. Headline embeddings via the shared gateway — exact match, one model, never a scoring input

- Date: 2026-10-19
- Status: accepted

## Context
ML-2 (news embeddings + story clustering) needs vector search over headlines for two uses: semantic news
lookup for the bot's `/ask` (planned) and grouping near-duplicate headlines into stories. The cluster DB is
TimescaleDB; pgvector 0.8.1 is available. The shared llm-gateway (ADR 0022) already exposes an `embed`
capability (2048-dim, NVIDIA free tier). Options: local embedding model on the TX2 (GPU otherwise idle),
a hosted embedding API directly, or the gateway.

## Decision
1. **Through the gateway only** (`embed` capability), like every other LLM use. No provider name or key in
   marketdata; the gateway's failover chains stay in one place.
2. **Fallbacks disabled per request** (`disable_fallbacks`). Vectors from two different embedding models are
   not comparable, so a silent switch to `embed.2` would poison every similarity result. Instead the exact
   model that answered (from the response header) is stored with every vector in `headline_embeddings.model`,
   and comparisons are always same-model (`p.model = e.model` in the SQL). If the primary dies, new rows get
   the new model and simply never compare against old-model rows (search falls back to LIKE).
3. **pgvector exact search, no ANN index** (~90 headlines/day, a few thousand rows total — a scan is
   microseconds; HNSW caps at 2000 dims and our vectors are 2048).
4. **Story grouping**: a headline joins the story of its most similar earlier headline from the last 72 h if
   cosine similarity ≥ 0.86, else starts its own story (`story_id` = own `headline_id`). Threshold is a
   starting point — tuning is a pending task; first live day grouped nothing (65 headlines → 65 stories), so
   it will likely come down.
   **Amended 2026-10-20: `STORY_SIM=0.82`** (env on the `news-embed` CronJob; script default stays 0.86).
   Basis: nearest-neighbour distance distribution over the first 1,651 vectors (0.86 ≈ distance ≤ 0.14
   caught only the 53-vector near-duplicate spike → 49 merges) plus a manual review of nearest pairs:
   the 0.10–0.16 distance band is consistently the same story reworded (IDBI Q2, Bandhan +8 %, Tech
   Mahindra Q2, SEBI extension), while 0.20+ was not reviewed. Known accepted cost: daily recurring
   templates ("outlook today", gold-rate columns) dated ≤ 3 days apart can merge. Existing story_ids are
   not regrouped (only NULL rows are assigned). Re-tune only with a fresh pair review at the new threshold.
5. **Never a scoring input** (ADR 0018 stands): embeddings serve lookup/grouping only. Only public headline
   text leaves the cluster; no chat ids, no watchlists.
6. Runs 01:00 UTC (`news-embed` CronJob), after news 23:45 / sentiment 00:15 / NER 00:45; idempotent
   (DELETE+INSERT per headline); gateway down → exit 0, rows stay un-embedded, retried next day.

## Consequences
- `/ask` news queries and duplicate grouping have their data foundation; story-level news digests become
  possible (ML-2 next steps).
- A provider model switch makes old and new vectors incomparable — accepted (news search mostly touches
  recent headlines; re-embedding a day is ~2 min).
- Schema 13 (`13-news-embeddings.sql`): `headline_embeddings` (headline_id PK, ts, model, vector(2048),
   story_id). Plain table, telegram_app gets SELECT via default privileges.
