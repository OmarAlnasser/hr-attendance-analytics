#!/usr/bin/env bash
# Monthly PDF reports for the previous calendar month (organisation + every department).
# Safe to run more than once: a scope/period that already has a successful report is skipped,
# and a run in progress blocks a second one. Exit code 1 if any report failed.
# Reports are written to HR_REPORTS_DIR; nothing is emailed.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
mkdir -p output/logs
python -m hr_analytics run-monthly --all-departments >> output/logs/monthly.log 2>&1
