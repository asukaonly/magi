# Magi 桌面化迁移方案（Tauri + Python Sidecar）

## 1. 目标与范围

本方案用于将当前 `Python backend + React web` 形态迁移为桌面客户端：

- 桌面壳：Tauri
- 前端：继续使用 React + Vite
- 后端：保留 Python（FastAPI）作为 sidecar 进程

不在本次范围：

- 不迁移后端到 Node/TypeScript
- 不重写业务 API 协议
- 不引入旧逻辑兼容分叉

---

## 2. 当前基线（项目现状）

- Backend：`backend/src/magi`（FastAPI、事件总线、memory/runtime）
- Frontend：`frontend/src`（React 18 + Vite + Axios + socket.io-client）
- 现有接口：HTTP + WebSocket 已稳定可用

迁移核心策略：**保留业务后端，替换运行容器（浏览器 -> Tauri WebView）并由 Tauri 托管 Python 生命周期**。

---

## 3. 目标架构

```text
Tauri App
├── React UI (WebView)
│   ├── axios -> http://127.0.0.1:<port>/api/*
│   └── socket.io -> ws://127.0.0.1:<port>/...
├── Tauri Core (Rust)
│   ├── start_backend (spawn sidecar)
│   ├── health_check (poll /api/health)
│   ├── stop_backend (graceful shutdown)
│   └── provide_runtime_config (baseURL/token/port)
└── Python Sidecar (FastAPI/Uvicorn, bundled binary)
    ├── backend runtime
    └── data/logs in app data directory
```

---

## 4. 分阶段实施计划

## Phase 0：设计冻结与约束确认（0.5 天）

### 任务

1. 冻结 sidecar 模式为唯一桌面运行路径（不做双后端实现）。
2. 冻结本地网络模型：
   - 后端仅监听 `127.0.0.1`
   - 端口可配置（默认 `8000`，冲突自动递增）
3. 定义桌面数据目录（配置、DB、日志）迁移策略。

### 交付物

- 本文档评审通过
- 配置字段清单冻结

---

## Phase 1：PoC 跑通（1-2 天）

## 目标

在开发环境跑通：Tauri 启动 -> 自动拉起 Python -> React 可请求 API。

### 任务

1. 初始化 Tauri（位于 `frontend/src-tauri/`）。
2. 增加 Tauri shell plugin，配置 sidecar 权限。
3. 在 Rust 侧实现命令：
   - `start_backend`
   - `backend_status`
   - `stop_backend`
   - `get_backend_base_url`
4. React 启动流程改造：
   - 启动时先 `invoke("start_backend")`
   - 成功后再初始化 API client

### 验收

1. `npm run tauri:dev` 可进入可聊天状态。
2. 关闭桌面窗口后 Python 子进程退出。

---

## Phase 2：工程化与可用性（3-5 天）

## 目标

将 PoC 变为稳定开发基线，解决日志、端口冲突、错误提示、进程恢复。

### 任务

1. 后端启动入口改造（`backend/run_server.py`）
   - 支持 `MAGI_BACKEND_HOST/MAGI_BACKEND_PORT`
   - 固定 host 为 `127.0.0.1`
   - 暴露就绪日志标识
2. 进程管理增强（Rust）
   - 启动超时
   - 健康检查重试
   - sidecar 崩溃检测与 UI 通知
3. 前端错误体验
   - 启动失败页面（显示 stderr 关键错误）
   - “重试启动”入口
4. 统一 runtime config 通道
   - React 内禁止硬编码 baseURL
   - 统一从 Tauri 命令获取

### 验收

1. 端口被占用时能自动切换并继续启动。
2. sidecar 异常退出时前端可见错误，不出现静默卡死。

---

## Phase 3：打包发布链路（4-7 天）

## 目标

产出可安装包（macOS/Windows），包含 Python sidecar，支持版本升级。

### 任务

1. Python 打包脚本
   - 新增 `scripts/build-sidecar.sh`
   - 新增 `scripts/build-sidecar.ps1`
   - 使用 `pyinstaller` 生成平台二进制
2. Tauri 配置 `externalBin`
   - 将 sidecar 产物按 target triple 命名
3. CI 构建流水线
   - Frontend build
   - Sidecar build
   - `tauri build`
4. 签名与分发
   - macOS 签名/notarization
   - Windows 签名（如有证书）
5. 升级策略
   - 使用 Tauri updater
   - 保证用户数据目录不被覆盖

### 验收

1. 双平台安装包可安装并首次启动成功。
2. 升级后历史会话/记忆数据保留。

---

## Phase 4：安全与生产硬化（2-4 天）

## 目标

确保桌面环境下命令执行面和本地服务面可控。

### 任务

