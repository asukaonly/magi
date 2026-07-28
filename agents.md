# Magi Agent Handbook

## Scope

This document defines mandatory implementation and delivery rules for coding agents working in this repository.

---

## Quick Rules (Do / Don't)

**Do**
- Align major changes with the active `docs/` architecture and product guides before implementation.
- Keep `docs/` root reserved for long-lived source-of-truth documents only.
- Keep each task atomic and independently verifiable.
- Commit immediately after each completed independent task.
- Use Conventional Commits with clear English subjects.
- Use English for AI-generated comments/docstrings, logs, and error messages.
- Add tests or explicit validation evidence for behavior changes.
- When adding a backend HTTP route, also register its path + methods in `_PUBLIC_ROUTE_METHODS` (`backend/src/magi/api/routes.py`); the public app is built by filtering routers through this allowlist, so an unlisted route returns 404 at runtime even though it exists on the router (see Coding Standards → Adding an API route).

**Don't**
- Don't batch unrelated tasks in one commit.
- Don't include `cursor` / `claude` / `chatgpt` / `copilot` in commit text.
- Don't add AI identity signatures (for example, `Co-authored-by: AI Agent`).
- Don't diverge from the active `docs/` guidance without documenting why and impact.
- Don't commit temporary plans, review scratchpads, or exploratory design notes under `docs/`.
- Don't skip validation for core logic changes.
- Don't treat a router-import unit test as proof a route is reachable — that bypasses the `_build_public_router` allowlist filter; assert through the public router (or hit the live endpoint).
- Don't enforce English-only for UI copy unless explicitly required.
- Never add any compatibility code paths; this project is in active development mode.

---

## 1) Source Of Truth

Before changing architecture, core flows, product behavior, or module boundaries,
start with `docs/README.md`. It is the authoritative index for root-level
documentation:
- Core source-of-truth docs are mandatory first checks for broad changes.
- Scoped architecture references are durable docs for the named subsystem.
- Architecture records preserve lasting decisions and migration rationale.

Only root-level `docs/*.md` files listed in `docs/README.md` should be treated
as repository documentation source-of-truth or durable architecture records.

Temporary material rules:
- Put local scratch plans, implementation checklists, and design spikes under `docs/dev/`.
- `docs/dev/` is local-only and must stay gitignored.
- If a temporary document produces a durable decision, fold that decision back into the relevant root doc and then remove or ignore the temporary copy.

If implementation must deviate from the active documentation, explain in commit body:
1. Why deviation is necessary
2. Scope and impact
3. Follow-up plan

---

## 2) Current Architecture (Quick)

Magi is a local-first AI agent framework with:
- Sense-Plan-Act-Reflect loop
- Task-agent runtime centered on `ChatTaskAgent`, `ExploreTaskAgent`, `TaskOrchestrator`, and `WorkerAgentManager`
- Tool registry + builtin/provider tools + skills integration
- Lifecycle-based memory system (`L0`-`L4`)
- Desktop runtime target: `Tauri + React WebView + Python sidecar backend`

Main code locations:
- Backend core: `backend/src/magi/`
- API layer: `backend/src/magi/api/`
- Frontend app: `frontend/src/`
- Desktop host/runtime: `frontend/src-tauri/`
- Builtin plugins: `plugins/` (currently `core-tools`; `core-actions` is inactive)
- External plugins repo: `github.com/asukaonly/magi-plugins` (marketplace registry + all non-builtin plugins)
- Builtin plugins: `plugins/` (currently `core-tools`; `core-actions` is inactive)
- External plugins repo: `github.com/asukaonly/magi-plugins` (marketplace registry + all non-builtin plugins)

---

## 3) Repository Structure (Current)

