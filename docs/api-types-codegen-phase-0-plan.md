# API Types Codegen — Phase 0 Implementation Plan

**Status:** Complete — generator, committed output, and CI/release drift gates shipped.

> Historical execution record: every task below is complete; the checked steps preserve the rollout and its validation sequence.

**Goal:** Plumb the FastAPI → openapi-typescript → frontend type-generation pipeline end to end, with a CI drift check, but without migrating any existing `api/modules/*.ts`. After this plan, the pipeline exists and CI enforces it; the migration to use generated types is Phase 1+ (separate plans).

**Architecture:** Add an `openapi-typescript@^7` devDep to the frontend. Write `scripts/gen-api-types.sh` that runs the existing `scripts/export-python-openapi.py`, pipes the OpenAPI JSON through `npx openapi-typescript`, and writes `frontend/src/types/api/generated.ts`. Commit the first generated output to git. Add a `api-types-drift` job to `ci.yml` (and an equivalent step to `release.yml`) that re-runs the generator and fails if the result differs from what's committed.

**Tech Stack:** `openapi-typescript@^7` (TypeScript codegen, types only — zero runtime cost), bash for the generator wrapper, existing `scripts/export-python-openapi.py` (Python entry that already works in CI), GitHub Actions for the drift check.

**Spec reference:** `docs/api-types-codegen-design.md` (committed at `c54dec53`).

---

## File Structure

This plan creates / modifies these files:

| Path | Action | Responsibility |
|------|--------|---------------|
| `scripts/gen-api-types.sh` | Create | Bash wrapper: run OpenAPI export → openapi-typescript → generated.ts |
| `frontend/src/types/api/generated.ts` | Create | First codegen output (committed to git) |
| `frontend/src/types/api/README.md` | Create | "Don't hand-edit; here's how to regen" doc |
| `frontend/package.json` | Modify | Add `openapi-typescript` devDep + `gen:api-types` npm script |
| `frontend/package-lock.json` | Modify | Auto-updated by npm |
| `.github/workflows/ci.yml` | Modify | Add `api-types-drift` job |
| `.github/workflows/release.yml` | Modify | Add drift check step before `Run frontend validation` |

No existing `frontend/src/api/modules/*.ts` files are touched in Phase 0.

---

## Task 1: Add `openapi-typescript` devDependency

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`

- [x] **Step 1: Install the devDep**

```bash
cd /Users/asuka/code/magi/frontend
npm install --save-dev openapi-typescript@^7
```

Expected: Installs `openapi-typescript` and writes the version into `frontend/package.json` `devDependencies` (should resolve to `^7.13.0` or whatever the current 7.x latest is at run time).

- [x] **Step 2: Verify it shows up in package.json**

```bash
grep '"openapi-typescript"' /Users/asuka/code/magi/frontend/package.json
```

Expected: one line of output like `    "openapi-typescript": "^7.13.0",` (the patch version may differ).

- [x] **Step 3: Verify baseline still green**

```bash
cd /Users/asuka/code/magi/frontend
npm run type-check
npm run test:ci 2>&1 | grep -E "(Test Files|Tests)" | head -3
npm run build 2>&1 | tail -3
```

Expected:
- `type-check`: clean (no `error TS...` lines)
- `test:ci`: `Test Files  88 passed (88)` and `Tests  547 passed (547)` (or higher counts — must equal the pre-task baseline; never fewer)
- `build`: `✓ built in ...`

**No commit yet** — bundles cleanly with Task 5.

---

## Task 2: Create the codegen wrapper script

**Files:**
- Create: `scripts/gen-api-types.sh`

- [x] **Step 1: Write the script**

Create `/Users/asuka/code/magi/scripts/gen-api-types.sh` with exactly this content:

```bash
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
```

- [x] **Step 2: Make it executable**

```bash
chmod +x /Users/asuka/code/magi/scripts/gen-api-types.sh
```

- [x] **Step 3: Verify shebang & permissions**

```bash
ls -l /Users/asuka/code/magi/scripts/gen-api-types.sh
```

Expected: leading `-rwxr-xr-x` (the `x` bits matter).

**No commit yet.**

---

## Task 3: Create the types/api directory and its README

**Files:**
- Create: `frontend/src/types/api/README.md`

(The `frontend/src/types/api/` directory itself will be created implicitly when the README is written.)

- [x] **Step 1: Write the README**

Create `/Users/asuka/code/magi/frontend/src/types/api/README.md` with this content:

```markdown
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
```

- [x] **Step 2: Verify the directory and README exist**

```bash
ls /Users/asuka/code/magi/frontend/src/types/api/
```

Expected: `README.md` (and later `generated.ts` after Task 5).

**No commit yet.**

---

## Task 4: Wire the npm script

**Files:**
- Modify: `frontend/package.json`

- [x] **Step 1: Add `gen:api-types` script entry**

Locate the `"scripts"` block in `frontend/package.json` (currently around lines 7-16). It looks like:

```json
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview",
    "lint": "eslint . --ext ts,tsx --report-unused-disable-directives --max-warnings 0",
    "type-check": "tsc --noEmit",
    "test": "vitest run",
    "test:ci": "vitest run src/__tests__",
    "tauri": "tauri",
    "tauri:dev": "tauri dev",
    "tauri:build": "tauri build"
  },
