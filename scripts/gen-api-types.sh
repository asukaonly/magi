#!/usr/bin/env bash
#
# Generate frontend TypeScript types from the FastAPI / pydantic backend.
#
# Runs the existing OpenAPI exporter and pipes the schema through
# openapi-typescript to write frontend/src/types/api/generated.ts.
# This script must be re-run whenever any backend pydantic model on the
# transport surface changes; CI fails the build if the committed
# generated.ts is stale (see docs/api-types-codegen-design.md §4.5).
#
set -euo pipefail

# Resolve repo root from the script's own location so the script can be
# invoked from any working directory (e.g. `npm run gen:api-types` in
# the frontend/ subdirectory).
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

# Precondition checks — fail with a self-actionable message rather than
# `set -e` exiting on the first command-not-found from `mktemp` / `python3` / `npx`.
for tool in python3 npx mktemp; do
  if ! command -v "${tool}" >/dev/null 2>&1; then
    echo "ERROR: required tool '${tool}' not found on PATH." >&2
    case "${tool}" in
      python3)
        echo "       Install Python 3.13+ and re-run." >&2 ;;
      npx)
        echo "       Run 'npm install' in frontend/ first." >&2 ;;
      mktemp)
        echo "       Install coreutils (Linux) or rely on the system mktemp (macOS)." >&2 ;;
    esac
    exit 1
  fi
done

# Temporary OpenAPI snapshot — not committed; lives in $TMPDIR and is
# removed on exit so successive runs do not accumulate stale snapshots.
OPENAPI_TMP="$(mktemp -t magi-openapi.XXXXXX.json)"
trap 'rm -f "${OPENAPI_TMP}"' EXIT

# Stale-venv guard — fastapi and pydantic minor versions change the
# OpenAPI output bytes (Body field format vs contentMediaType; model
# split into -Input/-Output halves vs combined). If the local env is
# older than what backend/pyproject.toml requires, generated.ts will
# drift from what CI produces. Fail fast with a self-actionable
# message instead of generating wrong bytes that pass locally but
# fail the api-types-drift CI job.
python3 - <<'PY' || exit 1
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1] if "__file__" in dir() else Path(".")
pyproject_path = Path("backend/pyproject.toml")
manifest = tomllib.loads(pyproject_path.read_text("utf-8"))
required = {}
for dep in manifest["project"]["dependencies"]:
    name = dep.split(">=")[0].split("[")[0].strip()
    if name in ("fastapi", "pydantic"):
        lo = dep.split(">=")[1].split(",")[0].strip()
        required[name] = lo

import importlib.metadata as md
errors = []
for name, lo in required.items():
    try:
        installed = md.version(name)
    except md.PackageNotFoundError:
        errors.append(f"  {name}: NOT INSTALLED (need >={lo})")
        continue
    inst_t = tuple(int(p) for p in installed.split(".")[:3])
    lo_t = tuple(int(p) for p in lo.split(".")[:3])
    if inst_t < lo_t:
        errors.append(f"  {name}: installed {installed}, pyproject requires >={lo}")
if errors:
    print(
        "ERROR: gen-api-types.sh dependencies are stale — would generate "
        "bytes that DIFFER from CI and fail api-types-drift on push.\n"
        + "\n".join(errors)
        + "\n\nFix: pip install --upgrade fastapi pydantic\n"
        "(or use a fresh venv via: pip install -e backend\\[dev\\])",
        file=sys.stderr,
    )
    sys.exit(1)
PY

echo "Exporting FastAPI OpenAPI schema..."
python3 scripts/export-python-openapi.py --output "${OPENAPI_TMP}"

echo "Generating frontend/src/types/api/generated.ts..."
(
  cd frontend
  # Run openapi-typescript via the locally-installed devDep (npx falls
  # back to PATH; we want frontend/node_modules to win).
  npx --no-install openapi-typescript "${OPENAPI_TMP}" \
      --output src/types/api/generated.ts \
      --immutable
)

echo "Done. Generated: frontend/src/types/api/generated.ts"
