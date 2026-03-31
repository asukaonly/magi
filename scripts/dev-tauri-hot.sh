#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="${ROOT_DIR}/frontend"
FRONTEND_PORT="${MAGI_FRONTEND_PORT:-5173}"
TAURI_BIN_DIR="${ROOT_DIR}/frontend/src-tauri/binaries"

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

cleanup_stale_dev_backends() {
  local pid_list
  local pid

  # Catch-all for any magi backend process (run_server.py with any role/port combination)
  # This ensures we don't leave orphaned processes even if the process command changes
  pid_list="$(ps -Ao pid=,command= | grep -E 'python.*run_server\.py' | grep -v grep | awk '{print $1}' || true)"
  
  if [[ -z "${pid_list}" ]]; then
    return 0
  fi

  echo "Stopping stale Magi backend process(es): ${pid_list}"
  while IFS= read -r pid; do
    [[ -z "${pid}" ]] && continue
    kill -TERM "${pid}" 2>/dev/null || true
  done <<< "${pid_list}"

  sleep 2

  # Check for any remaining processes (may have become zombies)
  pid_list="$(ps -Ao pid=,command= | grep -E 'python.*run_server\.py' | grep -v grep | awk '{print $1}' || true)"
  
  if [[ -z "${pid_list}" ]]; then
    return 0
  fi

  echo "Force stopping stale Magi backend process(es): ${pid_list}"
  while IFS= read -r pid; do
    [[ -z "${pid}" ]] && continue
    kill -KILL "${pid}" 2>/dev/null || true
  done <<< "${pid_list}"
}

cleanup_on_exit() {
  echo ""
  echo "dev-tauri-hot.sh shutting down..."
  cleanup_stale_dev_backends
  echo "Cleanup complete."
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
echo "Magi sidecar placeholder (debug fallback mode)."
exit 0
EOF
  chmod +x "${sidecar_path}"
  echo "Created sidecar placeholder for dev: ${sidecar_path}"
}

ensure_sidecar_placeholder
cleanup_stale_dev_backends
kill_listeners_on_port "${FRONTEND_PORT}"
trap cleanup_on_exit EXIT INT TERM HUP QUIT

echo "Starting Tauri desktop window (frontend HMR enabled by Vite)..."
echo "Backend lifecycle is owned by Tauri in debug mode."

cd "${FRONTEND_DIR}"
env \
  VITE_DEV_SERVER_PORT="${FRONTEND_PORT}" \
  npm run tauri:dev
