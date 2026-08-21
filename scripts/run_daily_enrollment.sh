#!/bin/zsh

set -euo pipefail

cd "$(dirname "$0")/.."

if [ -d ".venv" ]; then
  source .venv/bin/activate
fi

export PYTHONUNBUFFERED=1

echo
echo "========================================"
echo "FORECAST LEDGER DAILY ENROLLMENT"
echo "========================================"

if [ -n "$(git status --porcelain)" ]; then
  echo
  echo "ERROR: working tree is not clean."
  git status --short
  exit 10
fi

echo
echo "[1/2] Enrollment"

python -m forecast_ledger.enrollment \
  --execute

echo
echo "[2/2] Operations status"

python -m forecast_ledger.ops

echo
echo "========================================"
echo "DAILY ENROLLMENT COMPLETE"
echo "========================================"
