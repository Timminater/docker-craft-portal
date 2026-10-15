#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
craft_venv_dir="${CRAFT_VENV_DIR:-$PWD/.venv}"
python3 -m venv "$craft_venv_dir"
"$craft_venv_dir/bin/python" -m pip install -r requirements-dev.txt
"$craft_venv_dir/bin/python" -m compileall -q portal scripts
"$craft_venv_dir/bin/python" -m pytest -q
node --check portal/static/app.js
node --check portal/static/bridge.js
node --check portal/static/storage.js
node --check portal/static/i18n.js
