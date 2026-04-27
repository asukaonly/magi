<p align="center">
  <img src="./docs/assets/brand/magi-mark.png" alt="Magi" width="96">
</p>

<p align="center">
  <strong style="font-size: 40px;">Magi</strong>
</p>

<p align="center">
  <a href="https://github.com/asukaonly/magi/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-2f3b4d" alt="License"></a>
  <a href="https://github.com/asukaonly/magi/releases"><img src="https://img.shields.io/github/v/release/asukaonly/magi" alt="Release"></a>
  <img src="https://img.shields.io/badge/platform-macOS-black?logo=apple" alt="macOS">
  <img src="https://img.shields.io/badge/platform-Windows-0078D4?logo=windows&logoColor=white" alt="Windows">
  <img src="https://img.shields.io/badge/Tauri-2.x-24C8DB?logo=tauri&logoColor=white" alt="Tauri">
  <img src="https://img.shields.io/badge/Rust-gateway-b7410e?logo=rust&logoColor=white" alt="Rust gateway">
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white" alt="Python">
</p>

Magi is a local-first desktop AI companion runtime with benchmarked long-term memory, personal data plugins, an inspectable agent workflow, and a persistent personality layer.

**Status:** Alpha. Magi is moving quickly, and interfaces may still change.

Language: English | [简体中文](./README.zh-CN.md)

## Why Magi

Most AI products are built around short prompts and disposable context. Magi is built around continuity.

It runs on your desktop, keeps your data local by default, connects to personal data sources through plugins, turns scattered activity into a timeline, and gives the assistant a memory system it can query with evidence instead of guessing from a short chat window.

Magi can also be read as `My Agent Gets It`: a system that remembers what happened, understands how things changed over time, and keeps a consistent personality as it interacts with you.

## Benchmark Signal

Magi's current memory and retrieval benchmark harness reaches **87.2% accuracy** on LongMemEval.

| LongMemEval category | Accuracy | Count |
| --- | ---: | ---: |
| Overall | 0.8720 | - |
| Multi-session | 0.7444 | 133 |
| Single-session assistant | 1.0000 | 56 |
| Temporal reasoning | 0.8947 | 133 |
| Knowledge update | 0.8974 | 78 |
| Single-session preference | 0.8667 | 30 |
| Single-session user | 0.9429 | 70 |

Methodology note: these numbers describe the current long-term memory/retrieval evaluation path, not a broad claim about every product surface. Before using them as a release claim, attach the model configuration, dataset revision, run command, and output artifact.

> Benchmark artifact placeholder: add the reproducible LongMemEval output summary here.

## Core Advantages

- **Benchmarked long-term recall**: Magi is designed to answer questions about facts, preferences, episodes, cross-session patterns, and temporal changes from durable memory.
- **Local-first desktop runtime**: a Tauri app starts a Rust gateway and Python IPC worker locally, with app/runtime data stored under your local Magi directory.
- **Personal data plugins**: optional official plugins can bring in sources such as calendar activity, Chrome history, git activity, music listening, photo metadata, screen time, media playback, Telegram, and terminal history.
- **L0-L4 lifecycle memory**: working context, normalized events, structured cognition, reflections, and procedural memory are separate but connected layers.
- **Inspectable memory workbench**: memory is not a hidden blob. The desktop UI exposes memory events, knowledge graph/state snapshots, reflections, and procedural skills.
- **Persistent personality system**: Magi maintains personality configuration, scenario-specific expression, state changes, and deeper behavior modeling beyond a one-off system prompt.
- **Controllable agent runs**: you can interrupt, steer, stop, or move long-running work into the background instead of waiting on a single blocking completion.
- **Runtime observability**: traces, tool calls, task status, permissions, and control surfaces are visible enough for users and developers to understand what the agent is doing.

## Product Tour

### Chat With Memory And Attachments

The chat workspace supports long-running conversations, local workspaces, managed attachments, reply context, tool traces, and memory-guided recall.

> Screenshot placeholder: add a chat screenshot or GIF showing a memory-backed answer with visible context/tool evidence.

### Timeline

Magi turns events from conversations and plugins into a searchable timeline with multiple time scales, query support, and context inspection.

