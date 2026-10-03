#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="${ROOT_DIR}/frontend"
BACKEND_DIR="${ROOT_DIR}/backend"
PROJECT_PYTHON="${ROOT_DIR}/.venv/bin/python"

echo "==> Installing frontend dependencies..."
cd "${FRONTEND_DIR}"
npm ci

echo ""
echo "==> Installing backend dependencies..."
if [ ! -d "${ROOT_DIR}/.venv" ]; then
    python3 -m venv "${ROOT_DIR}/.venv"
fi
if [ ! -x "${PROJECT_PYTHON}" ]; then
    echo "Project environment is incomplete: ${PROJECT_PYTHON}. Recreate .venv and retry." >&2
    exit 1
fi
echo "    using ${PROJECT_PYTHON}"

# Install into the same environment used by desktop and standalone dev services.
"${PROJECT_PYTHON}" -m pip install --upgrade setuptools wheel
"${PROJECT_PYTHON}" -m pip install --no-build-isolation -e "${ROOT_DIR}/sdk"
"${PROJECT_PYTHON}" -m pip install -e "${BACKEND_DIR}[dev]"

echo ""
echo "==> Checking local inference runtimes..."
"${PROJECT_PYTHON}" -c 'from magi.utils.inference_runtime import validate_inference_runtime; validate_inference_runtime()'

echo ""
echo "==> Building Rust workspace (Tauri + gateway)..."
cd "${ROOT_DIR}"
cargo build

echo ""
echo "All dependencies installed successfully."
