#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"
FRONTEND_DIR="${ROOT_DIR}/frontend"

FRONTEND_PORT="${MAGI_FRONTEND_PORT:-5173}"
BACKEND_LOG_FILE="${MAGI_BACKEND_LOG_FILE:-${HOME}/.magi/logs/backend-dev-hot.log}"
TAURI_BIN_DIR="${ROOT_DIR}/frontend/src-tauri/binaries"

BACKEND_SETTINGS="$(
  cd "${BACKEND_DIR}"
  python - <<'PY'
import os
import sys
sys.path.insert(0, os.path.join(os.getcwd(), "src"))
from magi.config import get_config
cfg = get_config()
token = (cfg.server.desktop_session_token or "").replace("|", "")
print(f"{cfg.server.host}|{cfg.server.port}|{int(bool(cfg.server.reload))}|{token}")
PY
)"
IFS='|' read -r BACKEND_HOST BACKEND_PORT BACKEND_RELOAD DESKTOP_TOKEN <<< "${BACKEND_SETTINGS}"

CONNECT_HOST="${MAGI_CONNECT_HOST:-${BACKEND_HOST}}"
if [[ "${CONNECT_HOST}" == "0.0.0.0" || "${CONNECT_HOST}" == "::" || "${CONNECT_HOST}" == "[::]" ]]; then
  CONNECT_HOST="127.0.0.1"
fi

BACKEND_API_PID=""
BACKEND_RUNTIME_PID=""
BACKEND_CLEANUP_DONE=0

cleanup_stale_backend_log_holders() {
  local holder_pids
  local pid
  local command

  holder_pids="$(lsof -t "${BACKEND_LOG_FILE}" 2>/dev/null | awk '!seen[$0]++' || true)"
  if [[ -z "${holder_pids}" ]]; then
    return 0
  fi

  while IFS= read -r pid; do
    [[ -z "${pid}" ]] && continue
    command="$(ps -p "${pid}" -o command= 2>/dev/null || true)"
    if [[ ! "${command}" =~ python ]] || [[ ! "${command}" =~ (run_server\.py|spawn_main|resource_tracker) ]]; then
      continue
    fi

    echo "Stopping stale backend log holder PID ${pid}: ${command}"
    kill -TERM "${pid}" 2>/dev/null || true
  done <<< "${holder_pids}"

  sleep 1

  holder_pids="$(lsof -t "${BACKEND_LOG_FILE}" 2>/dev/null | awk '!seen[$0]++' || true)"
  if [[ -z "${holder_pids}" ]]; then
    return 0
  fi

  while IFS= read -r pid; do
    [[ -z "${pid}" ]] && continue
    command="$(ps -p "${pid}" -o command= 2>/dev/null || true)"
    if [[ ! "${command}" =~ python ]] || [[ ! "${command}" =~ (run_server\.py|spawn_main|resource_tracker) ]]; then
      continue
    fi

    echo "Force stopping stale backend log holder PID ${pid}: ${command}"
    kill -KILL "${pid}" 2>/dev/null || true
  done <<< "${holder_pids}"
}

pick_backend_port() {
  local host="$1"
  local preferred_port="$2"
  python - "${host}" "${preferred_port}" <<'PY'
import socket
import sys

host = sys.argv[1] or "0.0.0.0"
preferred = int(sys.argv[2] or "0")

def try_bind(port: int):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError:
        sock.close()
        return None
    actual = sock.getsockname()[1]
    sock.close()
    return actual

if preferred > 0:
    picked = try_bind(preferred)
    if picked is not None:
        print(picked)
        raise SystemExit(0)

picked = try_bind(0)
if picked is None:
    raise SystemExit(1)
print(picked)
PY
}