```text
magi/
├── backend/
│   ├── src/magi/
│   │   ├── agent/              # Task-agent runtime, orchestration, workers
│   │   ├── api/                # Product-facing routers and services
│   │   ├── awareness/          # Sensors, ingestion, scheduling, event emission
│   │   ├── bootstrap/          # Composition root and lifecycle assembly
│   │   ├── channels/           # External messaging adapters
│   │   ├── chat/               # Chat domain persistence and attachments
│   │   ├── config/             # Config models/loader/introspection
│   │   ├── context/            # Prompt and recall shaping
│   │   ├── core/               # Infrastructure, DI, logging, runtime paths
│   │   ├── events/             # Message bus and event transport
│   │   ├── ipc/                # IPC server, dispatcher, protocol
│   │   ├── llm/                # LLM adapters and provider bridge
│   │   ├── memory/             # Lifecycle-based memory stores and retrieval
│   │   ├── personality/        # Personality state and subjective modeling
│   │   ├── plugins/            # Plugin discovery and registration
│   │   ├── runtime_trace/      # Execution observability persistence
│   │   ├── scheduler/          # Persistent scheduler and target dispatch
│   │   ├── skills/             # Skill loading/index/execution
│   │   ├── tasks/              # User-facing task tracking
│   │   ├── timeline/           # Timeline domain and sync workflows
│   │   ├── tools/              # Tool registry and builtin/providers
│   │   └── transport/          # IPC transport app wiring and middleware
│   ├── tests/                  # Backend tests
│   ├── configs/                # Runtime/provider configs
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── api/                # Axios client + API modules
│   │   ├── components/         # UI and feature components
│   │   ├── components/ui/      # shadcn/radix-style primitives
│   │   ├── components/onboarding/
│   │   ├── components/config-forms/
│   │   ├── i18n/               # i18next setup + locale resources
│   │   ├── pages/              # Route pages
│   │   ├── router/             # Route config
│   │   ├── stores/             # Zustand stores
│   │   ├── hooks/              # Custom hooks
│   │   ├── __tests__/          # Frontend tests
│   │   └── main.tsx
│   ├── src-tauri/              # Tauri desktop host (Rust + capabilities + sidecar wiring)
│   ├── package.json
│   └── vite.config.ts
├── scripts/
│   ├── build-sidecar.sh        # Build Python sidecar binary for macOS/Linux
│   ├── build-sidecar.ps1       # Build Python sidecar binary for Windows
│   └── dev-tauri-hot.sh        # Start Tauri + backend with hot reload
├── plugins/
│   ├── core-tools/              # Builtin tools plugin (web search, file ops, etc.)
│   └── core-actions/             # Legacy inactive directory
├── plugins/
│   ├── core-tools/              # Builtin tools plugin (web search, file ops, etc.)
│   └── core-actions/             # Legacy inactive directory
├── configs/
├── docs/
│   ├── project-overview.md
│   ├── product-configuration-guide.md
│   └── task-agent-runtime-architecture.md
├── README.md
└── agents.md
```

### External Plugin Repository

```text
magi-plugins/                     # github.com/asukaonly/magi-plugins
├── registry.json                  # Marketplace index (plugin_id, version, path, platforms)
├── calendar/                      # macOS calendar sensor
├── chrome-history/                # Chrome browsing history sensor
├── git-activity/                  # Git commit history sensor
├── netease-music/                 # NetEase Cloud Music play history sensor
├── photo-library/                 # Photo library EXIF sensor
├── screen-time/                   # macOS app usage sensor
├── system-media/                  # Cross-platform media playback sensor
├── telegram/                      # Telegram bot channel adapter
└── terminal-history/              # Terminal command history sensor
```

### External Plugin Repository

```text
magi-plugins/                     # github.com/asukaonly/magi-plugins
├── registry.json                  # Marketplace index (plugin_id, version, path, platforms)
├── calendar/                      # macOS calendar sensor
├── chrome-history/                # Chrome browsing history sensor
├── git-activity/                  # Git commit history sensor
├── netease-music/                 # NetEase Cloud Music play history sensor
├── photo-library/                 # Photo library EXIF sensor
├── screen-time/                   # macOS app usage sensor
├── system-media/                  # Cross-platform media playback sensor
├── telegram/                      # Telegram bot channel adapter
└── terminal-history/              # Terminal command history sensor
```

---

## 4) Tech Stack (Current)

### Backend
- Python 3.10+
- FastAPI + Pydantic v2 + Uvicorn
- Structlog
- aiosqlite / redis / chromadb / networkx
- OpenAI + Anthropic SDKs
- Socket.IO + aiohttp
- PyInstaller --onedir (desktop sidecar packaging)

