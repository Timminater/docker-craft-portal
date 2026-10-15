#!/usr/bin/env bash
set -euo pipefail
python -m pip install -r requirements-dev.txt
mkdir -p /tmp/craft-portal-codex
printf 'CRAFT_DATA_DIR=/tmp/craft-portal-codex\nCRAFT_PUBLIC_URL=http://localhost:8080\nCRAFT_AUTO_START_UPDATES=false\n' > .env.codex
python -m pytest -q