kill_listeners_on_port() {
  local port="$1"
  local pids
  pids="$(lsof -tiTCP:${port} -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -z "${pids}" ]]; then
    return 0
  fi

  echo "Port ${port} is in use, stopping existing listener(s): ${pids}"
  while IFS= read -r pid; do
    [[ -z "${pid}" ]] && continue
    kill -TERM "${pid}" 2>/dev/null || true
  done <<< "${pids}"

  sleep 1

  pids="$(lsof -tiTCP:${port} -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -z "${pids}" ]]; then
    return 0
  fi

  echo "Port ${port} listener(s) still active after TERM, forcing stop: ${pids}"
  while IFS= read -r pid; do
    [[ -z "${pid}" ]] && continue
    kill -KILL "${pid}" 2>/dev/null || true
  done <<< "${pids}"
}

stop_backend_process() {
  local pid="$1"
  local label="$2"
  local deadline

  if [[ -z "${pid}" ]] || ! kill -0 "${pid}" 2>/dev/null; then
    return 0
  fi

  echo "Stopping backend ${label} process PID ${pid}..."
  kill -TERM "${pid}" 2>/dev/null || true

  deadline=$((SECONDS + 5))
  while kill -0 "${pid}" 2>/dev/null; do
    if (( SECONDS >= deadline )); then
      echo "Backend ${label} process did not exit after TERM, forcing stop..."
      kill -KILL "${pid}" 2>/dev/null || true
      break
    fi
    sleep 0.2
  done
}

ensure_sidecar_placeholder() {
  mkdir -p "${TAURI_BIN_DIR}"

  local triple
  triple="$(rustc -vV | awk '/host:/ {print $2}')"
  if [[ -z "${triple}" ]]; then
    echo "Failed to detect rust target triple for Tauri sidecar placeholder."
    exit 1
  fi

  local sidecar_path="${TAURI_BIN_DIR}/magi-backend-${triple}"
  if [[ -f "${sidecar_path}" ]]; then
    return 0
  fi

  cat > "${sidecar_path}" <<'EOF'
#!/usr/bin/env bash
echo "Magi sidecar placeholder (external backend mode)."
exit 0
EOF
  chmod +x "${sidecar_path}"
  echo "Created sidecar placeholder for dev: ${sidecar_path}"
}

cleanup() {
  if [[ "${BACKEND_CLEANUP_DONE}" -eq 1 ]]; then
    return 0
  fi
  BACKEND_CLEANUP_DONE=1

  echo
  echo "Stopping Tauri hot-reload dev environment..."

  if [[ -n "${BACKEND_RUNTIME_PID}" ]] && kill -0 "${BACKEND_RUNTIME_PID}" 2>/dev/null; then
    stop_backend_process "${BACKEND_RUNTIME_PID}" "runtime_worker"
  fi

  if [[ -n "${BACKEND_API_PID}" ]] && kill -0 "${BACKEND_API_PID}" 2>/dev/null; then
    stop_backend_process "${BACKEND_API_PID}" "api"
  fi

  local remain_port_pids
  remain_port_pids="$(lsof -tiTCP:${BACKEND_PORT} -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "${remain_port_pids}" ]]; then
    kill_listeners_on_port "${BACKEND_PORT}"
  fi
}

trap cleanup EXIT INT TERM HUP QUIT

wait_for_backend_ready() {
  local ready_url="http://${CONNECT_HOST}:${BACKEND_PORT}/api/ready"
  local deadline=$((SECONDS + 60))

  echo "Waiting for backend readiness: ${ready_url}"

  while true; do
    if python - "${ready_url}" <<'PY'
import json
import sys
import urllib.error
import urllib.request

url = sys.argv[1]

try:
    with urllib.request.urlopen(url, timeout=1.5) as response:
        payload = json.load(response)
except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
    raise SystemExit(1)

ready = bool(payload.get("data", {}).get("ready"))
raise SystemExit(0 if ready else 1)
PY
    then
      echo "Backend is ready."
      return 0
    fi

    if (( SECONDS >= deadline )); then
      echo "Backend did not become ready within 60 seconds."
      echo "Recent backend logs:"
      tail -n 40 "${BACKEND_LOG_FILE}" || true
      return 1
    fi

    sleep 0.5
  done
}

