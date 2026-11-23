# PostgreSQL 16 with PostGIS 3.5, pgvector and h3-pg.
#
# postgis/postgis:16-3.5 is built on Debian bullseye. PGDG has retired
# bullseye from apt.postgresql.org and moved it to apt-archive, so the stock
# pgdg.list in the base image no longer resolves. We point apt at the archive
# (signed with the same key) before installing the extra extensions.
FROM postgis/postgis:16-3.5

RUN set -eux; \
    . /etc/os-release; \
    echo "deb [ signed-by=/usr/local/share/keyrings/postgres.gpg.asc ] https://apt-archive.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg-archive main" \
        > /etc/apt/sources.list.d/pgdg.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        postgresql-16-pgvector \
        postgresql-16-h3; \
    rm -rf /var/lib/apt/lists/*

# Role bootstrap (creates the non-superuser application role).
COPY init/ /docker-entrypoint-initdb.d/
