#!/usr/bin/env bash
# Canonical full-suite command for this repo.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="python3"
fi
"$PY" -m pytest tests/components -q
"$PY" -m pytest tests/recorder -p homeassistant -o addopts= -q
if ! command -v node >/dev/null 2>&1; then
  echo "error: node is required for frontend tests (install Node.js 18+)" >&2
  exit 1
fi
node --test tests/frontend/*.test.js
"$PY" scripts/scan_secrets.py
