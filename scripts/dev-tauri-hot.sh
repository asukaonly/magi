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

BACKEND_PID=""
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

collect_descendant_pids() {
  local parent_pid="$1"
  local child_pid
  while IFS= read -r child_pid; do
    [[ -z "${child_pid}" ]] && continue
    echo "${child_pid}"
    collect_descendant_pids "${child_pid}"
  done < <(pgrep -P "${parent_pid}" 2>/dev/null || true)
}

signal_process_tree() {
  local signal_name="$1"
  local root_pid="$2"
  local descendants

  descendants="$(collect_descendant_pids "${root_pid}" | awk '!seen[$0]++')"
  if [[ -n "${descendants}" ]]; then
    while IFS= read -r pid; do
      [[ -z "${pid}" ]] && continue
      kill "-${signal_name}" "${pid}" 2>/dev/null || true
    done <<< "${descendants}"
  fi

  kill "-${signal_name}" "${root_pid}" 2>/dev/null || true
}

stop_backend_process_tree() {
  local root_pid="$1"
  local deadline

  if ! kill -0 "${root_pid}" 2>/dev/null; then
    return 0
  fi

  echo "Stopping backend process tree rooted at PID ${root_pid}..."
  signal_process_tree TERM "${root_pid}"

  deadline=$((SECONDS + 5))
  while kill -0 "${root_pid}" 2>/dev/null; do
    if (( SECONDS >= deadline )); then
      echo "Backend process tree did not exit after TERM, forcing stop..."
      signal_process_tree KILL "${root_pid}"
      break
    fi
    sleep 0.2
  done

  sleep 0.5
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

  if [[ -n "${BACKEND_PID}" ]] && kill -0 "${BACKEND_PID}" 2>/dev/null; then
    stop_backend_process_tree "${BACKEND_PID}"
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

ensure_sidecar_placeholder
cleanup_stale_backend_log_holders
kill_listeners_on_port "${BACKEND_PORT}"
kill_listeners_on_port "${FRONTEND_PORT}"

mkdir -p "$(dirname "${BACKEND_LOG_FILE}")"
touch "${BACKEND_LOG_FILE}"

echo "Starting backend for Tauri..."
(
  cd "${BACKEND_DIR}"
  python run_server.py
) >"${BACKEND_LOG_FILE}" 2>&1 &
BACKEND_PID=$!
echo "Backend logs: ${BACKEND_LOG_FILE}"
echo "Tail backend logs manually: tail -f ${BACKEND_LOG_FILE}"
echo "Backend bind host(from config): ${BACKEND_HOST}:${BACKEND_PORT}"
echo "Backend connect endpoint: http://${CONNECT_HOST}:${BACKEND_PORT}"
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