wait_for_runtime_worker_ready() {
  local deadline=$((SECONDS + 60))

  echo "Waiting for runtime worker heartbeat..."

  while true; do
    if (
      cd "${BACKEND_DIR}"
      python - <<'PY'
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.getcwd(), "src"))

from magi.runtime_trace import RuntimeTraceStore
from magi.utils.runtime import get_runtime_paths


async def main() -> int:
    store = RuntimeTraceStore(db_path=str(get_runtime_paths().runtime_trace_db_path))
    heartbeat = await store.get_runtime_heartbeat(role="runtime_worker")
    if heartbeat is not None and str(heartbeat.status or "").strip() == "ready":
        return 0
    return 1


raise SystemExit(asyncio.run(main()))
PY
    ); then
      echo "Runtime worker is ready."
      return 0
    fi

    if (( SECONDS >= deadline )); then
      echo "Runtime worker did not become ready within 60 seconds."
      echo "Recent backend logs:"
      tail -n 40 "${BACKEND_LOG_FILE}" || true
      return 1
    fi

    sleep 0.5
  done
}

ensure_sidecar_placeholder
cleanup_stale_backend_log_holders
kill_listeners_on_port "${FRONTEND_PORT}"

SELECTED_BACKEND_PORT="$(pick_backend_port "${BACKEND_HOST}" "${BACKEND_PORT}")"
if [[ "${SELECTED_BACKEND_PORT}" != "${BACKEND_PORT}" ]]; then
  echo "Backend port ${BACKEND_PORT} is unavailable, switching to ${SELECTED_BACKEND_PORT}."
fi
BACKEND_PORT="${SELECTED_BACKEND_PORT}"

mkdir -p "$(dirname "${BACKEND_LOG_FILE}")"
touch "${BACKEND_LOG_FILE}"

echo "Starting dual-process backend for Tauri..."
(
  cd "${BACKEND_DIR}"
  python run_server.py --role runtime_worker --no-reload
) >"${BACKEND_LOG_FILE}" 2>&1 &
BACKEND_RUNTIME_PID=$!
echo "Runtime worker PID: ${BACKEND_RUNTIME_PID}"
wait_for_runtime_worker_ready

(
  cd "${BACKEND_DIR}"
  python run_server.py --role api --host "${BACKEND_HOST}" --port "${BACKEND_PORT}" --no-reload
) >>"${BACKEND_LOG_FILE}" 2>&1 &
BACKEND_API_PID=$!
echo "API PID: ${BACKEND_API_PID}"
echo "Backend logs: ${BACKEND_LOG_FILE}"
echo "Tail backend logs manually: tail -f ${BACKEND_LOG_FILE}"
echo "Backend bind host(from config): ${BACKEND_HOST}:${BACKEND_PORT}"
echo "Backend connect endpoint: http://${CONNECT_HOST}:${BACKEND_PORT}"
echo "Backend topology: api + runtime_worker"
echo "Backend reload(from config): ${BACKEND_RELOAD}"
wait_for_backend_ready

echo "Starting Tauri desktop window (frontend HMR enabled by Vite)..."
(
  cd "${FRONTEND_DIR}"
  MAGI_TAURI_EXTERNAL_BACKEND=1 \
  MAGI_TAURI_EXTERNAL_BACKEND_HOST="${CONNECT_HOST}" \
  MAGI_TAURI_EXTERNAL_BACKEND_PORT="${BACKEND_PORT}" \
  MAGI_TAURI_EXTERNAL_BACKEND_API_BASE="http://${CONNECT_HOST}:${BACKEND_PORT}/api" \
  MAGI_TAURI_EXTERNAL_BACKEND_WS_BASE="ws://${CONNECT_HOST}:${BACKEND_PORT}" \
  MAGI_DESKTOP_SESSION_TOKEN="${DESKTOP_TOKEN}" \
  VITE_DEV_SERVER_PORT="${FRONTEND_PORT}" \
  npm run tauri:dev
)
