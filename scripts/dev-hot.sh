#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"
FRONTEND_DIR="${ROOT_DIR}/frontend"

FRONTEND_HOST="${MAGI_FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${MAGI_FRONTEND_PORT:-5173}"

BACKEND_PID=""
FRONTEND_PID=""

BACKEND_SETTINGS="$(
  cd "${BACKEND_DIR}"
  python - <<'PY'
import os
import sys
sys.path.insert(0, os.path.join(os.getcwd(), "src"))
from magi.config import get_config
cfg = get_config()
print(f"{cfg.server.host}|{cfg.server.port}|{int(bool(cfg.server.reload))}")
PY
)"
IFS='|' read -r BACKEND_HOST BACKEND_PORT BACKEND_RELOAD <<< "${BACKEND_SETTINGS}"

cleanup() {
  echo
  echo "Stopping dev processes..."

  if [[ -n "${BACKEND_PID}" ]] && kill -0 "${BACKEND_PID}" 2>/dev/null; then
    kill -TERM "${BACKEND_PID}" 2>/dev/null || true
  fi

  if [[ -n "${FRONTEND_PID}" ]] && kill -0 "${FRONTEND_PID}" 2>/dev/null; then
    kill -TERM "${FRONTEND_PID}" 2>/dev/null || true
  fi

  wait || true
  echo "All dev processes stopped."
}

trap cleanup EXIT INT TERM

echo "Starting dual-process backend supervisor..."
(
  cd "${BACKEND_DIR}"
  python run_supervisor.py
) &
BACKEND_PID=$!

echo "Starting frontend with hot reload..."
(
  cd "${FRONTEND_DIR}"
  npm run dev -- --host "${FRONTEND_HOST}" --port "${FRONTEND_PORT}"
) &
FRONTEND_PID=$!

echo
echo "Dev environment is up."
echo "Backend:  http://${BACKEND_HOST}:${BACKEND_PORT}"
echo "Backend topology: supervisor + api + runtime_worker"
echo "Backend reload(from config): ${BACKEND_RELOAD}"
echo "Frontend: http://${FRONTEND_HOST}:${FRONTEND_PORT}"
echo "Press Ctrl+C to stop both."

while true; do
  if ! kill -0 "${BACKEND_PID}" 2>/dev/null; then
    echo "Backend process exited unexpectedly."
    exit 1
  fi
  if ! kill -0 "${FRONTEND_PID}" 2>/dev/null; then
    echo "Frontend process exited unexpectedly."
    exit 1
  fi
  sleep 1
done
