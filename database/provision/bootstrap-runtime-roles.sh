#!/bin/sh
set -eu

psql --set=ON_ERROR_STOP=1 \
  --host="${PGHOST:-postgres}" \
  --username="${PGUSER:-smartlib_bootstrap}" \
  --dbname="${PGDATABASE:-smartlib}" <<'SQL'
SELECT 'CREATE ROLE smartlib_api NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT NOBYPASSRLS'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'smartlib_api')
\gexec
SQL
