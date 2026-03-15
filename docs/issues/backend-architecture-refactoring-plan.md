# 后端架构改造执行计划

> 目标: 将 `backend/src/magi/` 按 14 层架构重构，使每层职责和边界清晰
> 基于: 目标架构图 + 代码现状分析

---

## 目标分层（自下向上）

```
L1  应用级别组件    日志 | DI容器 | 健康检查 | 连接池 | 调度引擎 | DB初始化
L2  配置           应用配置 | LLM配置 | 插件配置 | 人格配置 | 工具配置 | 记忆配置
L3  消息总线        消费位点 | 异常恢复
L4  插件           工具插件 | 记忆插件 | 传感器插件 | 执行器插件 | 人格插件（仅注册）
L5  LLM运行时      普通聊天 | 流式聊天 | 向量生成 | 文生图 | 文生视频 | 文生音频
L6  记忆组件        工作区记忆 | 事件记忆 | 知识记忆 | 摘要记忆 | 工具记忆 | 偏好记忆
L7  LLM工具        内置工具 | 内置skills | 插件工具 | 三方skills
L8  人格           人格维护 | 状态跃迁 | 行为进化 | 情绪状态 | 成长记忆
L9  传感器 | 执行器  内置传感器 + 插件传感器 | 内置执行器 + 插件执行器（同层并行）
L10 上下文层        prompt组装 | 长上下文压缩 | 场景提示词
L11 Agent运行时     task agent管理 | 路由分发 | function calling
L12 时间线系统      数据展示 | 时间线任务
L13 对外服务        api层（routers + services）
L14 对外连接        WebSocket | HTTP（连接管理，不含业务逻辑）
```

**依赖规则**: 上层可以依赖下层，不可反向。同层模块之间通过接口或消息总线通信。

---

## 执行阶段

### 阶段一：拆分 memory/ 包（影响最大，解耦最关键）

memory/ 目前承载了记忆(L6)、人格(L8)、上下文(L10) 三层职责，是耦合最严重的包。

#### 步骤 1.1：提取人格层 → 新建 `personality/`

**移出的文件**:

| 原路径 | 新路径 | 说明 |
|--------|--------|------|
| `memory/self_memory.py` | `personality/self_memory.py` | 人格统一管理（改名待定） |
| `memory/other_memory.py` | `personality/other_memory.py` | 他人画像 |
| `memory/personality_loader.py` | `personality/loader.py` | 人格配置加载 |
| `memory/emotional_state.py` | `personality/emotional_state.py` | 情绪状态引擎 |
| `memory/behavior_evolution.py` | `personality/behavior_evolution.py` | 行为进化 |
| `memory/growth_memory.py` | `personality/growth_memory.py` | 成长记忆 |
| `memory/adaptive_profile_updater.py` | `personality/adaptive_profile_updater.py` | 画像更新调度 |
| `memory/models.py` 中人格相关模型 | `personality/models.py` | `CorePersonality`, `EmotionalState`, `CognitionProfile` 等 |

**改动范围**:
- 所有 `from ..memory.self_memory import` → `from ..personality.self_memory import`
- `runtime_modules.py` 的 `MemorySystemModule` 中人格初始化逻辑拆出
- `memory/__init__.py` (UnifiedMemoryStore) 移除对人格组件的引用

#### 步骤 1.2：提取上下文层 → 新建 `context/`

**移出的文件**:

| 原路径 | 新路径 | 说明 |
|--------|--------|------|
| `memory/prompt_context_assembler.py` | `context/assembler.py` | prompt 模块化组装 |
| `memory/context_builder.py` | `context/builder.py` | 记忆→场景上下文构建 |
| `memory/prompt_context_schema.py` | `context/schema.py` | 上下文 dataclass 定义 |
| `memory/scenario_prompts.py` | `context/scenario_prompts.py` | 场景提示词存储 |

**改动范围**:
- `agent/task_agents/chat/prompt_service.py` 等引用方更新 import 路径
- `runtime_modules.py` 的 `MemorySystemModule` 中 `ScenarioPromptsStore` 初始化拆出

#### 步骤 1.3：清理 memory/ 为纯记忆层

