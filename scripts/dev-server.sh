#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_PATH="${HOME}/.config/magi-server/dev.json"
DATA_DIR="${HOME}/.magi-center-dev"
PORT=19080
INIT_OPTIONS_SET=false

usage() {
  cat <<'EOF'
Usage: scripts/dev-server.sh [--config <file>] [--data-dir <directory>] [--port <port>]

Start the development center without Tauri or the frontend.
Requires Cargo and the repository's .venv with backend dependencies installed.

  --config    Absolute configuration path (default: ~/.config/magi-server/dev.json)
  --data-dir  Absolute data directory for a NEW config (default: ~/.magi-center-dev)
  --port      HTTP port for a NEW config (default: 19080; 0 chooses a free port)
  -h, --help  Show this help

Existing configurations are reused without modification. To change an existing
port or data directory, edit that config or choose a new --config path.
Stop with Ctrl+C. Source changes require a restart; there is no hot reload.
EOF
}

fail() {
  printf 'Error: %s\n' "$1" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --config|--data-dir|--port)
      [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || fail "Missing value for $1"
      case "$1" in
        --config) CONFIG_PATH="$2" ;;
        --data-dir) DATA_DIR="$2"; INIT_OPTIONS_SET=true ;;
        --port) PORT="$2"; INIT_OPTIONS_SET=true ;;
      esac
      shift 2
      ;;
    *) fail "Unknown argument: $1 (use --help)" ;;
  esac
done

[[ "$CONFIG_PATH" == /* ]] || fail "Configuration path must be absolute"
if [[ -e "$CONFIG_PATH" || -L "$CONFIG_PATH" ]]; then
  [[ "$INIT_OPTIONS_SET" == false ]] || fail "--data-dir and --port only apply to a new configuration"
fi
command -v cargo >/dev/null 2>&1 || fail "Cargo is required; install the Rust toolchain first"
[[ -x "${ROOT_DIR}/.venv/bin/python" ]] || fail "Install the backend development environment in ${ROOT_DIR}/.venv first"

cd "$ROOT_DIR"
if [[ ! -e "$CONFIG_PATH" && ! -L "$CONFIG_PATH" ]]; then
  cargo run --locked -p magi-server -- init \
    --config "$CONFIG_PATH" \
    --data-dir "$DATA_DIR" \
    --development-root "$ROOT_DIR" \
    --port "$PORT"
fi

printf 'Starting development center with config: %s\n' "$CONFIG_PATH"
# The service owner handles shutdown and recovery; the launcher owns no extra supervisor.
exec cargo run --locked -p magi-server -- run --config "$CONFIG_PATH"
