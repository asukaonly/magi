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
  echo
  echo "Stopping Tauri hot-reload dev environment..."

  if [[ -n "${BACKEND_PID}" ]] && kill -0 "${BACKEND_PID}" 2>/dev/null; then
    kill -TERM "${BACKEND_PID}" 2>/dev/null || true
    sleep 1
  fi

  local remain_port_pids
  remain_port_pids="$(lsof -tiTCP:${BACKEND_PORT} -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "${remain_port_pids}" ]]; then
    while IFS= read -r pid; do
      [[ -z "${pid}" ]] && continue
      kill -TERM "${pid}" 2>/dev/null || true
    done <<< "${remain_port_pids}"
  fi
}

trap cleanup EXIT INT TERM

ensure_sidecar_placeholder
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
