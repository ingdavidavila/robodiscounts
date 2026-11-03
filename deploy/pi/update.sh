#!/usr/bin/env bash
# Pull the latest code and refresh dependencies. Your config.yaml, .env and price history are untouched.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
git pull --ff-only origin main
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
echo "Updated."
