#!/bin/bash
# Creates the read-only login role at cluster init. Table-level grants are
# applied later by migration 0002 (they require the tables to exist first).
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
	CREATE ROLE "${READONLY_USER}" LOGIN PASSWORD '${READONLY_PASSWORD}';
EOSQL
