#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"
TAURI_BIN_DIR="${ROOT_DIR}/frontend/src-tauri/binaries"

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

TARGET_TRIPLE="$(rustc -vV | awk '/host:/ {print $2}')"
if [[ -z "${TARGET_TRIPLE}" ]]; then
  echo "Failed to detect rust target triple."
  exit 1
fi

mkdir -p "${TAURI_BIN_DIR}"

pushd "${BACKEND_DIR}" >/dev/null
PYTHONPATH="${BACKEND_DIR}/src${PYTHONPATH+:${PYTHONPATH}}" python - <<'PY'
import subprocess

from magi.utils.sidecar_build import build_pyinstaller_command

subprocess.run(build_pyinstaller_command(), check=True)
PY
popd >/dev/null

SOURCE_BIN="${BACKEND_DIR}/dist/magi-backend"
TARGET_BIN="${TAURI_BIN_DIR}/magi-backend-${TARGET_TRIPLE}"

if [[ ! -f "${SOURCE_BIN}" ]]; then
  echo "Sidecar binary not found at ${SOURCE_BIN}"
  exit 1
fi

cp "${SOURCE_BIN}" "${TARGET_BIN}"
chmod +x "${TARGET_BIN}"

echo "Built sidecar: ${TARGET_BIN}"
