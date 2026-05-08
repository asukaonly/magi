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

Magi 是一个本地优先的 AI 伴侣。它不只回答当下的问题，也会在你允许的范围内记住对话、整理时间线、回看生活片段，并让这些记忆始终可检查、可修正、可删除。

**当前状态：** Alpha。项目仍在快速迭代，接口和行为可能继续调整。

语言：简体中文 | [English](./README.md)

## 什么是 Magi

magi的设计初衷并不是为了再造一个 Claude Code 或者 OpenClaw。

如果说很多 AI Agent 的核心问题是“怎样更快、更好地完成一项任务”，那么 Magi 更关心另一个问题：在一次次对话、一天天活动和不断变化的生活里，AI 能不能真正观察到“你”？

这里的观察不是监控，也不是把数据堆成报表。Magi 希望在你授权的范围内，把散落在对话、日历、浏览记录、Git 提交、音乐、照片、屏幕使用、终端命令里的生活片段，整理成一条可以回望的时间线，沉淀成可检查、可修正、可删除的长期记忆。

你可以问它：“我上次说想换的那个键盘叫什么来着？”也可以让它帮你回顾最近一周在忙什么、哪些想法反复出现、哪些偏好发生了变化。它回答时不只是凭感觉补全上下文，而是能从记忆和时间线里找回证据。

所以 Magi 更像一个运行在你本地桌面上的 AI 伴侣运行时：它会记得发生过什么，理解事情如何随时间变化，也允许你随时查看、纠正和接管它的判断。任务执行只是其中一部分；更重要的是，它帮助你把那些容易被冲散的日常片段重新梳理成可以理解、可以回忆、也可以继续生长的东西。

`Magi` 这个名字来自《EVA》中的智能电脑系统，也可以理解为 `My Agent Gets It`：不是因为它永远知道答案，而是因为它愿意持续地认识你。

## 你可以用 Magi 做什么

- **回忆那些被你提过的小事**：Magi 会从对话中沉淀人物、偏好、习惯、事实和变化。下次你问“我上次说想换的那个键盘叫什么来着？”，它可以带着记忆证据回答。
- **回看一段时间里的自己**：接入日历、Chrome 历史、Git 提交、音乐播放、照片、屏幕使用、终端命令等数据源后，Magi 能把散落的活动整理成月、周、日、小时尺度的时间线。
- **整理可以继续追问的生活片段**：时间线不是冷冰冰的日志列表。它会把事件、上下文、状态变化和反思放在一起，让你更容易看见最近真正发生了什么。
- **查看和修正 AI 的记忆**：记忆不是隐藏黑盒。你可以查看 Magi 记住了什么，确认正确的事实，修正不准确的推断，也可以删除不想保留的内容。
- **在 Agent 执行时随时接管**：回复过程中可以插话、补充方向、纠正判断，也可以停止当前 run 或把长任务转到后台继续跑。
- **把能力边界交给你扩展**：插件市场、MCP 服务器、Telegram 等外部渠道可以把更多工具、资源和个人数据源接入同一个 Magi。

## 为什么它不只是另一个聊天窗口

- **长期记忆不是短上下文**：Magi 面向事实、偏好、事件片段、跨会话模式和时间变化问题构建召回链路，而不是只依赖当前聊天窗口。
- **时间线不是数据报表**：Magi 会把对话和插件来源的事件组织成可搜索、可回看、可追问的个人时间线，帮助你理解一段时间里的自己。
- **人格不是一层 system prompt**：Magi 维护人格配置、场景化表达、关系深度、状态切换和更深层的行为建模，让互动有持续变化的感觉。
- **执行过程不是黑盒等待**：trace、工具调用、任务状态、权限请求和控制面板会展示 Agent 正在做什么，用户可以随时介入。

## 产品一览

### 带记忆和附件的对话

Chat 工作区支持长对话、本地工作区、受管理附件、回复上下文和工具 trace。更重要的是，它可以在合适的时候带着长期记忆回答，而不是每次都从一片空白开始。

> 截图占位符：这里补一张 Chat 截图或 GIF，展示 Magi 使用记忆证据回答问题，并能看到上下文/工具调用。

### 时间线

Magi 会把聊天和插件来源的事件组织成可搜索时间线，支持月、周、日、小时多种尺度、自然语言查询和上下文抽屉。你可以从一天的碎片回看一周的节奏，也可以从一个事件追到背后的证据。

> 截图占位符：这里补一张 Timeline 截图，展示月/周/日/小时导航和上下文抽屉。

### 记忆工作台

记忆页面展示 L0 工作状态、L1 事件、L2 结构化认知、L3 反思和 L4 程序性技能。你可以检查 AI 记住了什么，也可以修正、驳回或清除不该保留的记忆。

> 截图占位符：这里补一张 Memory Workbench 截图，展示 L1-L4 导航或 L2 知识/状态视图。

### 人格与自然回复节奏

Magi 不只是给模型套一段固定 system prompt。它维护人格档案、对话模式、触发反应、关系深度和动态状态，也能把长回复拆成更自然的多段聊天气泡，让回答更像持续互动，而不是一次性报告。

> 截图占位符：这里补一张 Persona 或 Chat Rhythm 截图，展示人格编辑或自然分段回复。

### 任务与运行控制

Magi 把对话视为可控制的 Agent run。你可以打断当前回复、调整运行方向、处理权限请求、回答 Agent 的追问，或把长任务移动到后台继续执行。

