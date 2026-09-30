#!/bin/sh
set -eu

smartlib_repo_dir="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
smartlib_compose_file="$smartlib_repo_dir/infra/compose/compose.yaml"
smartlib_env_file="${SMARTLIB_COMPOSE_ENV_FILE:-$smartlib_repo_dir/infra/compose/.env.local}"
smartlib_backup_dir="${SMARTLIB_BACKUP_DIR:-$smartlib_repo_dir/backups}"
smartlib_timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
smartlib_backup_file="$smartlib_backup_dir/smartlib-$smartlib_timestamp.dump"

mkdir -p "$smartlib_backup_dir"
umask 077

docker compose --env-file "$smartlib_env_file" -f "$smartlib_compose_file" \
    exec -T postgres pg_dump \
    --format=custom \
    --compress=6 \
    --no-password \
    --username "${SMARTLIB_DB_BOOTSTRAP_USER:-smartlib_bootstrap}" \
    --dbname "${SMARTLIB_DB_NAME:-smartlib}" > "$smartlib_backup_file"

shasum -a 256 "$smartlib_backup_file"
printf '%s\n' "$smartlib_backup_file"
