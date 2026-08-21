#!/bin/zsh

set -u

cd "$(dirname "$0")/.."

export PYTHONUNBUFFERED=1
export FORECAST_LEDGER_SKIP_ENROLLMENT=1

STATE_DIR="$HOME/Library/Application Support/ForecastLedger/ops"

mkdir -p "$STATE_DIR"

LAST_RUN_AT="$STATE_DIR/last_run_at_utc.txt"
LAST_STATUS="$STATE_DIR/last_run_status.txt"
LAST_SUCCESS="$STATE_DIR/last_success_at_utc.txt"
REVIEW_MARKER="$STATE_DIR/review_pending"
FAILURE_MARKER="$STATE_DIR/last_failure_status.txt"

NOW_UTC="$(
  /bin/date -u "+%Y-%m-%dT%H:%M:%SZ"
)"

print -r -- "$NOW_UTC" \
  > "$LAST_RUN_AT"


notify() {
  local message="$1"

  /usr/bin/osascript \
    -e "display notification \"$message\" with title \"Forecast Ledger\"" \
    >/dev/null \
    2>&1 \
    || true
}


./scripts/run_research_cycle.sh

STATUS=$?

print -r -- "$STATUS" \
  > "$LAST_STATUS"


if [ "$STATUS" -eq 0 ]; then
  print -r -- "$NOW_UTC" \
    > "$LAST_SUCCESS"

  rm -f \
    "$REVIEW_MARKER" \
    "$FAILURE_MARKER"

  exit 0
fi


if [ "$STATUS" -eq 2 ]; then
  if [ ! -f "$REVIEW_MARKER" ]; then
    print -r -- "$NOW_UTC" \
      > "$REVIEW_MARKER"

    notify \
      "Semantic review is required before new forecasts can run."
  fi

  # Expected human-gate state.
  # Do not report it to launchd as infrastructure failure.
  exit 0
fi


PREVIOUS_FAILURE="$(
  cat "$FAILURE_MARKER" \
    2>/dev/null \
    || true
)"

if [ "$PREVIOUS_FAILURE" != "$STATUS" ]; then
  notify \
    "Research cycle failed with exit code $STATUS. Check the Forecast Ledger log."
fi

print -r -- "$STATUS" \
  > "$FAILURE_MARKER"

exit "$STATUS"
