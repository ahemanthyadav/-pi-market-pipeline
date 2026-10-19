-- Merge a hypertable's weekly chunks into one chunk per calendar year (TimescaleDB >= 2.18,
-- merge_chunks is a PROCEDURE). Applied 2026-10-18 to stock_prices (1962-2025: 3,382 -> 107
-- chunks) and index_prices (2021-2025: 300 -> 84). Rows unchanged, 0 duplicates, verified.
-- Takes a verified pg-backup first. Never run it on the current year while writers are live.
-- Usage (one year per call, inside the DB pod):
--   psql -v ON_ERROR_STOP=1 -v tbl=stock_prices -v yr=1999 -f 2026-10-18-merge-weekly-chunks.sql
SELECT coalesce(array_agg(format('%I.%I', chunk_schema, chunk_name) ORDER BY range_start)::text, '{}') AS arr,
       count(*) AS n
  FROM timescaledb_information.chunks
 WHERE hypertable_name = :'tbl' AND extract(year FROM range_start) = :yr \gset
SELECT (:n >= 2) AS go \gset
\if :go
CALL merge_chunks(:'arr'::regclass[]);
\echo merged :tbl :yr :n
\endif