剩余文件（全部属于 L6 记忆组件）:
```
memory/__init__.py          → UnifiedMemoryStore（仅编排 L0-L5）
memory/l0_working_memory.py → L0 工作区记忆
memory/l1_event_store.py    → L1 事件记忆
memory/l2_*.py              → L2 知识记忆（认知/关系/用户图谱）
memory/l3_*.py              → L3 摘要/嵌入记忆
memory/l4_*.py              → L4 程序性/摘要记忆
memory/l5_capabilities.py   → L5 能力记忆
memory/capability_store.py  → L5 兼容层
memory/event_contracts.py   → 事件→记忆契约
memory/integration.py       → 记忆集成管道
memory/hybrid_retrieval/    → 混合检索
```

`memory/__init__.py` 中的 UnifiedMemoryStore 移除对人格和上下文的依赖，仅保留 L0-L5 存储编排。

---

### 阶段二：拆分 runtime_modules.py

当前 `runtime_modules.py` 的 11 个 Module 需要拆成更细粒度的、与层对齐的 Module。

#### 步骤 2.1：将 DatabaseInitializer 从 MemorySystemModule 移到 CoreDependenciesModule

`DatabaseInitializer` 是应用级别基础设施(L1)，不应在记忆层(L6)初始化。

**改动**: `CoreDependenciesModule.init()` 中执行 `DatabaseInitializer.initialize_all()`。

#### 步骤 2.2：拆分 MemorySystemModule 为 3 个 Module

| 新 Module | 层 | 职责 |
|-----------|---|------|
| `MemoryStoreModule` | L6 | UnifiedMemoryStore 初始化、MemoryIntegration 启动、LLM Usage Store |
| `PersonalityModule` | L8 | SelfMemory、OtherMemory 初始化 |
| `ContextModule` | L10 | ScenarioPromptsStore 初始化、默认 prompt 加载 |

#### 步骤 2.3：拆分 AgentRuntimeCoreModule 为 2-3 个 Module

| 新 Module | 层 | 职责 |
|-----------|---|------|
| `SensorExecutorModule` | L9 | SensorHub + ActionExecutor 初始化 |
| `AgentRuntimeModule` | L11 | TaskAgentManager + RouterAgent + AgentRuntime |

#### 步骤 2.4：TaskAgent 工厂抽出

将 `AgentRuntimeCoreModule` 中内联的 TaskAgent 创建 lambda 移到 `agent/task_agents/` 下的工厂模块：

```python
# agent/task_agents/factory.py
def create_chat_agent(agent_id, *, llm_adapter, llm_pool, ...) -> ChatTaskAgent: ...
def create_task_agent(agent_type, agent_id, *, ...) -> TaskAgentBase: ...
```

`AgentRuntimeModule` 只负责调用工厂，不负责知道每种 Agent 的构造参数。

#### 步骤 2.5：Timeline 业务逻辑回归 timeline/

将 `_build_timeline_handler()`、`_resolve_timeline_contribution()` 从 `runtime_modules.py` 移到 `timeline/handler.py`。

#### 步骤 2.6：辅助函数归位

| 函数 | 目标位置 |
|------|---------|
| `_is_llm_selection_pending()` | `config/` 或 `llm/` |
| `_create_scenario_llm_pool()` | `llm/factory.py` |
| `_create_core_llm_adapter()` | `llm/factory.py` |
| `_get_nested_setting()` | `utils/` |

---

### 阶段三：调度编排分散化

当前 `scheduler/bootstrap.py` 集中注册了 3 类调度任务，需要将注册逻辑分散到各自所属层。

#### 步骤 3.1：定义调度注册接口

```python
# scheduler/contracts.py（已有，扩展）
class ScheduleContributor(Protocol):
    """每层如果需要调度任务，实现此接口"""
    async def register_schedules(self, scheduler: SchedulerService) -> None: ...
    async def unregister_schedules(self, scheduler: SchedulerService) -> None: ...
```

#### 步骤 3.2：各层自行注册

| 调度类型 | 当前位置 | 目标位置 |
|----------|---------|---------|
| `TIMELINE_SENSOR_SYNC` | `scheduler/bootstrap.py` | `timeline/` 层自行向调度引擎注册 |
| `AGENT_TASK` | `scheduler/bootstrap.py` | `agent/` 或 Agent Runtime Module 自行注册 |
| `ACTION_DISPATCH` | `scheduler/bootstrap.py` | 执行器层自行注册 |

#### 步骤 3.3：精简 scheduler/bootstrap.py

`SchedulerBootstrap` 退化为调度引擎初始化 + 收集各层注册的编排器，不再包含 timeline/agent/action 的具体处理逻辑。

---

### 阶段四：对外连接层分离

#### 步骤 4.1：提取 WebSocket 连接管理

