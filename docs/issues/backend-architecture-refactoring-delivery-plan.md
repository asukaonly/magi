# 后端架构改造落地清单（执行版）

> 基于文档：`docs/issues/backend-architecture-refactoring-plan.md`
> 目标：把剩余改造任务拆成可独立提交、可独立验证的执行单元，直至完成全部阶段。

---

## 1. 当前完成度快照

### 已基本完成
- 阶段一（`memory/` 拆分到 `memory/ + personality/ + context/`）
- 阶段二中的 2.1 / 2.2 / 2.4 / 2.5
- 阶段五中的 5.1 / 5.3

### 仍需完成
- 阶段二：2.3（拆分 `AgentRuntimeCoreModule`）、2.6（辅助函数归位的剩余项）
- 阶段三：3.1 / 3.2 / 3.3（调度贡献接口与分散注册）
- 阶段四：4.1 / 4.2（连接层与 API 层职责分离）
- 阶段五：5.2（初始化顺序与新模块对齐）

---

## 2. 执行原则

- 每个任务必须独立可回滚、独立可验证、独立提交。
- 任务完成定义：实现完成 + 运行验证 + 文档/注释同步（如有）。
- 提交信息使用 Conventional Commits（英文 subject）。

---

## 3. 任务总览（12 项）

| ID | 任务 | 对应计划章节 | 预期提交 |
|---|---|---|---|
| T01 | 拆分 `AgentRuntimeCoreModule` 为 `SensorExecutorModule` + `AgentRuntimeModule` | 阶段二 2.3 | `refactor(runtime): split sensor executor and agent runtime modules` |
| T02 | 新增 `TimelineModule`，迁移 timeline 调度注册职责 | 阶段二/五 | `refactor(runtime): introduce dedicated timeline module` |
| T03 | 按 15 层顺序重排 `build_runtime_modules()` | 阶段五 5.2 | `refactor(runtime): align module startup order with layered architecture` |
| T04 | 定义 `ScheduleContributor` 协议 | 阶段三 3.1 | `refactor(scheduler): add schedule contributor protocol` |
| T05 | `timeline` 接入 contributor 协议 | 阶段三 3.2 | `refactor(timeline): adopt schedule contributor contract` |
| T06 | 迁移 `AGENT_TASK` 注册到 agent/runtime contributor | 阶段三 3.2 | `refactor(agent): move agent task schedule registration to contributor` |
| T07 | 迁移 `ACTION_DISPATCH` 注册到 execution contributor | 阶段三 3.2 | `refactor(execution): move action dispatch schedule registration to contributor` |
| T08 | 精简 `SchedulerBootstrap` 为编排壳层 | 阶段三 3.3 | `refactor(scheduler): slim bootstrap to orchestration only` |
| T09 | `websocket_bridge_lifecycle` 收敛为纯桥接 | 阶段四 4.1 | `refactor(websocket): keep bridge lifecycle transport-only` |
| T10 | `messages` router 移除 websocket 直推职责 | 阶段四 4.2 | `refactor(api): decouple message router from websocket transport` |
| T11 | 辅助函数归位（`_get_nested_setting` 等） | 阶段二 2.6 | `refactor(utils): relocate shared nested setting and runtime helpers` |
| T12 | 全量回归验证 + 计划文档状态回填 | 收尾 | `docs(architecture): update refactoring progress and completion notes` |

---

## 4. 分任务执行细则

### T01 拆分 AgentRuntimeCoreModule
- 目标：把 L9 与 L11 职责拆开，降低 `runtime_modules.py` 复杂度。
- 主要改动文件：
  - `backend/src/magi/runtime/runtime_modules.py`
- 验证命令：
  - `cd backend && pytest tests/runtime/test_lifecycle_orchestrator.py tests/runtime/test_bootstrap_llm_selection.py`

### T02 新增 TimelineModule
- 目标：timeline 初始化与调度注册从 `SchedulerModule` 脱离为独立层（L12）。
- 主要改动文件：
  - `backend/src/magi/runtime/runtime_modules.py`
  - `backend/src/magi/timeline/scheduler_contrib.py`
- 验证命令：
  - `cd backend && pytest tests/timeline/test_timeline_runtime_bridge.py tests/scheduler/test_scheduler_runtime.py`

