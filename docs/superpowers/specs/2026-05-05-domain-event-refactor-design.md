# 领域事件化重构与 L4 数据落地设计

日期：2026-05-05
作者：asuka

## 1. 背景

`/api/memory/procedures` 永远返回 0。排查后定位：

- `procedural_skills` / `l4_execution_traces` 在数据库中均为 0 行。
- L1 的 `fact_events` 表里只有 `SENSOR_EVENT / AIResponse / UserMessage / APP_USAGE_HOURLY`，**完全没有 `ActionExecuted / TaskCompleted / TaskFailed`**。
- L4 写入分支（`memory/store_ingestion.py:123`）的触发条件是 `event_type == ACTION_EXECUTED`，但全代码库没有任何业务模块发出这种事件。
- 工具实际执行点（`agent/execution/function_calling/step_executor.py`、`agent/task_orchestration_workers.py`、`agent/task_agents/chat/planning_service.py`）只把结果写入 `runtime_trace.db`，从未生成 `MemoryEvent`。

根因不是"忘了 emit 一个事件"，而是 **"工具执行 / 任务生命周期"** 这类领域行为没有作为领域事件被建模——observability（runtime_trace）和领域事件混线，业务模块（chat projector / awareness）则直接调用 memory 的 `ingest_event`，把 memory 系统耦合在了主链路上。

本次改造将引入显式的领域事件层，让 memory 子系统从"被调用方"变为"订阅方"，并顺便补上 L4 的周期维护任务。

## 2. 目标 / 非目标

### 目标

1. 工具执行、任务生命周期产生的领域行为必须以**强类型领域事件**形态在系统总线上流通。
2. memory 子系统所有写入路径都通过订阅领域事件触发，不再被业务模块主动调用。
3. L4 写入链路打通，`procedural_skills` / `l4_execution_traces` / `l4_skills_fts` 在工具执行时正常增长。
4. observability（runtime_trace）与 memory 同源，但通过独立订阅者落地，互不耦合。
5. L4 具备最小可用的周期性维护：断路器衰减、pending_trace 健康检查、FTS 一致性、零活跃 skill 清理。

### 非目标

- 不重写现有 `MemoryEvent` 结构（继续作为 memory 子系统的内部 DTO）。
- 不替换现有 `MessageBusBackend` / `InMemoryMessageBusBackend` 实现，继续复用。
- 不动 task agent 内部的 message bus（用于 UI 渲染等细粒度 payload 通信）；只把 task 生命周期事件提级到主总线。
- 不做跨进程持久化的 EventBus 升级（继续 in-memory）。
- 不重新设计 L4 的存储 schema（沿用现表）。

## 3. 整体架构

```
┌─────────────────── Producer 侧 ─────────────────────────┐
│ ToolInvocationService.invoke(call, ctx)                  │
│   - 包裹 _tool_registry.execute()                        │
│   - 完成后 publish ToolInvocationCompleted               │
│ TaskOrchestrator                                         │
│   - publish TaskStarted / TaskCompleted / TaskFailed     │
│ chat/projector  -> publish UserMessageReceived /         │
│                                AssistantResponseProduced │
│ awareness/ingestion_gateway -> publish SensorEventEmitted│
└──────────────────────┬──────────────────────────────────┘
                       │  Event(type=..., payload=<强类型 dataclass>)
                       ▼
┌─────────── EventBus（现有 InMemoryMessageBusBackend）────┐
└──┬──────────┬──────────┬──────────┬──────────┬──────────┘
   ▼          ▼          ▼          ▼          ▼
 Memory    Runtime    Metrics/   Awareness   未来订阅者
 Ingestion Trace      Usage      Behavior
 Subscriber Subscriber

Memory Ingestion Subscriber
  └─► 翻译为 MemoryEvent
      └─► UnifiedMemoryStore.ingest_event(memory_event)
            └─► 遍历 layers; layer.accepts(memory_event) 才 dispatch
                 ├─ L0  (working memory)
                 ├─ L1  (events)
                 ├─ L2  (semantic / pipeline)
                 ├─ L3  (summaries)
                 └─ L4  (procedural skills)        ← accepts ActionExecuted / TaskCompleted / TaskFailed
```

