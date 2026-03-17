# Magi

<p align="center">
  <strong>[ Magi Logo ]</strong>
</p>

<p align="center">
  <a href="https://github.com/asukaonly/magi/blob/main/LICENSE"><img src="https://img.shields.io/github/license/asukaonly/magi" alt="License"></a>
  <a href="https://github.com/asukaonly/magi/releases"><img src="https://img.shields.io/github/v/release/asukaonly/magi" alt="Release"></a>
  <img src="https://img.shields.io/badge/platform-macOS-black?logo=apple" alt="macOS">
  <img src="https://img.shields.io/badge/React-18+-61DAFB?logo=react&logoColor=white" alt="React">
  <img src="https://img.shields.io/badge/Tauri-2.x-24C8DB?logo=tauri&logoColor=white" alt="Tauri">
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white" alt="Python">
</p>

Magi is a local-first desktop AI agent that combines multi-source sensing, layered memory, and personality controls for long-term personal companionship and life recall.

**Status:** Alpha (fast-moving, interfaces and behavior may change)

Language: English | [简体中文](./README.zh-CN.md)

## Why Magi

Magi takes inspiration from the intelligent computer system in *Evangelion*, and can also be read as `My Agent Gets It`.

Most AI products are built around instant answers and short-lived context. Magi is designed differently: as a local desktop agent that can continuously sense, remember, and interact with you over time.

Through extensible sensor plugins, Magi can connect to external personal data sources such as browsing history, screen activity, calendars, social posts, AI conversations, and photo archives, then organize them into a searchable personal timeline and memory system.

At the core is a five-layer memory model: workspace memory, event memory, knowledge memory, summary and reflection memory, and tool skill memory. This structure is meant to improve recall, support long-term understanding, and help turn scattered life fragments into something more coherent and reviewable.

Magi also exposes more detailed personality and emotional controls, so the way it responds can stay consistent with the kind of long-term companion you want to build, not just a generic assistant.

Magi is not trying to be another one-off question answering tool. It is built to be a more personal desktop agent for remembering, organizing, and understanding your life over time.

## Core Highlights

- Multi-source sensing and timeline building through extensible sensor plugins
- A five-layer memory system for better recall, reflection, and personal understanding
- Personality and emotion controls for a more stable long-term companion experience

## For Users (macOS)

Magi is distributed as a packaged desktop app.
You do not need to install Python, Node.js, or run source code.

### Install

1. Open GitHub Releases for this repository.
2. Download `Magi-0.1.0-macos.dmg`.
3. Open the DMG and drag `Magi` into `Applications`.
4. Launch `Magi` from `Applications`.

### Launch and First Run

1. Open `Magi`.
2. Complete onboarding (language, model/provider setup, basic preferences).
3. Start chatting and configuring your agent from the desktop app.

### Update

1. Download the latest DMG from GitHub Releases.
2. Replace the existing app in `Applications`.

### Uninstall

1. Remove `Magi` from `Applications`.
2. Optional: remove local data directory `~/.magi/` if you want a full cleanup.

### Local Data Directory

Magi stores runtime/app data at:

- `~/.magi/`

## For Contributors

### Prerequisites

- Python 3.10+
- Node.js 18+
- npm
- Rust toolchain (required for Tauri desktop development)

### Quick Start (Source Development)

#### Option A: Web + Backend hot reload

```bash
./scripts/dev-hot.sh
```

#### Option B: Desktop (Tauri) + Backend hot reload

```bash
./scripts/dev-tauri-hot.sh
```

### Manual Setup

#### Backend

```bash
cd backend
pip install -r requirements.txt
python run_server.py
```

#### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Validation Commands

#### Frontend

```bash
cd frontend
npm run type-check
npm run test
npm run lint
```

#### Backend

```bash
cd backend
pytest
```

## Architecture At A Glance

Magi is built as a local-first agent runtime with clear layering and ownership boundaries.

- Runtime loop: Sense -> Plan -> Act -> Reflect
- Agent layering: MasterAgent -> TaskAgent -> WorkerAgent
- Core task runtime:
  - `ChatTaskAgent` for user-facing flows
  - `ExploreTaskAgent` for large exploration workflows
  - `TaskOrchestrator` for bounded orchestration
  - `WorkerAgentManager` for leaf worker execution
- Memory model: lifecycle-based `L0` to `L4`
- Extension model: tools, plugins, skills, sensors/actions
- Runtime shapes:
  - Web mode: React frontend + Python backend
  - Desktop mode: Tauri shell + React WebView + Python sidecar backend

## Repository Layout

```text
magi/
├── backend/        # Python runtime, API, orchestration, memory, tools, plugins
├── frontend/       # React UI and Tauri desktop host
├── docs/           # Architecture and product documentation
├── plugins/        # Plugin packages
├── scripts/        # Dev/build helper scripts
└── openspec/       # Specs and planning artifacts
```

## Documentation

- [Documentation Index](./docs/README.md)
- [Project Overview](./docs/project-overview.md)
- [Product Configuration Guide](./docs/product-configuration-guide.md)
- [Task-Agent Runtime Architecture](./docs/task-agent-runtime-architecture.md)
- [Plugin Extension Architecture](./docs/plugin-extension-architecture.md)
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
