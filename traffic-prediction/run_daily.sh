#!/usr/bin/env bash
# Daily driver for the predictive sweep, meant to be run from cron.
# Loads the API key from .env (next to this script), runs the sweep, and
# appends a timestamped line to run_daily.log so cron failures are visible.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Load TOMTOM_API_KEY (and optionally PYTHON=) without echoing it.
if [[ -f "$DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$DIR/.env"
  set +a
fi

PYTHON="${PYTHON:-python3}"
LOG="$DIR/run_daily.log"

{
  echo "=== $(date -Is) ==="
  "$PYTHON" "$DIR/log_commute.py"
} >>"$LOG" 2>&1