```

Add a new key `"gen:api-types": "bash ../scripts/gen-api-types.sh"` immediately after `"test:ci"`:

```json
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview",
    "lint": "eslint . --ext ts,tsx --report-unused-disable-directives --max-warnings 0",
    "type-check": "tsc --noEmit",
    "test": "vitest run",
    "test:ci": "vitest run src/__tests__",
    "gen:api-types": "bash ../scripts/gen-api-types.sh",
    "tauri": "tauri",
    "tauri:dev": "tauri dev",
    "tauri:build": "tauri build"
  },
```

- [x] **Step 2: Sanity-check the JSON is still valid**

```bash
node -e "require('/Users/asuka/code/magi/frontend/package.json')" && echo "valid JSON"
```

Expected: `valid JSON` printed; no SyntaxError.

**No commit yet.**

---

## Task 5: Run the generator and commit Phase-0 pipeline

**Files:**
- Create: `frontend/src/types/api/generated.ts` (produced by the script)
- (Touches all files modified/created in Tasks 1-4)

- [x] **Step 1: Run the generator**

```bash
cd /Users/asuka/code/magi/frontend
npm run gen:api-types
```

Expected output:
```
Exporting FastAPI OpenAPI schema...
Generating frontend/src/types/api/generated.ts...
Done. Generated: frontend/src/types/api/generated.ts
```

- [x] **Step 2: Verify generated.ts looks sane**

```bash
wc -l /Users/asuka/code/magi/frontend/src/types/api/generated.ts
head -20 /Users/asuka/code/magi/frontend/src/types/api/generated.ts
grep -c "export interface\|export type" /Users/asuka/code/magi/frontend/src/types/api/generated.ts || true
```

Expected:
- Line count: more than 100 (an empty or near-empty file means the OpenAPI export produced no schemas — investigate before continuing).
- Head should show an auto-generated header from `openapi-typescript`, then `export interface paths` or `export type paths`.
- A nonzero count of `export interface` or `export type` lines.

- [x] **Step 3: Verify the generated file type-checks**

```bash
cd /Users/asuka/code/magi/frontend
npm run type-check 2>&1 | tail -5
```

Expected: no `error TS` lines (clean exit). The generated file is included by `tsconfig.json`'s `"include": ["src"]`.

- [x] **Step 4: Inspect the `unknown` density**

```bash
grep -c "unknown" /Users/asuka/code/magi/frontend/src/types/api/generated.ts || true
grep -c "Record<string, unknown>" /Users/asuka/code/magi/frontend/src/types/api/generated.ts || true
```

Record these numbers in the commit message body. They are the spec's Risk §8.1 — "OpenAPI export 可能不全" — surfacing as concrete data. Do **not** fail or block on high counts; this is intentionally just observational input for Phase 1 planning.

- [x] **Step 5: Verify the existing build + tests are still green**

```bash
npm run test:ci 2>&1 | grep -E "(Test Files|Tests)" | head -3
npm run build 2>&1 | tail -5
```

Expected:
- Test count not lower than the pre-Task-1 baseline (`88 / 547` or whatever the baseline was).
- `✓ built in ...` line.

- [x] **Step 6: Commit the pipeline + first generated.ts**

```bash
cd /Users/asuka/code/magi
git add scripts/gen-api-types.sh \
        frontend/package.json \
        frontend/package-lock.json \
        frontend/src/types/api/README.md \
        frontend/src/types/api/generated.ts

