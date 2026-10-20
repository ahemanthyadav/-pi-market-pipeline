"""ML-2 groundwork — headline embeddings + story grouping via the shared llm-gateway (2026-10-19, ADR 0024).

Daily at 01:00 UTC (after news-fetcher 23:45, sentiment 00:15, NER 00:45). Embeds every raw_headlines row that
has no embedding yet (batches of BATCH, gateway capability `embed`, fallbacks DISABLED — vectors from two
different models cannot be compared, so the exact model name from the gateway is stored with each vector and
every comparison stays within one model). Then groups headlines into stories: a headline joins the story of
its most similar earlier headline from the previous STORY_HOURS if cosine similarity >= STORY_SIM, else it
starts its own story (story_id = its own headline_id).

Uses: /ask news search (semantic, bot), duplicate-story grouping. Never a scoring input (ADR 0018).
Only public headline text is sent. Exit 0 when the gateway is down (retried tomorrow — rows stay un-embedded).
Env: PG*, LLM_BASE_URL, LLM_API_KEY, BATCH (48), PAUSE (s between batches, 35 — gateway embed rpm is 2),
     MAX_BATCHES (60), STORY_SIM (0.86), STORY_HOURS (72).
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

import psycopg


def connect():
    conn = psycopg.connect(host=os.environ.get("PGHOST", "timescaledb.market-data.svc.cluster.local"),
                           user=os.environ.get("PGUSER", "postgres"), password=os.environ["PGPASSWORD"],
                           dbname=os.environ.get("PGDATABASE", "postgres"))
    conn.autocommit = True
    return conn


def embed(texts):
    """-> (model_name, [vectors]). Raises RuntimeError('unavailable: …') on any gateway problem."""
    body = {"model": "embed", "input": texts, "encoding_format": "float", "disable_fallbacks": True}
    req = urllib.request.Request(os.environ["LLM_BASE_URL"].rstrip("/") + "/embeddings",
                                 data=json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + os.environ["LLM_API_KEY"],
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            model = r.headers.get("x-litellm-model-name") or ""
            data = json.load(r)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        detail = exc.read().decode()[:200] if isinstance(exc, urllib.error.HTTPError) else str(exc)
        raise RuntimeError(f"unavailable: {detail}") from exc
    vecs = [d["embedding"] for d in sorted(data["data"], key=lambda d: d["index"])]
    if not model or len(vecs) != len(texts):
        raise RuntimeError("unavailable: no model name or wrong vector count")
    return model.split("/", 1)[-1] if "/" in model else model, vecs   # strip any provider prefix


def vec_literal(v):
    return "[" + ",".join(f"{x:.6g}" for x in v) + "]"


def embed_pending(conn, embedder=embed, batch=48, pause=35.0, max_batches=60):
    done = 0
    for i in range(max_batches):
        with conn.cursor() as cur:
            cur.execute("SELECT r.id, r.ts, r.headline FROM raw_headlines r "
                        "LEFT JOIN headline_embeddings e ON e.headline_id = r.id "
                        "WHERE e.headline_id IS NULL AND r.ts >= now() - interval '400 days' "
                        "ORDER BY r.ts LIMIT %s", (batch,))
            rows = cur.fetchall()
        if not rows:
            break
        if i:
            time.sleep(pause)
        model, vecs = embedder([h[:1000] for _id, _ts, h in rows])
        with conn.transaction():
            with conn.cursor() as cur:
                for (hid, ts, _h), v in zip(rows, vecs):
                    cur.execute("DELETE FROM headline_embeddings WHERE headline_id = %s", (hid,))
                    cur.execute("INSERT INTO headline_embeddings (headline_id, ts, model, embedding) "
                                "VALUES (%s, %s, %s, %s::vector)", (hid, ts, model, vec_literal(v)))
        done += len(rows)
        print(f"embedded {done} (model {model})", flush=True)
    return done


def group_stories(conn, sim=0.86, hours=72):
    """Assign story_id to headlines that have none, oldest first (so earlier stories exist)."""
    n = 0
    with conn.cursor() as cur:
        cur.execute("SELECT headline_id, ts, model FROM headline_embeddings WHERE story_id IS NULL "
                    "AND ts >= now() - interval '400 days' ORDER BY ts, headline_id")
        todo = cur.fetchall()
    for hid, ts, model in todo:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT p.story_id, 1 - (p.embedding <=> e.embedding) AS s "
                "FROM headline_embeddings e JOIN headline_embeddings p "
                "  ON p.model = e.model AND p.story_id IS NOT NULL AND p.headline_id <> e.headline_id "
                " AND p.ts <= e.ts AND p.ts >= e.ts - make_interval(hours => %s) "
                "WHERE e.headline_id = %s ORDER BY p.embedding <=> e.embedding LIMIT 1", (hours, hid))
            best = cur.fetchone()
            story = best[0] if best and best[1] >= sim else hid
            cur.execute("UPDATE headline_embeddings SET story_id = %s WHERE headline_id = %s", (story, hid))
        n += 1
    return n


def main() -> int:
    conn = connect()
    try:
        done = embed_pending(conn, batch=int(os.environ.get("BATCH", "48")),
                             pause=float(os.environ.get("PAUSE", "35")),
                             max_batches=int(os.environ.get("MAX_BATCHES", "60")))
    except RuntimeError as exc:
        print(f"EMBED-UNAVAILABLE {str(exc)[:200]}", flush=True)
        done = 0
    grouped = group_stories(conn, float(os.environ.get("STORY_SIM", "0.86")), int(os.environ.get("STORY_HOURS", "72")))
    with conn.cursor() as cur:
        cur.execute("SELECT count(*), count(DISTINCT story_id) FROM headline_embeddings "
                    "WHERE ts >= now() - interval '1 day'")
        last_day, stories = cur.fetchone()
    conn.close()
    print(f"NEWS-EMBED-OK embedded={done} grouped={grouped} last_24h={last_day} headlines in {stories} stories", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