> 截图占位符：这里补一张 Tasks/Control 截图，展示后台任务或活跃运行控制。

### 插件市场与外部能力

插件市场支持安装、更新、启用、禁用和配置官方或外部插件。MCP 服务器和 Telegram 等渠道也可以接入同一个运行时，让 Magi 既能观察更多来源，也能使用更多工具。

> 截图占位符：这里补一张 Plugin Marketplace 截图，展示官方数据源/频道插件。

## 技术与可信度

### Benchmark 信号

Magi 当前的长期记忆与检索 benchmark harness 在 LongMemEval 上达到 **87.2% accuracy**。

| LongMemEval 分类 | Accuracy | 数量 |
| --- | ---: | ---: |
| Overall | 0.8720 | - |
| Multi-session | 0.7444 | 133 |
| Single-session assistant | 1.0000 | 56 |
| Temporal reasoning | 0.8947 | 133 |
| Knowledge update | 0.8974 | 78 |
| Single-session preference | 0.8667 | 30 |
| Single-session user | 0.9429 | 70 |

方法说明：这组数字描述的是当前长期记忆/检索评测链路，不应直接扩展为所有产品界面的整体能力宣称。公开发布前，建议补充模型配置、数据集版本、运行命令和输出 artifact。

> Benchmark artifact 占位符：这里补充可复现的 LongMemEval 输出摘要或结果截图。

### 技术底座

- **本地优先的桌面运行时**：Tauri 应用在本地启动 Rust gateway 和 Python IPC worker，应用与运行数据默认保存在本机。
- **L0-L4 生命周期记忆**：工作上下文、标准化事件、结构化认知、反思摘要和程序性记忆分层保存，又能在检索时协同工作。
- **多模型按场景分工**：规划、核心推理、embedding 等模型可以分别配置，按需平衡速度、质量和成本。
- **权限和安全控制**：工具执行支持权限分级，敏感操作需要确认，代码委派也可以限制路径、commit 和 push 等行为。
- **运行时可观察性**：trace、工具调用、LLM 用量、任务状态和系统指标帮助用户与开发者理解 Agent 的运行状态。

## 安装

Magi 以打包好的桌面应用交付。普通用户不需要安装 Python、Node.js 或 Rust。

1. 打开 [GitHub Releases](https://github.com/asukaonly/magi/releases)。
2. 下载对应平台的最新安装包：
   - macOS Apple Silicon：`Magi_aarch64.dmg`
   - macOS Intel：`Magi_x64.dmg`
   - Windows：`Magi_<version>_x64-setup.exe`
3. 安装并启动 Magi。
4. 完成语言、模型/提供商和基础偏好配置。

### 本地数据目录

Magi 将本地应用/运行数据保存在：

- macOS/Linux：`~/.magi/`
- Windows：`%USERPROFILE%\.magi`

只有在需要彻底清除 Magi 本地数据时，才需要删除这个目录。

## 架构总览

```text
Tauri desktop shell
  -> React WebView
  -> Rust gateway (Axum HTTP/WebSocket、配置 I/O、静态读取)
    -> Python IPC worker (LLM、Agent、记忆、插件、调度器)
      -> ~/.magi 下的本地存储
```

Rust gateway 负责桌面端 API 与 WebSocket。需要模型调用、Agent 执行、记忆检索、插件运行时或调度器的请求，会通过 IPC 分发给 Python sidecar。桌面模式下，FastAPI 只作为 worker 内部的 in-memory ASGI app 使用，不对外暴露 Python HTTP server。

## 面向贡献者

### 环境要求

- Python 3.10+
- Node.js 18+
- npm
- Rust 工具链

### 快速启动

```bash
./scripts/install-deps.sh
./scripts/dev-tauri-hot.sh
```

Windows 下可使用 PowerShell 脚本：

```powershell
./scripts/install-deps.ps1
.\scripts\dev-tauri-hot.ps1
```

### 桌面端 Release 构建

```bash
# 1. 构建 Python sidecar (--onedir mode)
./scripts/build-sidecar.sh

# 2. 构建 Tauri 桌面应用
cd frontend
npm run tauri:build
```

Windows 下构建 sidecar：

```powershell
.\scripts\build-sidecar.ps1
```

### 验证命令

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

## 仓库结构

```text
magi/
├── backend/        # Python 运行时、IPC app、编排、记忆、工具、插件
├── crates/         # Rust gateway crate
├── frontend/       # React UI 与 Tauri 桌面宿主
├── docs/           # 架构与产品文档
├── plugins/        # 内置插件包
├── benchmark/      # LongMemEval 与 benchmark 工具
├── sdk/            # 插件 SDK 包
└── scripts/        # 开发/构建脚本
```

## 文档导航

- [文档索引](./docs/README.md)
- [项目概览](./docs/project-overview.md)
- [产品配置指南](./docs/product-configuration-guide.md)
- [Task-Agent Runtime 架构](./docs/task-agent-runtime-architecture.md)
- [统一插件架构](./docs/plugin-extension-architecture.md)
- [插件开发指南](./docs/plugin-development-guide.md)
- [记忆系统设计](./docs/memory-system-design.md)

## 贡献方式

欢迎提交 Issue 和 Pull Request。

提交前建议：

1. 先与 `docs/` 中架构/产品文档对齐
2. 保持改动原子化、可独立验证
3. 为行为变更补充测试或明确验证证据
4. 使用 Conventional Commits

## 许可证

MIT