### Frontend
- React 18 + TypeScript + Vite
- TailwindCSS
- Radix UI primitives + shadcn-style components
- React Router 6
- Zustand
- TanStack Query
- React Hook Form + Zod
- i18next + react-i18next
- Vitest + Testing Library
- Framer Motion (where needed for interaction/transition)

### Desktop Runtime
- Tauri v2 (Rust host)
- `@tauri-apps/api`
- Python backend as sidecar process (PyInstaller --onedir, bundled via Tauri resources) with runtime token handshake

---

## 5) Coding Standards

### Python
- Naming:
  - Classes: `PascalCase`
  - Functions/variables: `snake_case`
  - Constants: `UPPER_SNAKE_CASE`
- Public methods must include type hints.
- I/O should be async (`async/await`).
- Use specific exceptions and structured logging (`structlog`).
- Prefer Google-style docstrings for non-trivial public APIs.
- AI-generated comments/docstrings/log/error text must be English.

### Adding an API route
Declaring a route on its `APIRouter` is NOT enough to make it reachable. Required steps:
1. **Declare** it: `@some_router.<method>("/path", ...)`.
2. **Allowlist** it: add `"/path": {"<METHOD>"}` under the router's group in `_PUBLIC_ROUTE_METHODS` (`backend/src/magi/api/routes.py`). `register_api_routes()` filters every router through `_build_public_router`, so a route missing from the allowlist is silently dropped → **HTTP 404 in the running app** (router-import unit tests still pass — they bypass the filter). Use the router-relative path (no `/api/<group>` prefix; the prefix is added when the filtered router is mounted).
3. **Gateway**: the Rust gateway (`crates/magi-gateway`) proxies all non-native paths to Python via `.fallback(proxy_handler)` — no gateway change needed for proxied routes. Only add `.route(...)` in `crates/magi-gateway/src/api/mod.rs` if the endpoint is implemented natively in Rust.
4. **Types**: if the request/response schema changed, update the hand-written client types under `frontend/src/api/` and cover the contract with focused backend/frontend tests.
5. **Reload**: the backend runs as a `--no-reload` IPC sidecar — fully relaunch the app (not webview reload) to pick up route/code changes.

Prove reachability through the public router, not just the raw router:

```python
from magi.api.routers.plugins import plugins_router
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router

public = _build_public_router(plugins_router, _PUBLIC_ROUTE_METHODS["plugins"])
assert "/install/upload/inspect" in {r.path for r in public.routes}
```

### TypeScript / React
- Naming:
  - Components/types/interfaces: `PascalCase`
  - Functions/variables: `camelCase`
  - Constants: `UPPER_SNAKE_CASE`
- Prefer functional components + hooks.
- Keep component logic clear and composable.
- AI-generated comments/log/error text must be English.
- UI copy language is product-driven and may be non-English.

### Frontend i18n (Mandatory for UI text)
- New user-facing copy must use i18n keys (`t(...)`), not hardcoded strings.
- Keep locale files under `frontend/src/i18n/locales/<lang>/`.
- Keep `zh-CN` and `en` keys aligned.
- On language change, keep both in sync:
  - `localStorage.magi_language`
  - `document.documentElement.lang`
- Verify no mixed-language leakage on key pages after related changes.

---

## 6) Task Execution Rules (Mandatory)

A task is the smallest independently verifiable and reversible change unit.

A task is complete only when all are done:
1. Implementation finished
2. Validation completed (tests or explicit verification)
3. Related docs/comments updated when needed

Rules:
- Do not mix unrelated tasks in one commit.
- Keep changes atomic and traceable.

### Documentation Update Rules

- When code changes alter product behavior, architecture ownership, runtime boundaries, or operator workflows, update the relevant root `docs/*.md` file in the same task when practical.
- Prefer updating an existing root doc over creating a new root-level document.
- New root-level docs require a durable cross-team purpose, not a one-off implementation need.
- If a root doc becomes obsolete, merge any still-valid guidance into surviving docs before deleting or archiving it.
- Do not leave root docs pointing at deleted files, renamed modules, or temporary execution plans.

---

## 7) Testing & Validation

