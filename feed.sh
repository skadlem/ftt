#!/usr/bin/env bash
# feed.sh — keep-trying wrapper for the long-call feeders on flaky routes.
# Usage: ./feed.sh <label> <command...>     (runs forever until rc=0)
# Launch each feeder in its own background session:
#   nohup ./feed.sh teacher  python3 teacher/sample.py --tasks tasks/train_pool.jsonl --out traces/ >> logs/feed-teacher.log 2>&1 &
set -u
label="$1"; shift
cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]:-$0}")")"
mkdir -p logs
pass=0
while true; do
  pass=$((pass+1))
  echo "[feed:$label] pass $pass $(date -u +%FT%TZ)"
  if "$@"; then
    echo "[feed:$label] DONE after $pass pass(es) $(date -u +%FT%TZ)"
    exit 0
  fi
  rc=$?
  if [ "$rc" -eq 2 ] && [ "$label" = "teacher" ]; then
    echo "[feed:$label] rc=2 = disjointness refusals (policy, not network) — stop"
    exit 2
  fi
  sleep $((60 + RANDOM % 120))   # back off 1-3 min between passes
done
