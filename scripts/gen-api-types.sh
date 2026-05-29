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

# Temporary OpenAPI snapshot — not committed; lives in $TMPDIR and is
# removed on exit so successive runs do not accumulate stale snapshots.
OPENAPI_TMP="$(mktemp -t magi-openapi.XXXXXX.json)"
trap 'rm -f "${OPENAPI_TMP}"' EXIT

echo "Exporting FastAPI OpenAPI schema..."
python scripts/export-python-openapi.py --output "${OPENAPI_TMP}"

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
