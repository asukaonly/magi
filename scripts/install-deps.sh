#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="${ROOT_DIR}/frontend"
BACKEND_DIR="${ROOT_DIR}/backend"

echo "==> Installing frontend dependencies..."
cd "${FRONTEND_DIR}"
npm install

echo ""
echo "==> Installing backend dependencies..."
cd "${BACKEND_DIR}"

# Pick pip: prefer the project's .venv (used by the Tauri gateway at runtime)
# over whatever pip happens to be on PATH (often a different Python like conda).
# Falls back to PATH pip if no .venv exists yet.
if [ -x "${ROOT_DIR}/.venv/bin/pip" ]; then
    PIP="${ROOT_DIR}/.venv/bin/pip"
    echo "    using ${PIP}"
else
    PIP="pip"
    echo "    no ${ROOT_DIR}/.venv found, using ${PIP} from PATH"
fi

# Install the plugin SDK first (local editable, before the backend that depends on it)
"${PIP}" install --no-build-isolation -e "${ROOT_DIR}/sdk"
"${PIP}" install -e ".[dev]" 2>/dev/null || "${PIP}" install -e .

echo ""
echo "==> Building Rust workspace (Tauri + gateway)..."
cd "${ROOT_DIR}"
cargo build

echo ""
echo "All dependencies installed successfully."
