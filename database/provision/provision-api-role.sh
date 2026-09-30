#!/bin/sh
set -eu

: "${SMARTLIB_DB_API_PASSWORD:?Set SMARTLIB_DB_API_PASSWORD}"
: "${SMARTLIB_DB_PROJECTION_PASSWORD:?Set SMARTLIB_DB_PROJECTION_PASSWORD}"
: "${SMARTLIB_DEV_ACTOR_ID:=00000000-0000-4000-8000-000000000001}"

psql --set=ON_ERROR_STOP=1 \
  --host="${PGHOST:-postgres}" \
  --username="${PGUSER:-smartlib_bootstrap}" \
  --dbname="${PGDATABASE:-smartlib}" \
  --set=api_password="${SMARTLIB_DB_API_PASSWORD}" \
  --set=projection_password="${SMARTLIB_DB_PROJECTION_PASSWORD}" <<'SQL'
SELECT 'CREATE ROLE smartlib_api LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT NOBYPASSRLS'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'smartlib_api')
\gexec
ALTER ROLE smartlib_api WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT NOBYPASSRLS PASSWORD :'api_password';
GRANT smartlib_app TO smartlib_api;

SELECT 'CREATE ROLE smartlib_projection_worker LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT NOBYPASSRLS'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'smartlib_projection_worker')
\gexec
ALTER ROLE smartlib_projection_worker WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT NOBYPASSRLS PASSWORD :'projection_password';
GRANT smartlib_projection TO smartlib_projection_worker;
SQL

psql --set=ON_ERROR_STOP=1 \
  --host="${PGHOST:-postgres}" \
  --username="${PGUSER:-smartlib_bootstrap}" \
  --dbname="${PGDATABASE:-smartlib}" \
  --set=dev_actor_id="${SMARTLIB_DEV_ACTOR_ID}" <<'SQL'
INSERT INTO smartlib.actor_role_assignment (actor_id, role_id, assigned_by)
SELECT :'dev_actor_id'::uuid, role_id, :'dev_actor_id'::uuid
  FROM smartlib.access_role
 WHERE code = 'knowledge_admin'
ON CONFLICT (actor_id, role_id) DO NOTHING;
SQL
