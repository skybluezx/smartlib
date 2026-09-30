#!/bin/sh
# Read-only local release checks. Historical fixtures absent from this checkout are reported as skipped.
set -eu
cd "$(dirname "$0")/../.."
apps/platform-api/.venv/bin/python apps/platform-api/scripts/export_openapi.py --check
apps/platform-api/.venv/bin/python -m pytest apps/platform-api/tests -q -rs
npm --prefix apps/web run check
