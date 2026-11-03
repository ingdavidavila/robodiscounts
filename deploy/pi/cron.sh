#!/usr/bin/env bash
# Install (or remove) the cron job that runs the price check.
#   ./deploy/pi/cron.sh --every 20     check every 20 minutes (5, 10, 15, 20, 30 or 60)
#   ./deploy/pi/cron.sh --remove       remove the job
#   ./deploy/pi/cron.sh --show         print the current job
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TAG="# robodiscounts-run"

current() { crontab -l 2>/dev/null || true; }
others()  { current | grep -vF "$TAG" || true; }

case "${1:-}" in
  --show)
    current | grep -F "$TAG" || echo "No robodiscounts cron job installed."
    ;;
  --remove)
    others | crontab -
    echo "Removed the robodiscounts cron job."
    ;;
  --every)
    n="${2:-}"
    case "$n" in
      5|10|15|20|30) spec="*/$n * * * *" ;;
      60)            spec="0 * * * *" ;;
      *) echo "Use --every 5, 10, 15, 20, 30 or 60 (minutes)." >&2; exit 1 ;;
    esac
    chmod +x "$ROOT/deploy/pi/run-check.sh"
    { others; echo "$spec $ROOT/deploy/pi/run-check.sh $TAG"; } | crontab -
    echo "Installed: $spec"
    echo "Logs: $ROOT/logs/check.log    Dashboard: $ROOT/site/index.html"
    ;;
  *)
    echo "Usage: $0 --every N | --remove | --show" >&2
    exit 1
    ;;
esac
