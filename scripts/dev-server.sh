#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_PATH="${HOME}/.config/magi-server/dev.json"
COMMAND=""
ARGS=()
EXTRA=()
HAS_DATA=false
HAS_RUNTIME=false

usage() {
  cat <<'HELP'
Usage: scripts/dev-server.sh [command] [options]

Use the same commands as magi-server, with the development deployment selected.
  (no command)       Open setup or manage this deployment
  run                Run in this terminal (Ctrl+C stops the service)
  status [--json]     Inspect this deployment without starting it
  configure          Edit models, language and persona
  connect            Guide desktop pairing and HTTPS access
  logs [--follow]    Read service logs (--source service|backend)
  config show        Inspect deployment settings
  <command> --help    Show all options for a command

Default config: ~/.config/magi-server/dev.json
New deployment data: ~/.magi-center-dev
Use --config /absolute/path.json to select another deployment.
Use --data-dir and --port with first setup or init only.
Read-only commands never initialize a deployment or require Python.
Requires Cargo; starting a service also requires the repository's .venv.
Source changes require a restart; there is no hot reload.
HELP
}

if [[ $# -eq 1 && ( "$1" == --help || "$1" == -h ) ]]; then
  usage
  exit 0
fi
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config|--data-dir|--port|--development-root|--bundle-root)
      [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || { printf 'Missing value for %s\n' "$1" >&2; exit 1; }
      case "$1" in
        --config) CONFIG_PATH="$2" ;;
        --data-dir) HAS_DATA=true; ARGS+=("$1" "$2") ;;
        --development-root|--bundle-root) HAS_RUNTIME=true; ARGS+=("$1" "$2") ;;
        *) ARGS+=("$1" "$2") ;;
      esac
      shift 2 ;;
    --config=*) CONFIG_PATH="${1#--config=}"; shift ;;
    --data-dir=*) HAS_DATA=true; ARGS+=("$1"); shift ;;
    --development-root=*|--bundle-root=*) HAS_RUNTIME=true; ARGS+=("$1"); shift ;;
    *)
      if [[ -z "$COMMAND" && "$1" != -* ]]; then COMMAND="$1"; fi
      ARGS+=("$1"); shift ;;
  esac
done

[[ "$CONFIG_PATH" == /* ]] || { printf 'Configuration path must be absolute\n' >&2; exit 1; }
if [[ "$COMMAND" == init || ( -z "$COMMAND" && ! -e "$CONFIG_PATH" && ! -L "$CONFIG_PATH" ) ]]; then
  [[ "$HAS_DATA" == true ]] || EXTRA+=(--data-dir "${HOME}/.magi-center-dev")
  [[ "$HAS_RUNTIME" == true ]] || EXTRA+=(--development-root "$ROOT_DIR")
elif [[ "$COMMAND" == collect && "$HAS_RUNTIME" == false ]]; then
  EXTRA+=(--development-root "$ROOT_DIR")
fi
printf 'Development deployment: %s\n' "$CONFIG_PATH" >&2
cd "$ROOT_DIR"
exec cargo run --quiet --locked -p magi-server -- --config "$CONFIG_PATH" ${EXTRA[@]+"${EXTRA[@]}"} ${ARGS[@]+"${ARGS[@]}"}
