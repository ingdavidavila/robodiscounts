#!/usr/bin/env bash
# One-time setup for a Raspberry Pi (or any Debian/Ubuntu box): Python env, packages, headless Chromium.
# Run as your normal user (not root). It will ask for your password once for apt.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

if [ "$(id -u)" -eq 0 ]; then
  echo "Run this as your normal user, not root (browsers and the cron job belong to that user)." >&2
  exit 1
fi

arch="$(uname -m)"
case "$arch" in
  aarch64|x86_64) ;;
  *)
    echo "Unsupported architecture: $arch" >&2
    echo "Chromium for the price checker needs a 64-bit OS. On a Pi, install 'Raspberry Pi OS (64-bit)'." >&2
    exit 1
    ;;
esac

echo "==> Installing system packages"
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip git util-linux

echo "==> Creating Python environment (.venv)"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo "==> Installing Chromium and its system libraries"
sudo "$ROOT/.venv/bin/playwright" install-deps chromium
.venv/bin/playwright install chromium

echo "==> Creating config files (only if missing)"
[ -f config.yaml ] || cp config.example.yaml config.yaml
[ -f .env ] || cp .env.example .env
chmod 600 .env
mkdir -p logs

cat <<MSG

Setup done. Next:
  1. Edit config.yaml  -> your products, URLs, MSRPs
  2. Edit .env         -> WhatsApp and Best Buy credentials
  3. Test:   ./deploy/pi/run-check.sh        (then look at logs/check.log and site/index.html)
  4. Start the schedule:   ./deploy/pi/cron.sh --every 20
MSG
