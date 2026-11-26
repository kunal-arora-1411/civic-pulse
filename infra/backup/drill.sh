#!/usr/bin/env sh
# The restore drill (P6-11): back up, restore into a scratch database, and
# check the copy matches the live one table by table. Prints the time each
# step took, which is the measured RTO for docs/runbooks/backup-restore.md.
set -eu

COMPOSE_FILE=${COMPOSE_FILE:-infra/docker-compose.yml}
POSTGRES_DB=${POSTGRES_DB:-civicpulse}
POSTGRES_USER=${POSTGRES_USER:-civicpulse}
dir=$(mktemp -d)
compose() { docker compose -f "$COMPOSE_FILE" "$@"; }
counts() {
  compose exec -T db psql -U "$POSTGRES_USER" -d "$1" -At -c "
    SELECT string_agg(format('%s=%s', relname, n), ' ' ORDER BY relname) FROM (
      SELECT c.relname, (xpath('/row/n/text()', query_to_xml(
        format('SELECT count(*) AS n FROM %I.%I', n.nspname, c.relname), false, true, '')))[1]::text AS n
      FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
      WHERE c.relkind = 'r' AND n.nspname = 'public') t"
}

t0=$(date +%s)
"$(dirname "$0")/backup.sh" "$dir"
t1=$(date +%s)
backup=$(find "$dir" -mindepth 1 -maxdepth 1 -type d | head -1)
before=$(counts "$POSTGRES_DB")
"$(dirname "$0")/restore.sh" "$backup" civicpulse_drill
t2=$(date +%s)
after=$(counts civicpulse_drill)

compose exec -T db psql -U "$POSTGRES_USER" -d postgres \
  -c 'DROP DATABASE IF EXISTS civicpulse_drill WITH (FORCE)' >/dev/null
rm -rf "$dir"

echo "backup took $((t1 - t0))s, restore took $((t2 - t1))s"
if [ "$before" = "$after" ]; then
  echo "DRILL PASSED: every table has the same row count"
else
  echo "DRILL FAILED: row counts differ" >&2
  echo "live:     $before" >&2
  echo "restored: $after" >&2
  exit 1
fi
