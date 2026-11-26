# Backups and restore (P6-11, PRD §13)

Two things hold state: the Postgres database and the media bucket. Redis
holds only rate-limit counters, the Celery broker and caches, and is not
backed up: losing it loses queued jobs. The outbox and the matching
watchdog re-drive those from the database.

## Targets

| | Target | How |
|---|---|---|
| **RPO** (data you can lose) | 1 hour | `backup.sh` hourly. With managed Postgres, point-in-time recovery brings it down to minutes; keep the hourly dumps as a second, provider-independent copy. |
| **RTO** (time to be back) | 4 hours | Restore the latest dump and mirror the media back. Re-measure with `drill.sh` (it prints how long each step took) and record the figure below. |
| Retention | 14 days of hourly backups on the machine (`BACKUP_KEEP_DAYS`); daily copies for 90 days in a bucket in another region. | |

These are proposals until the product owner and the city agree them.

## Taking a backup

```sh
infra/backup/backup.sh /var/backups/civicpulse
```

It writes a timestamped folder with `civicpulse.dump` (pg_dump custom
format), `media/` (a mirror of the bucket) and `SHA256SUMS`, and prunes
folders older than `BACKUP_KEEP_DAYS`. Schedule it hourly (cron or a
systemd timer) and copy each folder off the machine. Each folder gets a
full copy of the bucket, which is fine for a pilot. For a large bucket, use
the storage provider's replication and versioning instead and back up only
the database here.

The dump contains personal data (phone numbers, report locations). Store
backups encrypted, with access limited like the production database.
Anonymization (`POST /users/me/anonymize`) and the media retention job act
on the live data only: a backup taken before them still holds the old data
until it ages out, which is why backup retention is kept short.

## The restore drill (do this monthly, and after any infrastructure change)

```sh
infra/backup/drill.sh
```

It backs up, restores into a scratch database `civicpulse_drill`, compares
the row count of every table with the live database, drops the scratch
database and prints `DRILL PASSED` or `DRILL FAILED`. Run it on a quiet
stack: writes between the backup and the comparison show up as differences.
Record the result here:

| Date | Who | Backup | Restore | Result |
|---|---|---|---|---|
| | | | | |

## Restoring for real

1. Stop writers: `docker compose stop api worker ai-worker beat`.
2. Restore next to the live database and check it:
   `infra/backup/restore.sh /var/backups/civicpulse/<stamp> civicpulse_restore`.
3. Swap: rename the live database away and the restored one in
   (`ALTER DATABASE civicpulse RENAME TO civicpulse_broken; ALTER DATABASE
   civicpulse_restore RENAME TO civicpulse;`), as the owner role.
4. Media: `RESTORE_MEDIA=1 infra/backup/restore.sh <dir> civicpulse_restore`
   mirrors missing objects back (nothing is deleted).
5. Run migrations (`docker compose run --rm migrate`) in case the backup
   predates the deployed code, start the services, and check `/ready`.
6. Everyone signs in again if the restored sessions are older than their
   tokens; refresh tokens issued after the backup no longer exist.
