#!/usr/bin/env bash
# Wrapper script for the Linux cron job that refreshes the "Hiring now" overlay.
# Activates the project venv (if present) and runs the refresh.
#
# Install via:
#   crontab -e
# and add a line like:
#   0 6 * * * /path/to/SB-CTE-Dashboard/scripts/refresh-postings.sh
#
# Output is appended to scripts/refresh.log alongside this script.

set -euo pipefail

# Resolve project root from the script's own directory.
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
LOG_FILE="$SCRIPT_DIR/refresh.log"

cd "$PROJECT_ROOT"

# Activate venv if it exists; otherwise rely on system python.
if [ -f "venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source venv/bin/activate
elif [ -f ".venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

{
    echo "----- $(date -u '+%Y-%m-%d %H:%M:%S') UTC -----"
    python services/refresh_postings.py
    echo ""
} >> "$LOG_FILE" 2>&1
