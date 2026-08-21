#!/bin/zsh

set -euo pipefail

cd "$(dirname "$0")/.."

if [ -d ".venv" ]; then
  source .venv/bin/activate
fi

echo
echo "========================================"
echo "FORECAST LEDGER RESEARCH CYCLE"
echo "========================================"

echo
echo "[1/6] Enrollment"
python -m forecast_ledger.enrollment \
  --execute

echo
echo "[2/6] Scheduler"
python -m forecast_ledger.scheduler \
  --execute

echo
echo "[3/6] Semantic review check"
REVIEW_OUTPUT="$(
  python -m forecast_ledger.review
)"

echo "$REVIEW_OUTPUT"

if ! echo "$REVIEW_OUTPUT" \
  | grep -q \
  "Semantic review queue is empty."
then
  echo
  echo "========================================"
  echo "HUMAN REVIEW REQUIRED"
  echo "========================================"
  echo
  echo "Cycle stopped before retrieval/forecasting."
  echo "Complete semantic review, then rerun this script."
  exit 2
fi

echo
echo "[4/6] Forecast pipeline"
python -m forecast_ledger.pipeline \
  --execute

echo
echo "[5/6] Resolution sweep"
python -m forecast_ledger.resolution \
  --execute

echo
echo "[6/6] Operations status"
python -m forecast_ledger.ops

echo
echo "========================================"
echo "CYCLE COMPLETE"
echo "========================================"