### T03 重排 runtime module 启动顺序
- 目标：对齐计划中的 15 步初始化顺序，消除隐式顺序依赖。
- 主要改动文件：
  - `backend/src/magi/runtime/runtime_modules.py`
- 验证命令：
  - `cd backend && pytest tests/runtime/test_lifecycle_orchestrator.py`

### T04 定义 ScheduleContributor 协议
- 目标：为调度任务注册建立统一契约。
- 主要改动文件：
  - `backend/src/magi/scheduler/contracts.py`
- 验证命令：
  - `cd backend && pytest tests/scheduler/test_scheduler_runtime.py`

### T05 timeline 接入 contributor
- 目标：timeline 按统一协议注册/反注册 schedule。
- 主要改动文件：
  - `backend/src/magi/timeline/scheduler_contrib.py`
- 验证命令：
  - `cd backend && pytest tests/timeline/test_timeline_runtime_bridge.py`

### T06 迁移 AGENT_TASK 注册
- 目标：`AGENT_TASK` 从 scheduler bootstrap 迁移到 agent/runtime 层 contributor。
- 主要改动文件：
  - `backend/src/magi/scheduler/bootstrap.py`
  - `backend/src/magi/agent/`（新增或调整 contributor 文件）
- 验证命令：
  - `cd backend && pytest tests/scheduler/test_scheduler_runtime.py tests/api/test_runtime_chat_dispatch.py`

### T07 迁移 ACTION_DISPATCH 注册
- 目标：`ACTION_DISPATCH` 迁移到 execution 层 contributor。
- 主要改动文件：
  - `backend/src/magi/scheduler/bootstrap.py`
  - `backend/src/magi/execution/`（新增 contributor 文件）
- 验证命令：
  - `cd backend && pytest tests/scheduler/test_scheduler_runtime.py`

### T08 精简 SchedulerBootstrap
- 目标：`SchedulerBootstrap` 仅保留“调度引擎初始化 + contributor 编排”。
- 主要改动文件：
  - `backend/src/magi/scheduler/bootstrap.py`
- 验证命令：
  - `cd backend && pytest tests/scheduler/test_scheduler_runtime.py`

### T09 连接层桥接纯化
- 目标：`websocket_bridge_lifecycle` 只保留事件桥接，不包含业务拼装。
- 主要改动文件：
  - `backend/src/magi/api/websocket_bridge_lifecycle.py`
  - `backend/src/magi/websocket/`（必要时新增桥接辅助）
- 验证命令：
  - `cd backend && pytest tests/api/test_backend_app_websocket_bridge.py`

### T10 API 层传输职责纯化
- 目标：`messages` router 只做 HTTP 输入与事件发布，不直接做 websocket 推送。
- 主要改动文件：
  - `backend/src/magi/api/routers/messages.py`
- 验证命令：
  - `cd backend && pytest tests/api/test_runtime_chat_dispatch.py tests/api/test_backend_app_websocket_bridge.py`

### T11 辅助函数归位
- 目标：完成阶段二 2.6 剩余项（`_get_nested_setting` 等归档到合适层）。
- 主要改动文件：
  - `backend/src/magi/timeline/handler.py`
  - `backend/src/magi/utils/`（新增或扩展工具模块）
  - `backend/src/magi/runtime/bootstrap.py`（仅保留代理或移除兼容入口）
- 验证命令：
  - `cd backend && pytest tests/llm/test_scenario_llm_pool.py tests/timeline/test_timeline_runtime_bridge.py`

### T12 收尾回归与文档回填
- 目标：完成全量验证，并将状态同步回主计划文档。
- 主要改动文件：
  - `docs/issues/backend-architecture-refactoring-plan.md`
  - `docs/issues/backend-architecture-refactoring-delivery-plan.md`
- 验证命令：
  - `cd backend && pytest`

---

## 5. 推荐执行批次

### 批次 A（架构主干）
- T01
- T02
- T03

### 批次 B（调度分散化）
- T04
- T05
- T06
- T07
- T08

### 批次 C（连接层与收尾）
- T09
- T10
- T11
- T12

---

## 6. 进度跟踪（执行时更新）

- [ ] T01
- [ ] T02
- [ ] T03
- [ ] T04
- [ ] T05
- [ ] T06
- [ ] T07
- [ ] T08
- [ ] T09
- [ ] T10
- [ ] T11
- [ ] T12