当前 WebSocket 逻辑分散在：
- `websocket/` — 事件模型 + server
- `api/websocket/` — router + handlers
- `api/websocket_bridge_lifecycle.py` — 生命周期订阅
- `api/connection_manager.py` — 连接池管理

统一到**对外连接层**概念：WebSocket 的连接管理和协议处理在 L14，业务逻辑（消息转发、事件桥接）通过向下调用 API 层(L13)完成。

**改动**: `websocket_bridge_lifecycle.py` 中的事件订阅只做"从消息总线→WebSocket 推送"的桥接，不包含业务判断。

#### 步骤 4.2：明确 HTTP/WebSocket 只是传输

API 层(L13)的 router 不应感知传输协议。当前 `api/routers/messages.py` 中的 `send_message` 端点既处理 HTTP 请求又触发 WebSocket 推送——推送部分应由连接层通过订阅消息总线自动完成。

---

### 阶段五：补充依赖声明 + 初始化对齐

#### 步骤 5.1：SchedulerModule 补充 plugin 依赖声明

当前 `SchedulerModule` 隐式依赖 `runtime_plugin_system`（调用 `get_sensor_registry()` 等），但 `dependencies` 中未声明。

#### 步骤 5.2：重新排序 Module 初始化

按目标分层重新排列初始化顺序（对应 `build_runtime_modules()` 返回值）：

```
①  CoreDependenciesModule      → L1 应用级别组件（路径 + DB初始化 + 健康检查）
②  ConfigurationModule         → L2 配置
③  MessageBusModule            → L3 消息总线
④  PluginSystemModule          → L4 插件注册
⑤  LLMRuntimeModule            → L5 LLM运行时
⑥  MemoryStoreModule           → L6 记忆组件
⑦  ToolsModule                 → L7 LLM工具
⑧  PersonalityModule           → L8 人格
⑨  SensorExecutorModule        → L9 传感器/执行器
⑩  ContextModule               → L10 上下文层
⑪  AgentRuntimeModule          → L11 Agent运行时
⑫  TimelineModule(新)          → L12 时间线系统（包含调度注册）
⑬  SchedulerModule             → 调度引擎启动 + 收集各层注册
⑭  RuntimeExportsModule        → DI导出
⑮  MaintenanceModule           → L1 维护守护
```

#### 步骤 5.3：消除 bootstrap.py 全局变量冗余

统一使用 DI Container 作为运行时实例的唯一访问路径，移除 `bootstrap.py` 中的 8 个模块级全局变量和 `_sync_globals_from_state()`。各层通过 Container 获取依赖。

---

## 执行顺序建议

| 阶段 | 风险 | 建议顺序 |
|------|------|---------|
| 阶段一 (memory/ 拆分) | 🔴 高：影响面最广，import 链最长 | **最先做**，是后续步骤的前提 |
| 阶段二 (runtime_modules 拆分) | 🟡 中：内部重构，对外接口不变 | 紧跟阶段一 |
| 阶段五 (初始化对齐) | 🟡 中：和阶段二配合 | 与阶段二同步 |
| 阶段三 (调度分散化) | 🟢 低：三条独立路径可逐个迁移 | 阶段二之后 |
| 阶段四 (连接层分离) | 🟢 低：主要是文件移动和 import 调整 | 最后做 |

每个步骤完成后应能独立通过测试，保证可增量交付。

---

## 目标代码包结构

```
backend/src/magi/
├── core/               → L1 应用级别组件 (logger, container, database_initializer, health)
├── config/             → L2 配置
├── events/             → L3 消息总线
├── plugins/            → L4 插件注册
├── llm/                → L5 LLM运行时
├── memory/             → L6 记忆组件（纯 L0-L5 存储）
├── tools/              → L7 LLM工具
│   └── builtin/
│   └── providers/
├── personality/        → L8 人格（新）
├── awareness/          → L9 传感器（已有，合并 sensor_hub）
├── execution/          → L9 执行器（新，从 core/runtime 提取）
├── context/            → L10 上下文层（新）
├── agent/              → L11 Agent运行时
│   └── task_agents/
│   └── execution/
├── timeline/           → L12 时间线系统
├── api/                → L13 对外服务
│   └── routers/
│   └── services/
├── websocket/          → L14 对外连接
├── scheduler/          → L1 调度引擎
├── skills/             → L7 技能（可保持独立或合入 tools/）
├── runtime/            → 启动编排（lifecycle + modules）
├── processing/         → 拆分后合入 personality/ 和 memory/
└── utils/              → 通用工具
```
