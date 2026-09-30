#!/usr/bin/env bash
# Nightly data refresh (Linux/macOS). Imports any new device exports dropped in DROP_DIR,
# re-processes the affected days, and rewrites the Power BI CSV files.
# Files already imported are recognised by their SHA-256 and skipped, so the whole folder
# can be passed every night.
set -euo pipefail
cd "$(dirname "$0")/.."
DROP_DIR="${DROP_DIR:-/srv/timeclock/exports}"
source .venv/bin/activate
mkdir -p output/logs
python -m hr_analytics import-punches "$DROP_DIR" >> output/logs/nightly.log 2>&1
python -m hr_analytics export-powerbi >> output/logs/nightly.log 2>&1