> Screenshot placeholder: add a timeline screenshot showing month/week/day/hour navigation and a context drawer.

### Memory Workbench

The memory pages expose L0 working state, L1 events, L2 structured cognition, L3 reflections, and L4 procedural skills so long-term memory can be inspected and tuned.

> Screenshot placeholder: add a memory workbench screenshot showing the L1-L4 navigation or L2 knowledge/state view.

### Tasks And Run Control

Magi treats conversations as controllable agent runs. You can interrupt a reply, steer the active run, approve permission prompts, ask/answer agent questions, and move long work into background tasks.

> Screenshot placeholder: add a tasks/control screenshot showing a background task or active run controls.

### Plugin Marketplace

The plugin marketplace lets users install, update, enable, disable, and configure official or external plugins without shipping plugin-specific frontend bundles.

> Screenshot placeholder: add a plugin marketplace screenshot showing official source/channel plugins.

## Install

Magi is distributed as a packaged desktop app. You do not need to install Python, Node.js, or Rust to use a release build.

1. Open [GitHub Releases](https://github.com/asukaonly/magi/releases).
2. Download the latest installer for your platform:
   - macOS Apple Silicon: `Magi_aarch64.dmg`
   - macOS Intel: `Magi_x64.dmg`
   - Windows: `Magi_<version>_x64-setup.exe`
3. Install and launch Magi.
4. Complete onboarding for language, model/provider setup, and basic preferences.

### Local Data Directory

Magi stores local app/runtime data under:

- macOS/Linux: `~/.magi/`
- Windows: `%USERPROFILE%\.magi`

Remove that directory only if you want to fully clear local Magi data.

## Architecture At A Glance

```text
Tauri desktop shell
  -> React WebView
  -> Rust gateway (Axum HTTP/WebSocket, config I/O, static reads)
    -> Python IPC worker (LLM, agents, memory, plugins, scheduler)
      -> local stores under ~/.magi
```

The Rust gateway owns the desktop-facing API and WebSocket surface. Requests that need model calls, agent execution, memory retrieval, plugin runtime, or scheduler work are dispatched to the Python sidecar over IPC. FastAPI is used as an in-memory ASGI app inside the worker, not as a public Python HTTP server in desktop mode.

## For Contributors

### Prerequisites

- Python 3.10+
- Node.js 18+
- npm
- Rust toolchain

### Quick Start

```bash
./scripts/install-deps.sh
./scripts/dev-tauri-hot.sh
```

On Windows, use the PowerShell helpers where applicable:

```powershell
.\scripts\dev-tauri-hot.ps1
```

### Desktop Release Build

```bash
# 1. Build the Python sidecar (--onedir mode)
./scripts/build-sidecar.sh

# 2. Build the Tauri desktop app
cd frontend
npm run tauri:build
```

On Windows, build the sidecar with:

```powershell
.\scripts\build-sidecar.ps1
```

### Validation Commands

```bash
cd frontend
npm run type-check
npm run test
npm run lint
```

```bash
cd backend
pytest
```

## Repository Layout

```text
magi/
├── backend/        # Python runtime, IPC app, orchestration, memory, tools, plugins
├── crates/         # Rust gateway crate
├── frontend/       # React UI and Tauri desktop host
├── docs/           # Architecture and product documentation
├── plugins/        # Built-in plugin packages
├── benchmark/      # LongMemEval and benchmark utilities
├── sdk/            # Plugin SDK package
└── scripts/        # Dev/build helper scripts
```

## Documentation

- [Documentation Index](./docs/README.md)
- [Project Overview](./docs/project-overview.md)
- [Product Configuration Guide](./docs/product-configuration-guide.md)
- [Task-Agent Runtime Architecture](./docs/task-agent-runtime-architecture.md)
- [Unified Plugin Architecture](./docs/plugin-extension-architecture.md)
- [Plugin Development Guide](./docs/plugin-development-guide.md)
- [Memory System Design](./docs/memory-system-design.md)

## Contributing

Issues and Pull Requests are welcome.

Before opening a PR, please:

1. Align changes with architecture/product docs in `docs/`
2. Keep changes atomic and independently verifiable
3. Add tests or explicit validation evidence
4. Follow Conventional Commits

## License

MIT
