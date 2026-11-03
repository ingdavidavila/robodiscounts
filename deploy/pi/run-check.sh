#!/usr/bin/env bash
# What cron runs: one price check, then rebuild the dashboard (site/index.html).
# Safe to run by hand. A lock stops two runs from overlapping.
set -u

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT" || exit 1
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
mkdir -p logs

exec 9>logs/.lock
if ! flock -n 9; then
  echo "$(date -u +%FT%TZ) previous run still going, skipping" >> logs/check.log
  exit 0
fi

# Keep the log from growing forever: one rotated copy, ~2 MB each.
if [ -f logs/check.log ] && [ "$(stat -c %s logs/check.log)" -gt 2000000 ]; then
  mv -f logs/check.log logs/check.log.1
fi

# Small random delay so requests don't land on the exact same second every time.
if [ -z "${NO_JITTER:-}" ]; then sleep $((RANDOM % 45)); fi

export ROBODISCOUNTS_DEBUG_DIR="$ROOT/debug"   # saves the page when a price can't be read

echo "$(date -u +%FT%TZ) ---- check start" >> logs/check.log
"$PYTHON" -m robodiscounts.cli check >> logs/check.log 2>&1
status=$?
"$PYTHON" -m robodiscounts.cli dashboard >> logs/check.log 2>&1
echo "$(date -u +%FT%TZ) ---- check end (exit $status)" >> logs/check.log
exit $status
