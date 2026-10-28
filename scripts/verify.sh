#!/usr/bin/env bash
# Project verification: the single definition of "done".
# Runs every checkpoint check script in order; all must pass.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=.venv/bin/python
if [ ! -x "$PY" ]; then
  echo "FAIL: .venv missing. Run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

# Generated glyph stores are gitignored; regenerate if absent.
if [ ! -f glyphs/synthetic/manifest.json ]; then
  "$PY" -m handwriting.synthglyphs
fi
if [ ! -f glyphs/demo/manifest.json ]; then
  "$PY" -m handwriting.demostore
fi

status=0
for check in scripts/checkpoint*_check.py scripts/feature_*_check.py; do
  echo "=== $check ==="
  if ! "$PY" "$check"; then
    status=1
  fi
  echo
done

if [ "$status" -ne 0 ]; then
  echo "verify: FAIL"
  exit 1
fi
echo "verify: ALL PASS"
