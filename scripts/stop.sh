#!/usr/bin/env bash
# Shut down the local Home Assistant UAT server started by ./scripts/start.sh (or leftover live hass).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

PID_FILE="$ROOT/outputs/ha_live/hass.pid"
LIVE_ROOT="$ROOT/outputs/ha_live"
HOST="${HA_HOST:-127.0.0.1}"
PORT="${HA_PORT:-8123}"
CONFIG_MARKER="$LIVE_ROOT"

stopped_any=0

kill_pid() {
  local pid="$1"
  local label="$2"
  if [[ -z "${pid:-}" ]] || ! kill -0 "$pid" 2>/dev/null; then
    return 0
  fi
  echo "Stopping $label (pid $pid) …"
  kill -TERM "$pid" 2>/dev/null || true
  for _ in $(seq 1 30); do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "  $label stopped"
      stopped_any=1
      return 0
    fi
    sleep 0.5
  done
  echo "  $label still running — SIGKILL"
  kill -KILL "$pid" 2>/dev/null || true
  sleep 0.5
  stopped_any=1
}

# 1) PID file from ./scripts/start.sh
if [[ -f "$PID_FILE" ]]; then
  pid="$(tr -d '[:space:]' <"$PID_FILE" || true)"
  if [[ -n "${pid:-}" ]]; then
    kill_pid "$pid" "hass (pid file)"
  fi
  rm -f "$PID_FILE"
fi

# 2) Any hass process using this repo's outputs/ha_live config
while read -r pid; do
  [[ -n "${pid:-}" ]] || continue
  kill_pid "$pid" "hass (live config)"
done < <(
  pgrep -f "${CONFIG_MARKER}.*/config" 2>/dev/null || true
)

# 3) Anything still bound to the UAT port (best-effort)
if curl -sf --connect-timeout 1 "http://${HOST}:${PORT}/" >/dev/null 2>&1; then
  if command -v lsof >/dev/null 2>&1; then
    while read -r pid; do
      [[ -n "${pid:-}" ]] || continue
      kill_pid "$pid" "listener on ${HOST}:${PORT}"
    done < <(lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN -t 2>/dev/null || true)
  fi
fi

if curl -sf --connect-timeout 1 "http://${HOST}:${PORT}/" >/dev/null 2>&1; then
  echo "error: http://${HOST}:${PORT} still responds after stop" >&2
  exit 1
fi

if [[ "$stopped_any" -eq 1 ]]; then
  echo "Home Assistant is down"
else
  echo "Home Assistant was not running"
fi
exit 0
