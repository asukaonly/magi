# Magi

Magi 是一个本地优先（Local-first）的 macOS 桌面 AI Agent。

**当前状态：** Alpha（快速迭代中，接口与行为可能调整）

语言：简体中文 | [English](./README.md)

## 面向用户（macOS）

Magi 以打包好的桌面应用交付。  
普通用户不需要自行安装 Python、Node.js，也不需要源码运行。

### 安装

1. 打开当前仓库的 GitHub Releases。
2. 下载 `Magi-0.1.0-macos.dmg`。
3. 打开 DMG，将 `Magi` 拖入 `Applications`。
4. 在 `Applications` 中启动 `Magi`。

### 首次启动

1. 打开 `Magi`。
2. 完成引导配置（语言、模型/提供商、基础偏好）。
3. 开始在桌面端使用和配置你的 Agent。

### 更新

1. 从 GitHub Releases 下载最新 DMG。
2. 用新版本替换 `Applications` 中已有的 `Magi`。

### 卸载

1. 从 `Applications` 删除 `Magi`。
2. 如需彻底清理，可删除本地数据目录 `~/.magi/`。

### 本地数据目录

Magi 当前将运行数据存放在：

- `~/.magi/`

## 面向贡献者

### 环境要求

- Python 3.10+
- Node.js 18+
- npm
- Rust 工具链（开发 Tauri 桌面端时需要）

### 快速启动（源码开发）

#### 方案 A：Web + Backend 热更新

```bash
./scripts/dev-hot.sh
```

#### 方案 B：Desktop（Tauri）+ Backend 热更新

```bash
./scripts/dev-tauri-hot.sh
```

### 手动启动

#### 后端

```bash
cd backend
pip install -r requirements.txt
python run_server.py
```

#### 前端

```bash
cd frontend
npm install
npm run dev
```

### 验证命令

#### 前端

```bash
cd frontend
npm run type-check
npm run test
npm run lint
```

#### 后端

```bash
cd backend
pytest
```

## 架构总览

Magi 是一个本地优先的 Agent 运行时系统，强调分层与职责边界清晰。

- 运行循环：Sense -> Plan -> Act -> Reflect
- Agent 分层：MasterAgent -> TaskAgent -> WorkerAgent
- 核心任务运行时：
  - `ChatTaskAgent`：用户主入口任务代理
  - `ExploreTaskAgent`：大规模探索任务代理
  - `TaskOrchestrator`：父任务编排
  - `WorkerAgentManager`：叶子 Worker 生命周期管理
- 记忆体系：生命周期模型 `L0` 到 `L4`
- 扩展体系：tools、plugins、skills、sensors/actions
- 运行形态：
  - Web：React 前端 + Python 后端
  - Desktop：Tauri 壳 + React WebView + Python sidecar 后端

## 仓库结构

```text
magi/
├── backend/        # Python 运行时、API、编排、记忆、工具、插件
├── frontend/       # React UI 与 Tauri 桌面宿主
├── docs/           # 架构与产品文档
├── plugins/        # 插件包
├── scripts/        # 开发/构建脚本
└── openspec/       # 规格与计划产物
```

## 文档导航

- [文档索引](./docs/README.md)
- [项目概览](./docs/project-overview.md)
- [产品配置指南](./docs/product-configuration-guide.md)
- [Task-Agent Runtime 架构](./docs/task-agent-runtime-architecture.md)
- [插件扩展架构](./docs/plugin-extension-architecture.md)
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