git commit -m "$(cat <<'EOF'
feat(types): plumb openapi-typescript codegen pipeline (Phase 0)

Adds the FastAPI → openapi-typescript → frontend codegen pipeline
described in docs/api-types-codegen-design.md. After this commit:

* scripts/gen-api-types.sh wraps the existing
  scripts/export-python-openapi.py and pipes the schema through
  openapi-typescript into frontend/src/types/api/generated.ts.
* frontend/package.json gains openapi-typescript@^7 as a devDep and a
  `gen:api-types` npm script that calls the wrapper.
* The first generated.ts is committed so PR diffs surface schema
  changes; reviewers see the diff directly without rebuilding locally.
* frontend/src/types/api/README.md explains the regenerate command and
  the "do not hand-edit" rule.

Phase 0 does NOT yet migrate any frontend/src/api/modules/*.ts to
import from the generated file. That's Phase 1+ (per-module PRs,
tracked separately).

Verified: tsc clean, test:ci unchanged at baseline, vite build green.

generated.ts observational metrics (Spec §8.1 — OpenAPI export
completeness baseline):
* Total lines: <fill from Step 2>
* `unknown` occurrences: <fill from Step 4>
* `Record<string, unknown>` occurrences: <fill from Step 4>

These are recorded so Phase 1 module-migration PRs can decide which
endpoints need backend pydantic refinement before migration.
EOF
)"
```

Before running the commit, replace the three `<fill from ...>` placeholders with the actual numbers you observed.

- [x] **Step 7: Verify the commit landed cleanly**

```bash
git log --oneline -1
git show --stat HEAD | head -15
```

Expected: one new commit with subject `feat(types): plumb openapi-typescript codegen pipeline (Phase 0)`, touching the 5 files listed above (plus the lockfile).

---

## Task 6: Add the drift-check job to `ci.yml`

**Files:**
- Modify: `.github/workflows/ci.yml`

The current `ci.yml` (read it at `/Users/asuka/code/magi/.github/workflows/ci.yml`) has separate top-level jobs. We're adding a new sibling job `api-types-drift` that sets up Python + Node + backend deps, runs the generator, and asserts `git diff --exit-code`.

- [x] **Step 1: Read the current ci.yml top to confirm the `jobs:` block**

```bash
grep -n "^jobs:\|^  [a-z]" /Users/asuka/code/magi/.github/workflows/ci.yml
```

Expected: a `jobs:` line followed by sibling job names indented two spaces. Note the indentation of existing jobs.

- [x] **Step 2: Append the new job at the end of `ci.yml`**

Open `/Users/asuka/code/magi/.github/workflows/ci.yml` and append this block as the last top-level job under `jobs:` (preserve existing indentation; existing jobs are two-spaces-indented sibling keys of `jobs:`):

```yaml
  api-types-drift:
    name: Generated API types in sync with backend
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v5

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.13.5"

      - name: Set up Node.js
        uses: actions/setup-node@v5
        with:
          node-version: 20
          cache: npm
          cache-dependency-path: frontend/package-lock.json

      - name: Install backend (for FastAPI OpenAPI export)
        working-directory: backend
        run: |
          python -m pip install --upgrade pip
          pip install -e ../sdk
          pip install -e .

      - name: Install frontend dependencies
        working-directory: frontend
        run: npm ci

      - name: Regenerate API types
        run: bash scripts/gen-api-types.sh

      - name: Assert generated.ts is committed up to date
        run: |
          if ! git diff --exit-code -- frontend/src/types/api/generated.ts; then
            echo "::error::frontend/src/types/api/generated.ts is stale."
            echo "Run 'bash scripts/gen-api-types.sh' locally and commit the result."
            exit 1
          fi
```

- [x] **Step 3: Validate the YAML**

```bash
python -c "import yaml; yaml.safe_load(open('/Users/asuka/code/magi/.github/workflows/ci.yml'))" && echo "valid YAML"
```

Expected: `valid YAML` printed; no traceback.

**No commit yet** — bundle with Task 7.

---

## Task 7: Add the drift-check step to `release.yml`

**Files:**
- Modify: `.github/workflows/release.yml`

The release workflow already sets up Python, Node, and backend deps (lines 48-109 of the current file). We only need to insert the regenerate + assert step *before* `Run frontend validation` (currently around line 160).

- [x] **Step 1: Locate the insertion point**

```bash
grep -n "Run frontend validation\|Install frontend dependencies" /Users/asuka/code/magi/.github/workflows/release.yml
```

Expected: two line numbers showing `Install frontend dependencies` first, then `Run frontend validation`. The new step goes between them.

- [x] **Step 2: Insert the drift-check step**

Open `/Users/asuka/code/magi/.github/workflows/release.yml`. Find the block (approximately lines 155-167):

```yaml
      - name: Install frontend dependencies
        working-directory: frontend
        shell: bash
        run: npm ci

      - name: Run frontend validation
        working-directory: frontend
        shell: bash
        run: |
          npm run type-check
          npm run test:ci
          npm run lint
```

Insert this new step between them so the block becomes:

```yaml
      - name: Install frontend dependencies
        working-directory: frontend
        shell: bash
        run: npm ci

      - name: Verify generated API types are up to date
        shell: bash
        run: |
          bash scripts/gen-api-types.sh
          if ! git diff --exit-code -- frontend/src/types/api/generated.ts; then
            echo "::error::frontend/src/types/api/generated.ts is stale."
            echo "Run 'bash scripts/gen-api-types.sh' locally and commit the result."
            exit 1
          fi

      - name: Run frontend validation
        working-directory: frontend
        shell: bash
        run: |
          npm run type-check
          npm run test:ci
          npm run lint
```

- [x] **Step 3: Validate the YAML**

```bash
python -c "import yaml; yaml.safe_load(open('/Users/asuka/code/magi/.github/workflows/release.yml'))" && echo "valid YAML"
```

Expected: `valid YAML`.

**No commit yet** — bundle with Task 9.

---

## Task 8: Smoke-test the drift detection locally

This task does **not** modify committed state. It verifies that the drift logic actually fires when generated.ts is out of date.

- [x] **Step 1: Simulate drift**

```bash
cd /Users/asuka/code/magi
# Append a stray comment to generated.ts to make it look "edited":
echo "// intentionally-stale-marker-DELETE-ME" >> frontend/src/types/api/generated.ts
```

- [x] **Step 2: Re-run the generator**

```bash
bash scripts/gen-api-types.sh
```

Expected: regenerator overwrites generated.ts, removing the stray comment.

- [x] **Step 3: Confirm git sees no diff (regenerator restored the canonical form)**

```bash
git diff --exit-code -- frontend/src/types/api/generated.ts && echo "OK: no drift after regen"
```

Expected: `OK: no drift after regen`. This proves the workflow `git diff --exit-code` step will pass when the committed file is up to date.

- [x] **Step 4: Simulate the failure path**

```bash
cd /Users/asuka/code/magi
# Edit generated.ts directly without regenerating — this is what
# "stale because contributor forgot to run the generator" looks like.
echo "// intentionally-stale-marker-DELETE-ME" >> frontend/src/types/api/generated.ts

# This is the exact command the CI workflow runs:
if ! git diff --exit-code -- frontend/src/types/api/generated.ts; then
  echo "EXPECTED: drift detected (this is what CI would print as an error)"
fi
```

Expected: the diff command exits nonzero, the script prints `EXPECTED: drift detected ...`, confirming the CI logic would catch a forgotten regenerate.

- [x] **Step 5: Clean up**

```bash
cd /Users/asuka/code/magi
git checkout -- frontend/src/types/api/generated.ts
git diff --exit-code -- frontend/src/types/api/generated.ts && echo "clean"
```

Expected: `clean`.

**No commit in this task.**

---

## Task 9: Commit the CI integration

**Files:**
- Modify: `.github/workflows/ci.yml` (from Task 6)
- Modify: `.github/workflows/release.yml` (from Task 7)

- [x] **Step 1: Confirm only the two workflow files are staged-able**

```bash
cd /Users/asuka/code/magi
git status --short -- .github/workflows/
```

Expected: two `M` lines, one for `ci.yml`, one for `release.yml`. No other modified workflow.

- [x] **Step 2: Commit**

```bash
git add .github/workflows/ci.yml .github/workflows/release.yml
git commit -m "$(cat <<'EOF'
ci: assert frontend/src/types/api/generated.ts stays in sync with backend

Wires the Phase 0 drift check into both ci.yml (PR-time) and
release.yml (tag-time):

* ci.yml: new top-level job `api-types-drift` sets up Python 3.13 +
  Node 20, installs backend deps, runs scripts/gen-api-types.sh, and
  asserts `git diff --exit-code` on frontend/src/types/api/generated.ts.
* release.yml: the same `Verify generated API types are up to date`
  step is inserted between `Install frontend dependencies` and
  `Run frontend validation`, reusing the workflow's existing
  Python+Node+backend setup.

If a contributor changes a pydantic model on the FastAPI transport
surface but forgets to commit the regenerated generated.ts, both
workflows will fail with a clear error message pointing at the
correct local command.

See docs/api-types-codegen-design.md §4.5 for the design rationale.
EOF
)"
```

- [x] **Step 3: Verify the commit**

```bash
git log --oneline -2
git show --stat HEAD | head -10
```

Expected: latest commit subject `ci: assert frontend/src/types/api/generated.ts stays in sync with backend`, touching exactly `ci.yml` and `release.yml`.

---

## Task 10: Final end-to-end verification

This task confirms the local tree is healthy enough that the next PR-style validation (which is what will run on CI) would pass.

- [x] **Step 1: tsc, build, tests**

```bash
cd /Users/asuka/code/magi/frontend
npm run type-check
npm run test:ci 2>&1 | grep -E "(Test Files|Tests)" | head -3
npm run build 2>&1 | tail -5
```

Expected:
- `type-check`: no error TS lines.
- `test:ci`: `Test Files  88 passed (88)` and `Tests  547 passed (547)` (or higher; never lower).
- `build`: `✓ built in ...`.

- [x] **Step 2: Drift check passes against committed generated.ts**

```bash
cd /Users/asuka/code/magi
bash scripts/gen-api-types.sh
git diff --exit-code -- frontend/src/types/api/generated.ts && echo "OK: generated.ts matches what backend produces right now"
```

Expected: `OK: ...`. Phase 0's central invariant.

- [x] **Step 3: Cargo + gateway sanity (we did not touch Rust, but confirm we did not accidentally regress)**

```bash
cd /Users/asuka/code/magi
cargo test -p magi-gateway 2>&1 | tail -5
```

Expected: `test result: ok. ...` for each test binary; no `FAILED`.

- [x] **Step 4: Status check**

```bash
cd /Users/asuka/code/magi
git status --short
git log --oneline -3
```

Expected:
- `git status --short`: empty (or only files outside Phase 0 scope that pre-existed in your working tree).
- Last two commits are the two we added: `ci: assert frontend/src/types/api/generated.ts stays in sync with backend` and `feat(types): plumb openapi-typescript codegen pipeline (Phase 0)`.

---

## Acceptance criteria for Phase 0 (mirrors spec §7)

After all tasks complete, the following must be true:

- `scripts/gen-api-types.sh` exists, is executable, and produces `frontend/src/types/api/generated.ts` successfully on macOS and on Linux (Linux verified via CI in subsequent PR runs).
- `frontend/src/types/api/generated.ts` is committed and matches the output of a fresh run.
- `frontend/src/types/api/README.md` exists and documents the regenerate command.
- `frontend/package.json` lists `openapi-typescript` in `devDependencies` and `gen:api-types` in `scripts`.
- `.github/workflows/ci.yml` has an `api-types-drift` job; `.github/workflows/release.yml` has an inline drift-check step.
- `npm run type-check`, `npm run test:ci`, `npm run build`: all green at the same or higher counts than the pre-Phase-0 baseline.
- No `frontend/src/api/modules/*.ts` file has been modified (Phase 0 is plumbing only).

After Phase 0 merges, Phase 1 module-migration PRs may proceed (see spec §6 for priority order); each Phase 1 PR is a separate plan written from this one's spec.
