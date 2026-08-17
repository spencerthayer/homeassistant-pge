#!/usr/bin/env bash
# Canonical full-suite command for this repo.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python3 -m pytest tests/components -q
python3 -m pytest tests/recorder -p homeassistant -o addopts= -q
node --test tests/frontend/*.test.js
python3 scripts/scan_secrets.py
