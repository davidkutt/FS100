# Runbook: Postgres backup and restore

Owner: platform team · Applies to: the `app` and `keycloak` databases · Last reviewed: 2026-10

## Backup policy

- A logical backup of each database runs every night at 02:00 UTC with `pg_dump` in custom format.
- Backups are kept for **14 days**; the backup of the first day of each month is kept for a year.
- Backups are encrypted at rest and stored outside the cluster that runs the database.
- In the cloud (Phase 5) the managed service adds point-in-time recovery from WAL archives with a
  7-day window.

## Take a manual backup

Always take one before a risky migration or a manual data fix:

```bash
pg_dump --format=custom --no-owner --dbname="$API_DATABASE_URL" --file="app-$(date +%F-%H%M).dump"
pg_restore --list "app-2026-10-14-0930.dump" | head   # sanity check: the archive is readable
```

## Restore into a scratch database

Never restore over the live database first. Restore into a new database, verify, then switch.

```bash
createdb --host=localhost --username=postgres app_restore
pg_restore --no-owner --dbname=postgresql://postgres@localhost:5432/app_restore app-2026-10-14-0930.dump
```

## Verify the restore

1. Compare row counts of the important tables (`documents`) with the source or with the last known count.
2. Check the newest `created_at` to see how much data the backup misses.
3. Run the API against the scratch database (`API_DATABASE_URL`) and open the documents page.

## Switch over

Stop the API, rename the databases (`app` → `app_broken`, `app_restore` → `app`), start the API. Keep
`app_broken` for a week for forensics, then drop it. Documents whose vectors exist in Qdrant but whose
row is missing must be re-ingested or deleted from Qdrant.

## Restore drill

Once a month, restore last night's backup into a scratch database and run the verification steps. An
untested backup is not a backup. Record the drill duration — it is the realistic restore time objective.