核心分层：
- **领域事件**（`Event` + 强类型 payload）：描述"世界上发生了什么"，由领域服务发布。
- **MemoryEvent**：记忆系统的内部 DTO，由 `MemoryIngestionSubscriber` 在订阅时翻译产生，承载 ingest_target / cognition_eligible / retention_class 等记忆专属字段。
- **runtime_trace**：observability 关切，作为另一个独立订阅者，与 memory 平级。

## 4. 领域事件契约

新建 `magi/events/domain_payloads.py`，全部使用 `dataclass(frozen=True)`：

### 4.1 ToolInvocationCompleted

```python
@dataclass(frozen=True)
class ToolError:
    type: str             # 异常类型名 / 业务错误码
    message: str
    truncated: bool = False

@dataclass(frozen=True)
class TaskContext:
    session_id: str | None
    turn_id: str | None
    task_id: str | None
    user_id: str | None

@dataclass(frozen=True)
class ToolInvocationCompleted:
    tool_name: str
    tool_category: str        # "external_tool" / "internal" / "mcp" / ...
    success: bool
    duration_ms: float
    started_at: float         # epoch seconds
    finished_at: float
    args_summary: str | None  # 截断到 ~500 字符
    result_summary: str | None
    error: ToolError | None
    context: TaskContext
    correlation_id: str       # 用于跨订阅者关联（runtime_trace ↔ memory）
```

### 4.2 Task 生命周期

```python
@dataclass(frozen=True)
class TaskStarted:
    task_id: str
    task_type: str
    started_at: float
    context: TaskContext
    correlation_id: str

@dataclass(frozen=True)
class TaskCompleted:
    task_id: str
    task_type: str
    started_at: float
    finished_at: float
    summary: str | None
    context: TaskContext
    correlation_id: str

@dataclass(frozen=True)
class TaskFailed:
    task_id: str
    task_type: str
    started_at: float
    finished_at: float
    error: ToolError
    context: TaskContext
    correlation_id: str
```

### 4.3 chat / awareness 事件

```python
@dataclass(frozen=True)
class UserMessageReceived:
    content: str
    context: TaskContext
    metadata: Mapping[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class AssistantResponseProduced:
    content: str
    context: TaskContext
    metadata: Mapping[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class SensorEventEmitted:
    sensor_name: str
    payload: Mapping[str, Any]
    context: TaskContext
```

### 4.4 总线接入

- `magi/events/events.py` 的 `EventTypes` 增加常量：
  - `TOOL_INVOCATION_COMPLETED = "ToolInvocationCompleted"`
  - `TASK_STARTED = "TaskStarted"` （`TASK_COMPLETED` / `TASK_FAILED` 已存在）
  - `USER_MESSAGE_RECEIVED = "UserMessageReceived"` （`USER_MESSAGE` 仍保留以兼容老消息直到迁移完成）
  - `ASSISTANT_RESPONSE_PRODUCED = "AssistantResponseProduced"`
  - `SENSOR_EVENT_EMITTED = "SensorEventEmitted"`
- 发布形态：`Event(type=EventTypes.TOOL_INVOCATION_COMPLETED, payload=<对应 dataclass>)`。`payload` 字段类型在 `Event` 上仍是 `Any`（避免改 `Event` 类影响所有订阅者），但通过约定保证。
- 提供帮手 `magi/events/payload_helpers.py::expect_payload(event, cls) -> cls`：isinstance 检查 + 错误日志。

## 5. ToolInvocationService（工具执行收口）

新建 `magi/agent/execution/tool_invocation_service.py`：

