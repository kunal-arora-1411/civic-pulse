#!/usr/bin/env bash
# Creates the role the API connects as.
#
# The owner role (POSTGRES_USER) owns the schema and runs migrations. The API
# uses this separate role, which is deliberately NOT a superuser and does NOT
# have BYPASSRLS, so row-level security policies actually apply to it.
# Migrations grant it DML on the tables it needs.
#
# The postgres entrypoint may source this file rather than execute it, so it
# avoids `exit` and keeps its variables local to a function.

create_app_role() {
    local app_user="${APP_DB_USER:-civicpulse_app}"
    local app_password="${APP_DB_PASSWORD:-}"

    if [ -z "$app_password" ]; then
        echo "20-app-role.sh: APP_DB_PASSWORD must be set" >&2
        return 1
    fi

    psql -v ON_ERROR_STOP=1 \
        --username "$POSTGRES_USER" \
        --dbname "$POSTGRES_DB" \
        --set app_user="$app_user" \
        --set app_password="$app_password" \
        --set db_name="$POSTGRES_DB" <<'SQL'
SELECT format(
    'CREATE ROLE %I LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD %L',
    :'app_user', :'app_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user')
\gexec

SELECT format('GRANT CONNECT ON DATABASE %I TO %I', :'db_name', :'app_user')
\gexec
SELECT format('GRANT USAGE ON SCHEMA public TO %I', :'app_user')
\gexec

-- A request that leaves a transaction open would otherwise hold its locks
-- (and its tenant setting) indefinitely.
SELECT format('ALTER ROLE %I SET idle_in_transaction_session_timeout = %L', :'app_user', '60s')
\gexec
SQL
}

create_app_role