1. Tauri capability 最小权限
   - 只允许 sidecar 指定命令
   - 禁止任意 shell 执行
2. 本地 API 保护
   - 启动时生成一次性 token
   - 前端请求头携带 token（后端校验）
3. 日志脱敏
   - API key、敏感参数写入前过滤
4. 依赖与供应链检查
   - 锁定关键依赖版本
   - 发布前安全扫描

### 验收

1. 未授权本地进程不能直接调用敏感 API。
2. capability 配置审计通过。

---

## 5. 目录与文件改造清单

## 新增

```text
frontend/src-tauri/
├── Cargo.toml
├── tauri.conf.json
├── capabilities/default.json
└── src/
    ├── main.rs
    └── backend_manager.rs

scripts/
├── build-sidecar.sh
└── build-sidecar.ps1

doc/
└── tauri-python-sidecar-migration-plan.md
```

## 重点修改

- `frontend/package.json`
  - 增加 tauri scripts：`tauri:dev` / `tauri:build`
- `frontend/src/main.tsx`
  - 增加 backend 启动初始化流程
- `frontend/src/api/*`
  - baseURL 改为运行时注入
- `backend/run_server.py`
  - 支持桌面 sidecar 环境变量

---

## 6. API 与交互约定

## Tauri Commands（Rust -> Frontend）

1. `start_backend() -> { ok: boolean, baseUrl: string, pid?: number, error?: string }`
2. `backend_status() -> { running: boolean, pid?: number }`
3. `stop_backend() -> { ok: boolean }`
4. `get_backend_base_url() -> { baseUrl: string }`

## 进程状态机

`idle -> starting -> healthy -> stopping -> stopped`

异常分支：

- `starting -> failed`
- `healthy -> crashed`

---

## 7. 配置与环境变量规划

sidecar 启动环境变量：

- `MAGI_BACKEND_HOST=127.0.0.1`
- `MAGI_BACKEND_PORT=<dynamic>`
- `MAGI_APP_DATA_DIR=<tauri app data path>`
- `MAGI_DESKTOP_SESSION_TOKEN=<one-time token>`

前端运行时配置：

- `window.__MAGI_RUNTIME__.apiBaseUrl`
- `window.__MAGI_RUNTIME__.sessionToken`

---

## 8. 测试与验收计划

## 自动化测试

1. Backend
   - 启动参数单元测试（host/port/token）
   - 健康检查回归测试
2. Frontend
   - 启动失败状态组件测试
   - runtime baseURL 注入测试
3. E2E（建议 Playwright）
   - 首次启动 -> 发消息 -> 收回复
   - 杀死 sidecar -> 前端错误提示

## 手工测试矩阵

1. macOS Intel / Apple Silicon
2. Windows 10/11
3. 端口冲突场景
4. 无网络场景（本地仍可启动）
5. 升级保留数据场景

---

## 9. 风险清单与应对

1. **Python 打包体积与依赖复杂**
   - 应对：分平台构建、缓存 wheel、固定 requirements。
2. **端口冲突导致启动失败**
   - 应对：端口探测 + 自动递增 + 回传实际 baseURL。
3. **sidecar 崩溃影响前端体验**
   - 应对：健康轮询 + 崩溃事件 + 一键重启。
4. **权限配置过宽**
   - 应对：capability 白名单 + 发布前审计。
5. **跨平台签名流程复杂**
   - 应对：CI 中分离签名步骤，先内部 unsigned 验收。

---

## 10. 里程碑与时间预估

1. M1（第 1 周）：Phase 1 完成，开发可跑通
2. M2（第 2 周）：Phase 2 完成，团队可稳定联调
3. M3（第 3-4 周）：Phase 3 完成，可产出安装包
4. M4（第 4-5 周）：Phase 4 完成，进入灰度发布

---

## 11. 任务拆分建议（按提交粒度）

1. `chore(desktop): init tauri workspace and shell plugin`
2. `feat(desktop): add backend sidecar lifecycle commands`
3. `refactor(frontend): inject runtime api base url from tauri`
4. `feat(backend): support desktop sidecar startup env`
5. `chore(build): add sidecar build scripts for macOS/windows`
6. `ci(desktop): add tauri multi-platform build pipeline`
7. `feat(security): add desktop session token validation`
8. `test(desktop): add e2e startup and crash-recovery scenarios`

---

## 12. Definition of Done

满足以下条件才算迁移完成：

1. 双平台安装包可启动并完成完整对话链路。
2. 后端 sidecar 生命周期由 Tauri 完整托管，无残留进程。
3. 前端不含硬编码 localhost 地址，全部使用 runtime 注入。
4. 升级不破坏本地数据（会话、记忆、配置）。
5. 安全能力边界可审计（capability 最小化、token 校验生效）。

