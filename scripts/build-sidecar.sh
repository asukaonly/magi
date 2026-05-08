#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"
SIDECAR_STAGING="${ROOT_DIR}/frontend/src-tauri/sidecar-dist"

if ! command -v rustc >/dev/null 2>&1; then
  echo "rustc is required to resolve target triple."
  exit 1
fi

if ! command -v python >/dev/null 2>&1; then
  echo "python command not found."
  exit 1
fi

if ! python -m PyInstaller --version >/dev/null 2>&1; then
  echo "PyInstaller is required. Install with: python -m pip install pyinstaller"
  exit 1
fi

pushd "${BACKEND_DIR}" >/dev/null
PYTHONPATH="${BACKEND_DIR}/src${PYTHONPATH+:${PYTHONPATH}}" python - <<'PY'
import subprocess

from magi.utils.sidecar_build import (
  build_pyinstaller_command,
  validate_sqlite_vec_runtime_support,
)

validate_sqlite_vec_runtime_support()
subprocess.run(build_pyinstaller_command(), check=True)
PY
popd >/dev/null

SOURCE_DIR="${BACKEND_DIR}/dist/magi-backend"
SOURCE_BIN="${SOURCE_DIR}/magi-backend"

if [[ ! -f "${SOURCE_BIN}" ]]; then
  echo "Sidecar binary not found at ${SOURCE_BIN}"
  exit 1
fi

# Copy entire --onedir output to Tauri resource staging directory
rm -rf "${SIDECAR_STAGING}"
cp -a "${SOURCE_DIR}" "${SIDECAR_STAGING}"
chmod +x "${SIDECAR_STAGING}/magi-backend"

echo "Built sidecar (onedir): ${SIDECAR_STAGING}"