```python
class ToolInvocationService:
    def __init__(self, tool_registry, event_bus):
        self._tool_registry = tool_registry
        self._event_bus = event_bus

    async def invoke(self, call: ToolCall, ctx: InvocationContext) -> ToolCallResult:
        correlation_id = str(uuid.uuid4())
        started_at = time.time()
        started_mono = time.monotonic()
        success, error_obj, result = False, None, None
        try:
            result = await self._tool_registry.execute(call.name, call.args, ctx)
            success = result.is_success
            if not success:
                error_obj = ToolError(type="ToolFailure", message=result.error_summary())
            return result
        except Exception as exc:
            error_obj = ToolError(type=type(exc).__name__, message=str(exc)[:1000])
            raise
        finally:
            finished_at = time.time()
            duration_ms = (time.monotonic() - started_mono) * 1000
            try:
                await self._event_bus.publish(Event(
                    type=EventTypes.TOOL_INVOCATION_COMPLETED,
                    payload=ToolInvocationCompleted(
                        tool_name=call.name,
                        tool_category=ctx.tool_category,
                        success=success,
                        duration_ms=duration_ms,
                        started_at=started_at,
                        finished_at=finished_at,
                        args_summary=summarize(call.args),
                        result_summary=summarize(result) if result else None,
                        error=error_obj,
                        context=ctx.task_context,
                        correlation_id=correlation_id,
                    ),
                ))
            except Exception:
                logger.exception("publish ToolInvocationCompleted failed")
```

改造点：

- `agent/execution/function_calling/step_executor.py:141` `_driver._execute_tool_call` → 改为通过 `ToolInvocationService.invoke`
- `agent/task_orchestration_workers.py:66, 133` → 同上
- `agent/task_agents/chat/planning_service.py:320` → 同上

`_tool_registry.execute()` 不再被业务层直接调用（标记为内部 API，加 lint 提示）。

## 6. Task 生命周期事件

- `agent/task_orchestration_workers.py`：在 task 启动节点 publish `TaskStarted`，在终态节点（成功/失败）publish `TaskCompleted` / `TaskFailed`。
- `agent/task_agents/explore/postprocess_service.py`、`agent/task_agents/chat/...`：业务模块原本通过 `ExploreTaskCompletedPayload` 等内部消息走 task agent 自己的 message bus，**保留**这部分（用于 UI 渲染）；新增主总线事件 publish。
- 内部 message bus 与主总线职责区分：
  - 内部 message bus：UI 渲染、task-agent 间细粒度协作 payload。
  - 主总线：领域事实，下游订阅者（memory / runtime_trace / metrics / behavior）。

## 7. 订阅者侧

### 7.1 MemoryIngestionSubscriber

新建 `magi/memory/subscribers/memory_ingestion_subscriber.py`。

启动时向 EventBus 订阅以下事件类型：
- `ToolInvocationCompleted`
- `TaskStarted`、`TaskCompleted`、`TaskFailed`
- `UserMessageReceived`、`AssistantResponseProduced`
- `SensorEventEmitted`

每条事件经显式翻译函数（`translate_tool_invocation_completed(event)` 等）变为 `MemoryEvent`，再调 `unified_memory.ingest_event(memory_event)`。翻译函数集中在 `magi/memory/event_contracts.py`，与现有 MemoryEvent 构造器同位置。

业务模块改造：
- `chat/projector.py:95` 删除 `ingest_event` 直调，改为 `event_bus.publish(Event(type=USER_MESSAGE_RECEIVED, payload=...))`。
- `awareness/ingestion_gateway.py:97` 同上，改 publish `SensorEventEmitted`。
- 短期内 `EventTypes.USER_MESSAGE` / `AI_RESPONSE` / `SENSOR_EVENT` 保持可用以避免破坏现有订阅者；MemoryIngestionSubscriber 同时订阅老类型与新类型，迁移完成后再清理。

### 7.2 RuntimeTraceSubscriber

新建 `magi/runtime_trace/subscribers/runtime_trace_subscriber.py`。

订阅 `ToolInvocationCompleted` / `TaskStarted` / `TaskCompleted` / `TaskFailed`，把现在分散在 `agent/execution/function_calling/tracing.py`、`step_executor`、orchestrator 里直接写 `runtime_trace.db` 的代码迁过来。`runtime_trace.db` 的 schema 不变；变的是写入触发方式。

通过 `correlation_id` 字段把同一次工具调用在 memory 与 runtime_trace 中关联起来。

## 8. UnifiedMemoryStore + Layer 自声明

### 8.1 接口

```python
class MemoryLayer(Protocol):
    layer_name: str
    accepts_event_types: frozenset[str]   # 静态声明（用于快速短路）
    def accepts(self, event: MemoryEvent) -> bool: ...   # 动态精筛
    async def ingest(self, event: MemoryEvent) -> LayerIngestResult: ...
```

### 8.2 store_ingestion.py 重写

