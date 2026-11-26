#!/usr/bin/env sh
# Back up CivicPulse: the Postgres database and the media bucket (P6-11).
#
#   infra/backup/backup.sh [DEST_DIR]
#
# Writes DEST_DIR/<UTC timestamp>/ containing
#   civicpulse.dump   pg_dump custom format (all schemas, roles' grants)
#   media/            a mirror of the media bucket
#   SHA256SUMS        checksums, checked again by restore.sh
# and deletes backups older than BACKUP_KEEP_DAYS (default 14).
#
# Runs against the compose stack (docker compose exec). In production
# point COMPOSE_FILE at the deployment's file, run it from cron or a
# systemd timer every hour (the RPO in docs/runbooks/backup-restore.md),
# and copy DEST_DIR off the machine (another region's bucket).
set -eu

COMPOSE_FILE=${COMPOSE_FILE:-infra/docker-compose.yml}
DEST_ROOT=${1:-${BACKUP_DIR:-./backups}}
KEEP_DAYS=${BACKUP_KEEP_DAYS:-14}
POSTGRES_DB=${POSTGRES_DB:-civicpulse}
POSTGRES_USER=${POSTGRES_USER:-civicpulse}
S3_BUCKET=${S3_BUCKET:-civicpulse-media}

stamp=$(date -u +%Y%m%dT%H%M%SZ)
dest="$DEST_ROOT/$stamp"
mkdir -p "$dest/media"
compose() { docker compose -f "$COMPOSE_FILE" "$@"; }

echo "database -> $dest/civicpulse.dump"
compose exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  --format=custom --compress=6 --no-owner > "$dest/civicpulse.dump"

echo "media bucket -> $dest/media"
# minio-init's image has mc; mirror into a throwaway container, then copy out.
compose run --rm --no-deps -T -v "$(cd "$dest/media" && pwd):/backup" \
  --entrypoint /bin/sh minio-init -c \
  'mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null &&
   mc mirror --quiet --overwrite "local/$S3_BUCKET" /backup'

( cd "$dest" && find . -type f ! -name SHA256SUMS -exec sha256sum {} + > SHA256SUMS )
echo "backup complete: $dest ($(du -sh "$dest" | cut -f1))"

find "$DEST_ROOT" -mindepth 1 -maxdepth 1 -type d -mtime "+$KEEP_DAYS" \
  -exec rm -rf {} + 2>/dev/null || true
