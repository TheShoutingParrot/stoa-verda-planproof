#!/bin/sh
# Run the three new scan-next arms back to back under one GPU lock (docs/scan-next-protocol.md, R2 and R4):
#   .local/scan-next/with-gpu /bin/sh scripts/scan_next_arms.sh <CANDIDATE_SHA>
# Order: before-control, after, after-repeat. After each run, settle applies the time-out rule; a run that
# logged a time-out is set aside unseen and the arm runs again from scratch once, before the next arm.
# HARNESS and EXTRA override the harness command and add options (rehearsals on a dry manifest only).
set -u
C=${1:?usage: scan_next_arms.sh <CANDIDATE_SHA>}
PY=.local/scan-dev/objects/venv/bin/python
H=${HARNESS:-"$PY -B scripts/benchmark_scan_next.py"}
EXTRA=${EXTRA:-}
LOGS=${LOGS:-.local/evaluation/scan-next}
unset NEMOTRON_BASE_URL NEMOTRON_API_KEY
for arm in before-control after after-repeat; do
  rev=""
  [ "$arm" = before-control ] || rev="--revision $C"
  for attempt in 1 2; do
    echo "== $arm run $attempt start $(date +%H:%M:%S) $(uptime)" >> "$LOGS/arms.log"
    $H run --arm "$arm" $rev $EXTRA > "$LOGS/$arm-run-$attempt.log" 2>&1
    code=$?
    echo "   $arm run $attempt exit $code $(date +%H:%M:%S) $(uptime)" >> "$LOGS/arms.log"
    [ "$code" = 0 ] || { echo "$arm run $attempt failed; see $LOGS/$arm-run-$attempt.log" >&2; exit 1; }
    $H settle --arm "$arm" $EXTRA >> "$LOGS/arms.log" 2>&1
    code=$?
    [ "$code" = 0 ] && break
    [ "$code" = 2 ] && [ "$attempt" = 1 ] && continue
    echo "settle failed for $arm (exit $code); see $LOGS/arms.log" >&2
    exit 1
  done
done
echo "== all three arms sealed and settled $(date +%H:%M:%S)" >> "$LOGS/arms.log"
