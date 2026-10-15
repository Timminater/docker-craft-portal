#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
craft_venv_dir="${CRAFT_VENV_DIR:-$PWD/.venv}"
export CRAFT_DATA_DIR="${CRAFT_DATA_DIR:-$PWD/data}"
export CRAFT_PUBLIC_URL="${CRAFT_PUBLIC_URL:-http://localhost:8080}"
export CRAFT_AUTO_START_UPDATES="${CRAFT_AUTO_START_UPDATES:-false}"
exec "$craft_venv_dir/bin/uvicorn" portal.main:app --host 127.0.0.1 --port "${CRAFT_PORT:-8080}" --no-access-log --no-proxy-headers
