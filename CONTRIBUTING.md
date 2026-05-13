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
- Node.js and npm
- Rust stable toolchain
- Platform prerequisites required by Tauri if you plan to run or build the desktop app

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
- Prefer direct fixes over compatibility shims.
- Use English for commit messages, code comments, docstrings, logs, and error messages.
- Use Conventional Commits for commit subjects when possible.
- Do not mix unrelated changes in the same pull request.

## Pull requests

- Branch from `main`.
- Include a concise description of the problem, the approach, and the validation you ran.
- Include screenshots or recordings for UI changes when helpful.
- Link related issues or discussions when relevant.

## Plugin contributions

For plugin work, the repository boundary matters:

- built-in repository plugins can live under `plugins/` in this repository
- external plugins for local development usually live under `~/.magi/plugins/<your-plugin>/`
- marketplace-distributed plugins are usually developed in `magi-plugins`

If you are contributing a new external plugin, start with the plugin guide in `docs/plugin-development-guide.md` and then work in the companion repository.