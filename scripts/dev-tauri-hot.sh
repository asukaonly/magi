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
  local pattern
  local pid_list
  local pid

  for pattern in \
    "python run_server.py --role runtime_worker --no-reload" \
    "python run_server.py --role api --host"; do
    pid_list="$(ps -Ao pid=,command= | grep -F "${pattern}" | grep -v grep | awk '{print $1}' || true)"
    if [[ -z "${pid_list}" ]]; then
      continue
    fi

    echo "Stopping stale dev backend process(es): ${pid_list}"
    while IFS= read -r pid; do
      [[ -z "${pid}" ]] && continue
      kill -TERM "${pid}" 2>/dev/null || true
    done <<< "${pid_list}"
  done

  sleep 1

  for pattern in \
    "python run_server.py --role runtime_worker --no-reload" \
    "python run_server.py --role api --host"; do
    pid_list="$(ps -Ao pid=,command= | grep -F "${pattern}" | grep -v grep | awk '{print $1}' || true)"
    if [[ -z "${pid_list}" ]]; then
      continue
    fi

    echo "Force stopping stale dev backend process(es): ${pid_list}"
    while IFS= read -r pid; do
      [[ -z "${pid}" ]] && continue
      kill -KILL "${pid}" 2>/dev/null || true
    done <<< "${pid_list}"
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
echo "Magi sidecar placeholder (debug fallback mode)."
exit 0
EOF
  chmod +x "${sidecar_path}"
  echo "Created sidecar placeholder for dev: ${sidecar_path}"
}

ensure_sidecar_placeholder
cleanup_stale_dev_backends
kill_listeners_on_port "${FRONTEND_PORT}"

echo "Starting Tauri desktop window (frontend HMR enabled by Vite)..."
echo "Backend lifecycle is owned by Tauri in debug mode."

cd "${FRONTEND_DIR}"
exec env \
  VITE_DEV_SERVER_PORT="${FRONTEND_PORT}" \
  npm run tauri:dev
