#!/usr/bin/env sh
# Restore a backup made by backup.sh into the compose stack (P6-11).
#
#   infra/backup/restore.sh BACKUP_DIR [TARGET_DB]
#
# TARGET_DB defaults to civicpulse_restore, a new database next to the
# live one: the drill restores there and compares, so it never touches
# production data. Restoring over the live database is a deliberate
# second step (see docs/runbooks/backup-restore.md).
# With RESTORE_MEDIA=1 the media files are mirrored back into the bucket
# (missing objects are added; nothing is deleted).
set -eu

COMPOSE_FILE=${COMPOSE_FILE:-infra/docker-compose.yml}
src=${1:?usage: restore.sh BACKUP_DIR [TARGET_DB]}
target=${2:-civicpulse_restore}
POSTGRES_USER=${POSTGRES_USER:-civicpulse}
APP_DB_USER=${APP_DB_USER:-civicpulse_app}
S3_BUCKET=${S3_BUCKET:-civicpulse-media}
compose() { docker compose -f "$COMPOSE_FILE" "$@"; }

case "$target" in *[!a-z0-9_]*) echo "bad database name: $target" >&2; exit 2;; esac

echo "verifying checksums"
( cd "$src" && sha256sum --quiet -c SHA256SUMS )

echo "database -> $target"
compose exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres \
  -c "DROP DATABASE IF EXISTS \"$target\" WITH (FORCE)" \
  -c "CREATE DATABASE \"$target\" OWNER \"$POSTGRES_USER\""
compose exec -T db pg_restore -U "$POSTGRES_USER" -d "$target" \
  --no-owner --exit-on-error < "$src/civicpulse.dump"
compose exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$target" \
  -c "GRANT CONNECT ON DATABASE \"$target\" TO \"$APP_DB_USER\""

if [ "${RESTORE_MEDIA:-0}" = "1" ]; then
  echo "media -> bucket $S3_BUCKET"
  compose run --rm --no-deps -T -v "$(cd "$src/media" && pwd):/backup:ro" \
    --entrypoint /bin/sh minio-init -c \
    'mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null &&
     mc mirror --quiet "/backup" "local/$S3_BUCKET"'
fi
echo "restore complete into $target"
