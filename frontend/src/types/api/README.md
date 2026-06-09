# Generated API types

The files in this directory are **generated from the backend FastAPI /
pydantic schema** by `scripts/gen-api-types.sh`. Do not hand-edit.

## When to regenerate

After any change to a pydantic model or FastAPI route that affects the
HTTP transport surface (`backend/src/magi/transport/http_app.py` and
the routers it mounts):

```bash
# From repo root, or from frontend/ via npm:
bash scripts/gen-api-types.sh
# or:
cd frontend && npm run gen:api-types
```

CI runs the generator on every PR and fails the build if the committed
`generated.ts` differs from what would be produced fresh. If you change
a backend schema and forget to commit the regenerated file, CI will
tell you.

## Files

- `generated.ts` — OpenAPI-derived TypeScript types. Read by
  `frontend/src/api/modules/*.ts` (incremental migration; see
  [`docs/api-types-codegen-design.md`](../../../../docs/api-types-codegen-design.md)
  §6 for the per-module plan).

## Frontend-only types

If you need a type that does not exist in the backend (e.g. a
view-model that combines fields from multiple endpoints, or a
component-local prop type), put it under `src/types/view/` or
co-locate with the component. Do **not** add hand-written declarations
to this directory — the next codegen run will overwrite them.

## Background

See `docs/api-types-codegen-design.md` for the full design (Phase 0
pipeline; Phase 1+N per-module migration).
