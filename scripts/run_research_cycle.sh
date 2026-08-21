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
echo "[preflight] Git integrity"

if [ -n "$(git status --porcelain)" ]; then
  echo
  echo "ERROR: working tree is not clean."
  git status --short
  exit 10
fi

echo "git tree: clean"

echo
echo "[preflight] OpenAI credentials"

if [ -z "${OPENAI_API_KEY:-}" ]; then
  KEY="$(
    security find-generic-password       -s forecast-ledger-openai       -a "$USER"       -w       2>/dev/null       || true
  )"

  if [ -z "$KEY" ]; then
    echo
    echo "ERROR: OpenAI API key unavailable."
    exit 11
  fi

  export OPENAI_API_KEY="$KEY"
fi

python - <<'PY_INNER'
from openai import OpenAI

OpenAI().models.list()
print("OpenAI preflight: OK")
PY_INNER

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
