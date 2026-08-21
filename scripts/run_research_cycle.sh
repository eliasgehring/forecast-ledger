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
echo "[1/6] Enrollment"

python -m forecast_ledger.enrollment \
  --execute

echo
echo "[2/6] Scheduler"

python -m forecast_ledger.scheduler \
  --execute

echo
echo "[3/6] Non-interactive semantic review gate"

set +e

REVIEW_OUTPUT="$(
  python - <<'PY'
import sqlite3
from pathlib import Path

from forecast_ledger.review import (
    load_review_candidates,
)

db_path = Path(
    "data/forecast_ledger.db"
).resolve()

connection = sqlite3.connect(
    f"file:{db_path}?mode=ro",
    uri=True,
)

try:
    candidates = (
        load_review_candidates(
            connection
        )
    )
finally:
    connection.close()

if not candidates:
    print(
        "Semantic review queue is empty."
    )
    raise SystemExit(0)

print(
    "Semantic review required:",
    len(candidates),
    "checkpoint(s)",
)

for candidate in candidates:
    print(
        candidate.market_id,
        candidate.checkpoint.value,
        "|",
        candidate.question,
    )

raise SystemExit(2)
PY
)"

REVIEW_STATUS=$?

set -e

echo "$REVIEW_OUTPUT"

if [ "$REVIEW_STATUS" -eq 2 ]; then
  echo
  echo "========================================"
  echo "HUMAN REVIEW REQUIRED"
  echo "========================================"
  echo
  echo "No retrieval or forecasting was started."
  echo
  echo "Run:"
  echo "python -m forecast_ledger.review"
  echo
  echo "Then rerun:"
  echo "./scripts/run_research_cycle.sh"
  exit 2
fi

if [ "$REVIEW_STATUS" -ne 0 ]; then
  echo
  echo "ERROR: semantic review gate failed."
  exit "$REVIEW_STATUS"
fi

echo
echo "[4/6] OpenAI preflight"

if [ -z "${OPENAI_API_KEY:-}" ]; then
  KEY="$(
    security find-generic-password \
      -s forecast-ledger-openai \
      -a "${USER:-$(id -un)}" \
      -w \
      2>/dev/null \
      || true
  )"

  if [ -z "$KEY" ]; then
    echo
    echo "ERROR: OpenAI API key unavailable."
    exit 11
  fi

  export OPENAI_API_KEY="$KEY"
fi

python - <<'PY'
from openai import OpenAI

OpenAI().models.list()

print(
    "OpenAI preflight: OK"
)
PY

echo
echo "[5/6] Forecast pipeline"

python -m forecast_ledger.pipeline \
  --execute

PIPELINE_STATUS=$?

if [ "$PIPELINE_STATUS" -ne 0 ]; then
  echo
  echo "ERROR: forecast pipeline failed."
  exit "$PIPELINE_STATUS"
fi

echo
echo "[6/6] Resolution sweep"

python -m forecast_ledger.resolution \
  --execute

echo
echo "========================================"
echo "OPERATIONS STATUS"
echo "========================================"

python -m forecast_ledger.ops

echo
echo "========================================"
echo "CYCLE COMPLETE"
echo "========================================"
