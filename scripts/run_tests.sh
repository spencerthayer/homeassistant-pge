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
"$PY" scripts/scan_secrets.py
