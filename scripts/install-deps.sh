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
# Install the plugin SDK first (local editable, before the backend that depends on it)
pip install --no-build-isolation -e "${ROOT_DIR}/sdk"
pip install -e ".[dev]" 2>/dev/null || pip install -e .

echo ""
echo "==> Building Rust workspace (Tauri + gateway)..."
cd "${ROOT_DIR}"
cargo build

echo ""
echo "All dependencies installed successfully."
