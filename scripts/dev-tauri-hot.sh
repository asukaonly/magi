#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"
FRONTEND_DIR="${ROOT_DIR}/frontend"

BACKEND_HOST="${MAGI_BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${MAGI_BACKEND_PORT:-8000}"

# Use a stable dev token so HTTP/WS desktop auth passes while backend reload is enabled.
DESKTOP_TOKEN="${MAGI_DESKTOP_SESSION_TOKEN:-magi-desktop-dev-token}"

BACKEND_PID=""

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

echo "Starting backend with hot reload for Tauri..."
(
  cd "${BACKEND_DIR}"
  MAGI_DESKTOP_MODE=1 \
  MAGI_DESKTOP_SESSION_TOKEN="${DESKTOP_TOKEN}" \
  python run_server.py \
    --host "${BACKEND_HOST}" \
    --port "${BACKEND_PORT}" \
    --reload
) &
BACKEND_PID=$!

echo "Starting Tauri desktop window (frontend HMR enabled by Vite)..."
(
  cd "${FRONTEND_DIR}"
  MAGI_TAURI_EXTERNAL_BACKEND=1 \
  MAGI_TAURI_EXTERNAL_BACKEND_HOST="${BACKEND_HOST}" \
  MAGI_TAURI_EXTERNAL_BACKEND_PORT="${BACKEND_PORT}" \
  MAGI_TAURI_EXTERNAL_BACKEND_API_BASE="http://${BACKEND_HOST}:${BACKEND_PORT}/api" \
  MAGI_TAURI_EXTERNAL_BACKEND_WS_BASE="ws://${BACKEND_HOST}:${BACKEND_PORT}" \
  MAGI_DESKTOP_SESSION_TOKEN="${DESKTOP_TOKEN}" \
  npm run tauri:dev
)

