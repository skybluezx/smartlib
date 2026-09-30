#!/bin/sh
set -eu

smartlib_repo_dir="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
smartlib_compose_file="$smartlib_repo_dir/infra/compose/compose.yaml"
smartlib_env_file="${SMARTLIB_COMPOSE_ENV_FILE:-$smartlib_repo_dir/infra/compose/.env.local}"

docker compose --env-file "$smartlib_env_file" -f "$smartlib_compose_file" \
    exec -T postgres psql \
    -v ON_ERROR_STOP=1 \
    -U "${SMARTLIB_DB_BOOTSTRAP_USER:-smartlib_bootstrap}" \
    -d "${SMARTLIB_DB_NAME:-smartlib}" \
    -f - < "$smartlib_repo_dir/database/tests/verify_database.sql"