去掉现 100~140 行的 `if` 链，改为：

```python
async def ingest_event(self, event_or_dict) -> dict:
    memory_event = normalize(event_or_dict)
    stored_event_id = await persist_fact_event(memory_event)
    memory_event.event_id = stored_event_id
    results = {}
    for layer in self._layers_in_order:
        if memory_event.event_type not in layer.accepts_event_types:
            continue
        if not layer.accepts(memory_event):
            continue
        try:
            results[layer.layer_name] = await layer.ingest(memory_event)
        except Exception:
            logger.exception("layer %s ingest failed", layer.layer_name)
            # 失败隔离：不阻塞其它 layer
    return summarize(results)
```

### 8.3 各 layer 的 accepts

- L0：`{USER_MESSAGE, USER_MESSAGE_RECEIVED, AI_RESPONSE, ASSISTANT_RESPONSE_PRODUCED, ACTION_EXECUTED, ...}`（按现有逻辑迁移）
- L1：所有"事实型"事件（保留现有判定）
- L2：原 `cognition_eligible` 判定下沉到 `L2.accepts(event) = event.cognition_eligible and (l1_written or no L1)`；通过 `LayerIngestResult.markers` 在 fan-out 上下文中传递 `l1_written` 标记给后续 layer
- L3：现在通过 schedule 触发，accepts 返回 False（保持 schedule 路径不变）
- L4：`accepts_event_types = {ACTION_EXECUTED, TASK_COMPLETED, TASK_FAILED}`，`accepts()` 进一步要求 L1 已写入或事件类型为 ACTION_EXECUTED

### 8.4 跨层依赖

- 通过 `_layers_in_order = [L0, L1, L2, L3, L4]` 显式声明顺序。
- 上一个 layer 的 `LayerIngestResult` 通过 fan-out context 传给后续 layer 的 accepts。

## 9. L4 maintenance schedule

新建 `magi/memory/l4/maintenance_schedule.py`，仿照 `magi/memory/l3/summary_schedule.py`：

### 9.1 周期任务

| 任务 | 频率 | 行为 |
|------|------|------|
| 断路器衰减 | 5 min | 扫 `procedural_skills`，open 状态超过 `breaker_open_timeout_seconds` → half_open；half_open 状态超过 N 分钟无新事件 → closed |
| pending_trace 健康检查 | 15 min | `pending_trace_count > _ADAPTIVE_MAX_THRESHOLD * 2` 强制触发一次 `_maybe_extract_strategy`；仍失败则记录 warning + 清零（避免堆积导致每次写入都失败重试） |
| FTS 一致性 | 1 hour | `count(procedural_skills) != count(l4_skills_fts)` 时调用 `backfill_fts()` |
| 零活跃 skill 软删 | 1 day | `last_seen` 超过 `inactive_skill_retention_days` 且 `total_attempts < N` → 设 `deleted_at`（schema 加这一列） |

### 9.2 配置

`MemoryL4Settings` 新增字段：
- `breaker_open_timeout_seconds`
- `breaker_halfopen_idle_seconds`
- `inactive_skill_retention_days`
- `inactive_skill_min_attempts`
- `maintenance_enabled`

### 9.3 调度器接入

- `memory/lifecycle.py` 启动流程中实例化并启动调度任务（同 L3 模式）。
- 关停流程中正确取消任务并等待完成。

### 9.4 schema 微调

`procedural_skills` 表新增 `deleted_at REAL` 列（migration via `ALTER TABLE` in lifecycle init，已有同模式可参考 `runtime_trace/schema.py:188`）。`get_all_skills` 等读路径过滤 `deleted_at IS NULL`。

## 10. 错误隔离 / 性能

- **EventBus 失败隔离**：`InMemoryMessageBusBackend` 现有实现已经会在没有订阅者时按 `require_subscriber_delivery_metadata_key` 决定是否丢弃。订阅者抛错的隔离需要在 backend 中确认；如果未实现，在 lifecycle 的订阅注册处包一层 `safe_handler`。
- **MemoryIngestionSubscriber**：单 layer 失败由 `store_ingestion` 隔离，整体失败仅记日志，不重抛回 EventBus。
- **ToolInvocationService**：publish 失败被 try/except 吞掉只记日志，业务返回值不受影响（领域行为不能因记忆侧失败而失败）。
- **性能预算**：现网 826 条 SENSOR_EVENT + 32 条 chat 事件累计；订阅者数量 < 10，in-memory pub/sub 开销可忽略。新增 publish 在 ToolInvocationService.invoke 的 finally 中，用 fire-and-forget 风格（仍 await，但不会阻塞主路径任何昂贵操作）。

