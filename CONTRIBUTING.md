# Contributing to Magi

Thanks for contributing.

Magi currently spans two closely related repositories:

- `magi` - the desktop app, backend runtime, frontend, Rust gateway, built-in platform code, and core documentation
- `magi-plugins` - the marketplace registry and most installable external plugins: https://github.com/asukaonly/magi-plugins

If you are not sure where a change belongs:

- runtime, frontend, backend APIs, memory, scheduling, gateway, docs, SDK, and built-in tooling changes belong in this repository
- new marketplace plugins or fixes to an external plugin package usually belong in `magi-plugins`

## Before you start

Before changing architecture, product behavior, runtime boundaries, or plugin contracts, read the relevant root docs in `docs/`:

- `docs/README.md`
- `docs/project-overview.md`
- `docs/product-configuration-guide.md`
- `docs/task-agent-runtime-architecture.md`
- `docs/plugin-extension-architecture.md`
- `docs/plugin-development-guide.md`
- `docs/memory-system-design.md`

If your change affects behavior or ownership described there, update the corresponding doc in the same pull request.

## Local setup

Recommended prerequisites:

- Python 3.10+
- Node.js 22.22.3 and npm 11.16.0 for frontend work
- Rust stable toolchain
- Platform prerequisites required by Tauri if you plan to run or build the desktop app

The frontend is the canonical Node.js package in this repository. Use the version
files under `frontend/` with your preferred version manager, then install with
`npm ci` so `package-lock.json` is not rewritten by local npm resolution.

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
./scripts/install-deps.sh
```

On Windows, use `.venv\Scripts\activate` and `./scripts/install-deps.ps1` instead.

The install script will:

- install frontend dependencies
- install `sdk/` and `backend/` in editable mode
- build the Rust workspace

## Useful commands

```bash
# frontend
cd frontend
npm run type-check
npm run test
npm run lint
npm run tauri:dev

# backend
cd backend
pytest

# repo-level checks
cd ..
python scripts/check-api-contract.py
./scripts/run-backend-type-gate.sh
cargo test -p magi-gateway
```

## Contribution guidelines

- Keep each change atomic and independently verifiable.
- Add or update tests when behavior changes. If automated coverage is not practical, document the validation you performed.
- When adding a backend API route, also register its path + methods in `_PUBLIC_ROUTE_METHODS` (`backend/src/magi/api/routes.py`) — otherwise it returns 404 at runtime despite existing on the router. See `agents.md` → Coding Standards → Adding an API route.
- Keep gateway routes authenticated by default and update the ownership/access manifest for every native route or static mount. Only liveness and bundled avatars may be public; DOM-loaded private resources use scoped short-lived tickets, never the desktop session credential in a URL.
- Treat `_PUBLIC_ROUTE_METHODS` as the Python product-visibility allowlist, not as an unauthenticated gateway allowlist.
- Prefer direct fixes over compatibility shims.
- Use English for commit messages, code comments, docstrings, logs, and error messages.
- Use Conventional Commits for commit subjects.
- Do not mix unrelated changes in the same pull request.
- Avoid refactor-only pull requests unless the refactor is required to ship a concrete fix, feature, or documented cleanup.

## Before you open a pull request

- For larger features, architecture changes, plugin contract changes, or workflow changes, start with an Issue or Discussion first.
- Run the narrowest relevant validation locally before asking for review.
- Update docs in the same pull request when product behavior, setup steps, runtime boundaries, or repository ownership change.
- Keep the pull request focused on one problem or one independently reviewable change.
- For UI changes, include screenshots or a short recording.

## Pull requests

- Branch from `main`.
- Include a concise description of the problem, the approach, and the validation you ran.
- Include screenshots or recordings for UI changes when helpful.
- Link related issues or discussions when relevant.

## Commit message guidelines

Use Conventional Commits:

- `feat`: new user-facing behavior or capability
- `fix`: bug fix or regression repair
- `refactor`: internal restructuring without changing behavior
- `perf`: performance improvement
- `docs`: documentation-only changes
- `test`: tests added or updated
- `chore`: maintenance or tooling work
- `revert`: revert a previous commit

Recommended rules:

- Write the subject in English and imperative mood.
- Keep the subject concise. `type: short summary` is the preferred format.
- Commit one independently reversible task at a time.
- Add a body for non-trivial commits to explain why, scope, and impact.
- Do not include tool or model branding in commit messages.

Examples:

- `feat: add schedule execution history panel`
- `fix: preserve session workspace on rename`
- `docs: clarify plugin repository ownership`

## Plugin contributions

For plugin work, the repository boundary matters:

- built-in repository plugins can live under `plugins/` in this repository
- external plugins for local development usually live under `~/.magi/plugins/<your-plugin>/`
- marketplace-distributed plugins are usually developed in `magi-plugins`

If you are contributing a new external plugin, start with the plugin guide in `docs/plugin-development-guide.md` and then work in the companion repository.
