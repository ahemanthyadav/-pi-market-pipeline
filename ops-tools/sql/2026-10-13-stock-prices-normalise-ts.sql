-- DQ-4 repair: make every stock_prices row "midnight UTC on the trade date".
--
-- Why: history was written with exchange-local midnight (US 04:00/05:00 UTC, NSE 18:30 UTC of the
-- PREVIOUS calendar day); rows written since ~2026-09-28 are 00:00 UTC on the trade date. The two
-- conventions overlapped for 5 days (4,434 duplicate symbol-days) and every old NSE row's ts::date
-- is one day early. Rule used for the rewrite: new_ts = date_trunc('day', ts + interval '6 hours')
--   US 04:00 / 05:00 -> same day 10:00 / 11:00 -> that day        (correct)
--   NSE 18:30        -> next day 00:30            -> next day      (correct: IST midnight = trade date)
--   00:00            -> untouched
--
-- Usage (psql, autocommit — the DO blocks commit per symbol, so do NOT wrap in BEGIN):
--   psql -v ON_ERROR_STOP=1 -f 2026-10-13-stock-prices-normalise-ts.sql
-- Idempotent: step 2 only touches rows that are not already at midnight, so a re-run after an
-- interruption simply continues. Every symbol is verified (rows inserted == rows deleted) inside its own
-- transaction; a mismatch RAISES and rolls that symbol back.
--
-- Rollback: restore from the pg_dump taken before the run (ops manual §9) — there is no inverse
-- UPDATE (the old local-midnight stamps are derivable but the duplicates deleted in step 1 are not).
SET timezone = 'UTC';

-- Step 1: delete the old-convention twin of a trade day that already has a 00:00 row (4,434 rows expected).
DO $$
DECLARE n bigint;
BEGIN
  DELETE FROM stock_prices o
   WHERE o.ts >= '2026-09-27' AND o.ts <> date_trunc('day', o.ts)
     AND EXISTS (SELECT 1 FROM stock_prices x
                  WHERE x.symbol = o.symbol AND x.ts >= '2026-09-27' AND x.ts = date_trunc('day', x.ts)
                    AND x.ts = date_trunc('day', o.ts + interval '6 hours'));
  GET DIAGNOSTICS n = ROW_COUNT;
  RAISE NOTICE 'step 1: deleted % duplicate old-convention rows', n;
  IF n > 6000 THEN
    RAISE EXCEPTION 'step 1 deleted % rows, more than the expected ~4,434 — rolled back', n;
  END IF;
END $$;

-- Step 2: per symbol, rewrite the remaining old-convention rows to midnight UTC of the trade date.
DO $$
DECLARE s text; a bigint; b bigint; tot bigint := 0; k int := 0;
BEGIN
  FOR s IN SELECT DISTINCT symbol FROM stock_prices WHERE ts <> date_trunc('day', ts) ORDER BY 1 LOOP
    INSERT INTO stock_prices (symbol, ts, open, high, low, close, volume)
      SELECT symbol, date_trunc('day', ts + interval '6 hours'), open, high, low, close, volume
        FROM stock_prices WHERE symbol = s AND ts <> date_trunc('day', ts)
      ON CONFLICT (symbol, ts) DO NOTHING;
    GET DIAGNOSTICS a = ROW_COUNT;
    DELETE FROM stock_prices WHERE symbol = s AND ts <> date_trunc('day', ts);
    GET DIAGNOSTICS b = ROW_COUNT;
    IF a <> b THEN
      RAISE EXCEPTION 'symbol %: inserted % but deleted % — rolled back, investigate', s, a, b;
    END IF;
    tot := tot + a; k := k + 1;
    COMMIT;
    IF k % 100 = 0 THEN RAISE NOTICE 'step 2: % symbols, % rows so far', k, tot; END IF;
  END LOOP;
  RAISE NOTICE 'step 2 done: % symbols, % rows rewritten', k, tot;
END $$;
