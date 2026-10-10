---
name: Database Migration
description: Use when changing the TimescaleDB schema or data — backup first, additive-first changes, the schema ConfigMap workflow, batched backfills, verification by row counts, and a written rollback.
---

# DB migrations (TimescaleDB, schema managed via ConfigMap)

## Non-negotiables
- **Backup first.** Confirm today's dump exists (§9) or trigger one:
  `kubectl create job -n market-data pgbackup-manual --from=cronjob/pg-backup`.
- **Additive-first.** Adding columns/tables/indexes is safe. Changing or
  dropping existing things needs a staged plan: add new → backfill → switch
  readers → retire old. Never DROP data in the same change that ships its
  replacement.
- **Schema changes go through the ConfigMap**: edit
  `manifests/timescaledb/schema-configmap.yaml`, apply, re-run the schema-job.
  Ad-hoc `kubectl exec psql` DDL drifts from the manifest and bites the next
  restore drill.
- **Hypertables:** new time tables need `create_hypertable` or they silently
  stay plain (and slow). New unique constraints require ON CONFLICT handling
  in the writer in the same release (known gap: news tables, manual §12).

## Workflow
1. Write the DDL exactly as it will appear in the ConfigMap — idempotent
   (`IF NOT EXISTS`).
2. State the backfill: rows affected, expected duration, DB pod memory (TX2,
   2 Gi limit — backfill in batches, never one giant UPDATE).
3. Dry-run destructive parts as SELECTs first: count what the DELETE would hit.
4. Apply via the schema-job; verify with `\d` shape, row counts before/after,
   and a spot-check query from manual §5.
5. Re-run the restore drill after any schema change (§9) — a backup that can't
   restore is a rumor.
6. Update manual §3/§5 references and note the schema bump.

## Rollback
Every migration ships with its reverse written down (even if the reverse of
an ADD COLUMN is just "leave it empty and stop using it"). Data-destroying
rollbacks need explicit user approval — the Retain PV exists for filesystem
accidents, not for careless SQL.