Minimum expectation per task:
- Add/update tests for changed behavior, or
- Provide explicit verification steps when automated tests are unavailable.

Useful commands:

```bash
# frontend
cd frontend
npm run type-check
npm run test
npm run lint
npm run tauri:dev
npm run tauri:build

# backend
cd backend
pytest

# sidecar build (must run before tauri:build)
./scripts/build-sidecar.sh

# tauri desktop + backend hot reload
./scripts/dev-tauri-hot.sh
```

Backend test naming convention:
- File: `test_<module_name>.py`
- Class: `Test<ClassName>`
- Method: `test_<scenario>`
- Place tests under the matching package area in `backend/tests/` (for example: API routes in `backend/tests/api/`, tools in `backend/tests/tools/`, memory logic in `backend/tests/memory/`).
- Avoid adding new backend test files directly under `backend/tests/` root unless they are true cross-package integration tests and no package-specific folder fits.

---

## 8) Git Commit Policy (Mandatory)

### Commit Frequency
- Every completed independent task must be committed immediately.
- Do not batch unrelated tasks.

### Commit Format
Use Conventional Commits:

```text
<type>: <subject>

<body>

<footer>
```

Recommended types: `feat`, `fix`, `refactor`, `perf`, `docs`, `test`, `chore`, `revert`

### Commit Quality Rules
- Subject must be concise, in English (recommended <= 50 chars).
- For non-trivial changes, body should explain why/scope/impact.
- Keep each commit atomic.

### Prohibited Content
Commit subject/body/footer must not contain agent/model/tool branding:
- `cursor`, `claude`, `chatgpt`, `copilot`
- `ai-generated`, `generated by ai`
- Any model/assistant branding

Also prohibited:
- `Co-authored-by: Cursor`
- `Co-authored-by: Claude`
- `Co-authored-by: AI Agent`

---

## 9) Development Workflow

1. Review the relevant document in `docs/`
2. Implement code changes
3. Validate (tests or explicit verification)
4. Commit immediately for the completed task
5. Push only when requested

Example:

```bash
git add .
git commit -m "fix: handle timeout in worker execution"
git push
```

### Releasing a version

Use the automated script — do **not** hand-edit version files or create tags manually:

```bash
scripts/bump-release.sh <major|minor|patch>   # e.g. patch: 0.1.14 -> 0.1.15
```

It reads the current version from `VERSION`, bumps the requested part, syncs **all**
metadata via `scripts/release-version.py sync` (VERSION, Cargo.lock, frontend
`package.json`/lock, `tauri.conf.json`, `src-tauri/Cargo.toml`, `backend/pyproject.toml`),
runs an environment-independent sanity check, pushes the branch, then **gates on the
remote `ci.yml` run** (`gh run watch`) and only creates + pushes the `v<version>` tag
once CI is green. The tag triggers `release.yml` (desktop bundle builds).

Remote CI is the source of truth because it installs the supported dependency
versions from a clean environment and runs the complete cross-platform validation;
a long-lived local environment may lag those versions. Requires: clean working
tree, a checked-out branch, and authenticated `gh`.

---

## 10) Branching

- `main`: stable branch
- `feature/*`: new features
- `fix/*`: bug fixes
- `refactor/*`: refactors

---

## 11) Review Checklist

- [ ] `docs/` alignment verified (or deviation documented)
- [ ] Code follows naming/type/async conventions
- [ ] Validation completed (tests or explicit checks)
- [ ] Task is atomic and independently reversible
- [ ] Commit message follows policy
- [ ] Commit message contains no agent/model identity markers

---

## 12) References

- [PEP 8](https://pep8.org/)
- [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)
- [Python Typing](https://docs.python.org/3/library/typing.html)
- [Python AsyncIO](https://docs.python.org/3/library/asyncio.html)
- [FastAPI](https://fastapi.tiangolo.com/)
- [Pydantic](https://docs.pydantic.dev/)
- [Structlog](https://www.structlog.org/)
- [React TypeScript Cheatsheet](https://react-typescript-cheatsheet.netlify.app/)
- [Vite Guide](https://vitejs.dev/guide/)

---

**Last Updated**: 2026-03-03  
**Maintainer**: Magi Development Team
