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

Magi 是一个本地优先的桌面 AI 伴侣运行时，结合经过 LongMemEval 验证的长期记忆、个人数据插件、可观察的 Agent 工作流，以及可持续演化的人格系统。

**当前状态：** Alpha。项目仍在快速迭代，接口和行为可能继续调整。

语言：简体中文 | [English](./README.md)

## 为什么是 Magi

大多数 AI 产品围绕短 prompt 和一次性上下文构建。Magi 的核心目标是连续性。

它运行在你的桌面上，默认将数据保存在本地，通过插件接入个人数据源，把分散的活动组织成可检索的时间线，并让 AI 能够从有证据的长期记忆中回答，而不是只依赖当前聊天窗口里的短上下文。

`Magi` 这个名字来自《EVA》中的智能电脑系统，也可以理解为 `My Agent Gets It`：它记得发生过什么，理解事情如何随时间变化，并在持续互动中保持稳定的人格表达。

## Benchmark 信号

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

## 核心优势

- **有 benchmark 支撑的长期召回**：Magi 面向事实、偏好、事件片段、跨会话模式和时间变化问题构建记忆检索链路。
- **本地优先的桌面运行时**：Tauri 应用在本地启动 Rust gateway 和 Python IPC worker，应用与运行数据默认保存在本机。
- **个人数据插件生态**：可选官方插件可以接入日历、Chrome 历史、Git 活动、音乐播放、照片元数据、屏幕使用、系统媒体、Telegram、终端历史等来源。
- **L0-L4 生命周期记忆**：工作上下文、标准化事件、结构化认知、反思摘要和程序性记忆分层保存，又能在检索时协同工作。
- **可检查的记忆工作台**：记忆不是隐藏黑盒。桌面端可以查看事件、知识图谱/状态快照、反思和程序性技能。
- **可持续演化的人格系统**：Magi 不只是套一层 system prompt，而是维护人格配置、场景化表达、状态切换和更深层的行为建模。
- **可控制的 Agent run**：你可以在回复过程中打断、补充方向、停止，或把长任务转入后台继续跑。
- **运行时可观察性**：trace、工具调用、任务状态、权限请求和控制面板让用户与开发者都能看见 Agent 正在做什么。

## 产品一览

### 带记忆和附件的对话

Chat 工作区支持长对话、本地工作区、受管理附件、回复上下文、工具 trace，以及由记忆检索辅助的回答。

> 截图占位符：这里补一张 Chat 截图或 GIF，展示 Magi 使用记忆证据回答问题，并能看到上下文/工具调用。

### 时间线

Magi 会把聊天和插件来源的事件组织成可搜索时间线，支持多种时间尺度、查询和上下文抽屉。

> 截图占位符：这里补一张 Timeline 截图，展示月/周/日/小时导航和上下文抽屉。

### 记忆工作台

记忆页面展示 L0 工作状态、L1 事件、L2 结构化认知、L3 反思和 L4 程序性技能，让长期记忆可以被检查和调优。

> 截图占位符：这里补一张 Memory Workbench 截图，展示 L1-L4 导航或 L2 知识/状态视图。

### 任务与运行控制

Magi 把对话视为可控制的 Agent run。你可以打断当前回复、调整运行方向、处理权限请求、回答 Agent 的追问，或把长任务移动到后台。

> 截图占位符：这里补一张 Tasks/Control 截图，展示后台任务或活跃运行控制。

### 插件市场

插件市场支持安装、更新、启用、禁用和配置官方或外部插件，不需要为每个插件单独打包前端页面。

> 截图占位符：这里补一张 Plugin Marketplace 截图，展示官方数据源/频道插件。

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