## 11. 测试策略

### 11.1 单元

- `tests/events/test_domain_payloads.py`：dataclass 序列化、`expect_payload` 行为
- `tests/agent/execution/test_tool_invocation_service.py`：成功 / 失败 / 异常三种路径下 publish 一次且参数正确
- `tests/memory/test_layer_accepts.py`：每个 layer 的 `accepts_event_types` 与 `accepts()` 矩阵
- `tests/memory/subscribers/test_memory_ingestion_subscriber.py`：6 类领域事件分别翻译到 MemoryEvent 后再走 ingest 的快照
- `tests/memory/l4/test_maintenance_schedule.py`：四类周期任务的边界条件

### 11.2 集成

- `tests/integration/test_l4_pipeline.py`：发布一条 `ToolInvocationCompleted` → 验证 `procedural_skills` / `l4_execution_traces` / `l4_skills_fts` 都有写入
- `tests/integration/test_runtime_trace_pipeline.py`：同一条事件 → 验证 `runtime_trace.db` 同步落地，`correlation_id` 一致
- `tests/integration/test_chat_to_memory.py`：chat projector publish UserMessageReceived → MemoryIngestionSubscriber → L0/L1 写入

### 11.3 回归

- 现有 `test_chat_*` / `test_awareness_*` 测试把直接 mock `unified_memory.ingest_event` 的方式改为断言总线上 publish 的事件。
- `tests/memory/l3/test_summary_schedule.py` 等保持原样。

## 12. 实施分阶段

按依赖顺序，每阶段独立可发布：

1. **基础设施层**：领域事件 dataclass + EventTypes 常量 + payload helper（无副作用）。
2. **ToolInvocationService**：新建 service + 三处调用点改造 + RuntimeTraceSubscriber 接管 trace 写入。完成后 L4 已能写入。
3. **MemoryIngestionSubscriber**：新建订阅者 + chat projector / awareness ingestion gateway 改 publish + 翻译表。完成后 ingest_event 不再被业务模块直调。
4. **Layer 自声明**：UnifiedMemoryStore fan-out 重写 + 各 layer accepts 实现。完成后 store_ingestion 的 if 链消失。
5. **Task 生命周期事件**：task_orchestrator 与 task agent post-process publish。
6. **L4 maintenance schedule**：调度器 + 配置 + schema 微调。

## 13. 风险与缓解

| 风险 | 缓解 |
|------|------|
| InMemoryMessageBusBackend 订阅者抛错没隔离 | 阅读现有实现确认；缺失则在 lifecycle 注册处 wrap |
| 现网代码里有未覆盖到的 `_tool_registry.execute()` 调用点 | 实施前用 grep 全量扫描 + 加 deprecation warning 在 execute 上 |
| chat projector 改 publish 后下游某个旧订阅者 break | MemoryIngestionSubscriber 同时订阅新旧事件类型一段时间，确认无回归后清理 |
| L4 schedule 与 strategy_extraction 抢占 LLM 资源 | maintenance 任务里强制触发 strategy_extraction 时使用与日常路径一致的速率限制 |
| schema migration 失败 | `ALTER TABLE ... ADD COLUMN deleted_at` 是 sqlite 安全操作；包一层 try 兼容已存在的列 |
| 性能：每次工具调用多一次 publish | in-memory，开销 < 1ms；事件总线已经在跑，多一个订阅者数量级不变 |

## 14. Open Questions

- TaskContext 各字段的来源：当前调用栈里 task_id / turn_id / session_id 不一定都有，是否在 ToolInvocationService 入口要求调用方传完整 ctx，还是允许 None？倾向于"允许 None，记 warning"。
- 是否需要把 `LLM_CALL_COMPLETED` 也纳入这次重构？倾向于"本次不动"，已有写入路径正常。
