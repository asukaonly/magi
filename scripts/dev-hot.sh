#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"
FRONTEND_DIR="${ROOT_DIR}/frontend"

BACKEND_HOST="${MAGI_BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${MAGI_BACKEND_PORT:-8000}"
FRONTEND_HOST="${MAGI_FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${MAGI_FRONTEND_PORT:-5173}"

BACKEND_PID=""
FRONTEND_PID=""

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

echo "Starting backend with hot reload..."
(
  cd "${BACKEND_DIR}"
  python run_server.py --host "${BACKEND_HOST}" --port "${BACKEND_PORT}" --reload
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

