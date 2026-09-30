#!/bin/sh
set -eu
smartlib_repo_dir="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
# No probe rows are inserted into the business database.
exec python3 "$smartlib_repo_dir/infra/backup/verify-readonly-restore.py"
