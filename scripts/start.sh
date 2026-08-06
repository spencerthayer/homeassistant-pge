#!/usr/bin/env bash
# Boot the local Home Assistant UAT server (http://127.0.0.1:8123).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

PID_FILE="$ROOT/outputs/ha_live/hass.pid"
LOG_FILE="$ROOT/outputs/ha_live/hass.log"
CURRENT_LINK="$ROOT/outputs/ha_live/current"
LIVE_ROOT="$ROOT/outputs/ha_live"
VENV_HASS="$ROOT/.venv/bin/hass"
VENV_PY="$ROOT/.venv/bin/python"
HOST="${HA_HOST:-127.0.0.1}"
PORT="${HA_PORT:-8123}"

if [[ ! -x "$VENV_HASS" ]]; then
  echo "error: missing $VENV_HASS — create the project venv first" >&2
  exit 1
fi

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "${old_pid:-}" ]] && kill -0 "$old_pid" 2>/dev/null; then
    echo "Home Assistant already running (pid $old_pid) — http://${HOST}:${PORT}"
    echo "  stop with: ./scripts/stop.sh"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

if curl -sf --connect-timeout 1 "http://${HOST}:${PORT}/" >/dev/null 2>&1; then
  echo "error: something already listens on ${HOST}:${PORT}; refuse to start a second instance" >&2
  echo "  tip: ./scripts/stop.sh   (or free the port), then ./scripts/start.sh" >&2
  exit 1
fi

mkdir -p "$LIVE_ROOT"

pick_run_dir() {
  local d resolved
  if [[ -L "$CURRENT_LINK" || -d "$CURRENT_LINK" ]]; then
    # Prefer readlink so a broken/self-referential current never becomes run_dir.
    resolved="$(readlink "$CURRENT_LINK" 2>/dev/null || true)"
    if [[ -n "${resolved:-}" && "${resolved}" != "$CURRENT_LINK" && -d "${resolved}/config" ]]; then
      printf '%s\n' "$resolved"
      return 0
    fi
    if [[ ! -L "$CURRENT_LINK" ]]; then
      d="$(cd "$CURRENT_LINK" 2>/dev/null && pwd -P || true)"
      if [[ -n "${d:-}" && "$d" != "$CURRENT_LINK" && -d "$d/config" ]]; then
        printf '%s\n' "$d"
        return 0
      fi
    fi
  fi
  # Newest timestamped dir with a config/
  find "$LIVE_ROOT" -mindepth 1 -maxdepth 1 -type d -name '20*' \
    | sort -r \
    | while read -r d; do
        if [[ -d "$d/config" ]]; then
          printf '%s\n' "$d"
          break
        fi
      done
}

run_dir="$(pick_run_dir || true)"

if [[ -z "${run_dir:-}" || ! -d "$run_dir/config" ]]; then
  echo "No existing live config — preparing a new run …"
  "$VENV_PY" "$ROOT/scripts/dev_ha_live_server.py" --prepare-only
  run_dir="$(pick_run_dir || true)"
fi

if [[ -z "${run_dir:-}" || ! -d "$run_dir/config" ]]; then
  echo "error: could not locate or create a live config under $LIVE_ROOT" >&2
  exit 1
fi

# Replace current atomically. Never ln -sfn into an existing symlink-to-dir
# (macOS follows the link and can create current/current).
rm -f "$CURRENT_LINK"
ln -s "$run_dir" "$CURRENT_LINK"
config_dir="$run_dir/config"

# Keep the custom component symlink pointed at the repo.
"$VENV_PY" -c "
from pathlib import Path
import shutil
root = Path(r'''$ROOT''')
source = (root / 'custom_components' / 'pge_energy').resolve()
target = Path(r'''$config_dir''') / 'custom_components' / 'pge_energy'
target.parent.mkdir(parents=True, exist_ok=True)
if target.is_symlink() or target.is_file():
    target.unlink()
elif target.is_dir():
    shutil.rmtree(target)
target.symlink_to(source, target_is_directory=True)
print(f'linked {target} -> {source}')
"

echo "Starting Home Assistant"
echo "  URL:     http://${HOST}:${PORT}"
echo "  config:  $config_dir"
echo "  run dir: $run_dir"
echo "  log:     $LOG_FILE"
if [[ -f "$run_dir/LOGIN.txt" ]]; then
  echo "  login:   see $run_dir/LOGIN.txt"
else
  echo "  login:   default dev / devpass"
fi

# Double-fork daemonize so Cursor/agent shell teardown cannot reap hass.
"$VENV_PY" - "$VENV_HASS" "$config_dir" "$LOG_FILE" "$PID_FILE" <<'PY'
import os
import sys

hass, config_dir, log_file, pid_file = sys.argv[1:5]
if os.fork() > 0:
    raise SystemExit(0)
os.setsid()
if os.fork() > 0:
    raise SystemExit(0)
os.chdir("/")
os.umask(0)
with open(pid_file, "w", encoding="utf-8") as handle:
    handle.write(str(os.getpid()))
devnull = open("/dev/null", "rb")
log = open(log_file, "ab", buffering=0)
os.dup2(devnull.fileno(), 0)
os.dup2(log.fileno(), 1)
os.dup2(log.fileno(), 2)
os.execv(hass, [hass, "-c", config_dir, "--ignore-os-check"])
PY

for _ in $(seq 1 90); do
  if curl -sf --connect-timeout 1 "http://${HOST}:${PORT}/" >/dev/null 2>&1; then
    echo "Home Assistant is up (pid $(cat "$PID_FILE"))"
    exit 0
  fi
  if ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "error: hass exited early — see $LOG_FILE" >&2
    rm -f "$PID_FILE"
    exit 1
  fi
  sleep 1
done

echo "warning: hass pid $(cat "$PID_FILE") is running but HTTP not ready yet; check $LOG_FILE"
exit 0
