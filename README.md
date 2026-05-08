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

Magi is a local-first AI companion. It does more than answer the question in front of you: with your permission, it remembers conversations, organizes a timeline, helps you revisit fragments of everyday life, and keeps those memories inspectable, correctable, and deletable.

**Status:** Alpha. Magi is moving quickly, and interfaces may still change.

Language: English | [简体中文](./README.zh-CN.md)

## What Is Magi

Magi was not designed to rebuild Claude Code or OpenClaw.

If many AI agents are centered on the question "how can this task be completed faster and better?", Magi cares more about another question: across conversations, daily activity, and the changes that happen over time, can an AI actually observe you?

Observation here does not mean surveillance, and it does not mean turning your life into a dashboard of raw data. Magi aims to take the fragments you authorize from conversations, calendars, browsing history, git commits, music, photos, screen time, terminal commands, and other sources, then organize them into a timeline you can revisit and a long-term memory you can inspect, correct, and delete.

You can ask it, "What was the keyboard I said I wanted to buy last time?" You can also ask it to review what you were busy with this week, which ideas kept coming back, or how a preference changed over time. When it answers, it should not be guessing from vibes. It should be able to recover evidence from memory and timeline context.

So Magi is closer to an AI companion runtime that lives on your local desktop: it remembers what happened, understands how things changed, and lets you inspect, correct, or take over its judgment at any time. Task execution is only one part of it. The deeper goal is helping you turn everyday fragments that would otherwise get washed away into something understandable, memorable, and able to keep growing.

The name `Magi` comes from the intelligent computer system in `EVA`, and can also be read as `My Agent Gets It`: not because it always knows the answer, but because it is willing to keep getting to know you.

## What You Can Do With Magi

- **Recall the small things you mentioned**: Magi can distill people, preferences, habits, facts, and changes from conversations. Next time you ask "what was that keyboard I said I wanted?", it can answer with memory evidence.
- **Look back at yourself over time**: after connecting data sources such as calendars, Chrome history, git commits, music playback, photos, screen time, and terminal commands, Magi can organize scattered activity into month, week, day, and hour timelines.
- **Organize life fragments you can keep asking about**: the timeline is not a cold list of logs. It brings events, context, state changes, and reflections together so it is easier to see what actually happened recently.
- **Inspect and correct AI memory**: memory is not a hidden black box. You can review what Magi remembers, confirm accurate facts, correct bad inferences, and delete things you do not want kept.
- **Take over while an agent run is happening**: you can interrupt a reply, add direction, correct a judgment, stop the active run, or move long work into the background.
- **Expand the boundary yourself**: the plugin marketplace, MCP servers, Telegram, and other external channels can connect more tools, resources, and personal data sources to the same Magi.

## Why It Is Not Just Another Chat Window

- **Long-term memory is not short context**: Magi is built to recall facts, preferences, episodes, cross-session patterns, and temporal changes instead of depending only on the current chat window.
- **A timeline is not a data report**: Magi organizes events from conversations and plugins into a searchable, reviewable, askable personal timeline that helps you understand yourself across time.
- **Personality is not a system prompt wrapper**: Magi maintains personality configuration, scenario-specific expression, relationship depth, state changes, and deeper behavior modeling so interaction can feel continuous.
- **Execution is not a black-box wait**: traces, tool calls, task status, permission prompts, and control surfaces show what the agent is doing and let you step in.

## Product Tour

### Chat With Memory And Attachments

The chat workspace supports long-running conversations, local workspaces, managed attachments, reply context, and tool traces. More importantly, it can answer with long-term memory when that context matters, instead of starting from a blank slate every time.

> Screenshot placeholder: add a chat screenshot or GIF showing a memory-backed answer with visible context/tool evidence.

### Timeline

Magi turns events from conversations and plugins into a searchable timeline with month, week, day, and hour scales, natural-language queries, and context drawers. You can review a week's rhythm from a day's fragments, or trace one event back to its evidence.

> Screenshot placeholder: add a timeline screenshot showing month/week/day/hour navigation and a context drawer.

### Memory Workbench

The memory pages expose L0 working state, L1 events, L2 structured cognition, L3 reflections, and L4 procedural skills. You can inspect what the AI remembers, then correct, reject, or clear memory that should not be kept.

> Screenshot placeholder: add a memory workbench screenshot showing the L1-L4 navigation or L2 knowledge/state view.

### Persona And Natural Reply Rhythm

Magi is not just a model with a fixed system prompt attached. It maintains persona profiles, conversation modes, trigger reactions, relationship depth, and dynamic state. It can also split long replies into more natural chat bubbles, so responses feel more like ongoing interaction than one-off reports.

> Screenshot placeholder: add a persona or chat rhythm screenshot showing persona editing or natural segmented replies.

### Tasks And Run Control

Magi treats conversations as controllable agent runs. You can interrupt a reply, steer the active run, approve permission prompts, ask or answer agent questions, and move long work into the background.

> Screenshot placeholder: add a tasks/control screenshot showing a background task or active run controls.

### Plugin Marketplace And External Capabilities

The plugin marketplace lets users install, update, enable, disable, and configure official or external plugins. MCP servers and channels such as Telegram can also connect to the same runtime, letting Magi observe more sources and use more tools.

> Screenshot placeholder: add a plugin marketplace screenshot showing official source/channel plugins.

## Technical Credibility

### Benchmark Signal

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

### Technical Foundation

- **Local-first desktop runtime**: a Tauri app starts a Rust gateway and Python IPC worker locally, with app/runtime data stored under your local Magi directory.
- **L0-L4 lifecycle memory**: working context, normalized events, structured cognition, reflections, and procedural memory are stored in separate layers that still work together during retrieval.
- **Multi-model division of labor**: planning, core reasoning, embedding, and other model roles can be configured separately to balance speed, quality, and cost.
- **Permission and safety controls**: tool execution supports permission levels, sensitive operations require confirmation, and delegated code work can restrict paths, commits, and pushes.
- **Runtime observability**: traces, tool calls, LLM usage, task status, and system metrics help users and developers understand what the agent is doing.

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
./scripts/install-deps.ps1
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
