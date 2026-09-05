#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"
SIDECAR_STAGING="${ROOT_DIR}/frontend/src-tauri/sidecar-dist"
PLUGIN_PYTHON_STAGING="${ROOT_DIR}/frontend/src-tauri/plugin-python"

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

stage_plugin_python() {
  rm -rf "${PLUGIN_PYTHON_STAGING}"

  if [[ -n "${MAGI_PLUGIN_PYTHON_SOURCE:-}" ]]; then
    if [[ ! -d "${MAGI_PLUGIN_PYTHON_SOURCE}" ]]; then
      echo "MAGI_PLUGIN_PYTHON_SOURCE does not exist or is not a directory: ${MAGI_PLUGIN_PYTHON_SOURCE}"
      exit 1
    fi
    local source_root="${MAGI_PLUGIN_PYTHON_SOURCE}"
    if [[ -d "${source_root}/python/install" ]]; then
      source_root="${source_root}/python/install"
    fi
    mkdir -p "${PLUGIN_PYTHON_STAGING}"
    cp -a "${source_root}/." "${PLUGIN_PYTHON_STAGING}/"
  else
    if [[ "${GITHUB_ACTIONS:-}" == "true" || "${MAGI_REQUIRE_RELOCATABLE_PLUGIN_PYTHON:-}" == "1" ]]; then
      echo "MAGI_PLUGIN_PYTHON_SOURCE is required for CI/release builds."
      echo "Use scripts/prepare-plugin-python-runtime.py to provide a relocatable Python runtime."
      exit 1
    fi
    echo "MAGI_PLUGIN_PYTHON_SOURCE not set; creating development plugin-python venv from build Python."
    echo "For release builds, provide a relocatable Python runtime via MAGI_PLUGIN_PYTHON_SOURCE."
    python -m venv --copies "${PLUGIN_PYTHON_STAGING}"
  fi

  local plugin_python="${PLUGIN_PYTHON_STAGING}/bin/python"
  if [[ ! -x "${plugin_python}" ]]; then
    for candidate in "${PLUGIN_PYTHON_STAGING}/bin/python3" "${PLUGIN_PYTHON_STAGING}"/bin/python3.*; do
      [[ -x "${candidate}" ]] || continue
      ln -s "$(basename "${candidate}")" "${plugin_python}"
      break
    done
  fi
  if [[ ! -x "${plugin_python}" ]]; then
    echo "Plugin Python executable not found at ${plugin_python}"
    exit 1
  fi
  "${plugin_python}" -m pip --version >/dev/null
  python "${ROOT_DIR}/scripts/install-plugin-worker-runtime.py" --python "${plugin_python}" --sdk "${ROOT_DIR}/sdk"
  echo "Staged plugin Python runtime: ${PLUGIN_PYTHON_STAGING}"
}

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
stage_plugin_python

echo "Built sidecar (onedir): ${SIDECAR_STAGING}"
