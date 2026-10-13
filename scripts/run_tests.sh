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
  echo "error: node is required for frontend tests (install Node.js 18.19+)" >&2
  exit 1
fi
node_ok="$(node -p "const p=process.versions.node.split('.').map(Number); p[0]>18||(p[0]===18&&p[1]>=19)")"
if [[ "$node_ok" != "true" ]]; then
  echo "error: frontend tests require Node.js 18.19+ (found $(node -v))" >&2
  exit 1
fi
node --import ./tests/frontend/register-hooks.mjs --test tests/frontend/*.test.js
"$PY" scripts/scan_secrets.py
