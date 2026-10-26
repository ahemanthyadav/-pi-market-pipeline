#!/bin/bash
# Run EVERY test in tests/ — the single entrypoint used by both AGENTS.md
# ("Before any push") and .github/workflows/ci.yml, so a new test file can never
# be forgotten in either place: anything matching tests/test_*.py or
# tests/test-*.sh is picked up automatically.
#
# Usage: bash tests/run-all.sh      (from anywhere inside the repo)
# Exits non-zero if any test fails; individual suites may self-skip (and say so)
# when their prerequisites are absent (e.g. test-pg-backup.sh without a dump).
set -u
cd "$(git rev-parse --show-toplevel)"
fail=0
for t in tests/test_*.py; do
  echo "== $t"
  python3 "$t" || { echo "FAILED: $t"; fail=1; }
done
for t in tests/test-*.sh; do
  echo "== $t"
  bash "$t" || { echo "FAILED: $t"; fail=1; }
done
[ "$fail" -eq 0 ] && echo "run-all: all green" || echo "run-all: FAILURES above"
exit "$fail"
