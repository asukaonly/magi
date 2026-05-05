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
    # correlation_id 走外层 Event.correlation_id，不在 payload 中重复
```

### 4.2 Task 生命周期

```python
@dataclass(frozen=True)
class TaskStarted:
    task_id: str
    task_type: str
    started_at: float
    context: TaskContext

@dataclass(frozen=True)
class TaskCompleted:
    task_id: str
    task_type: str
    started_at: float
    finished_at: float
    summary: str | None
    context: TaskContext

@dataclass(frozen=True)
class TaskFailed:
    task_id: str
    task_type: str
    started_at: float
    finished_at: float
    error: ToolError
    context: TaskContext
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
  - `USER_MESSAGE_RECEIVED = "UserMessageReceived"`（`USER_MESSAGE` 仍保留以兼容现有订阅者，迁移完成后清理）
  - `ASSISTANT_RESPONSE_PRODUCED = "AssistantResponseProduced"`
  - `SENSOR_EVENT_EMITTED = "SensorEventEmitted"`
  - `TASK_STARTED / TASK_COMPLETED / TASK_FAILED` **已存在**（`events/events.py:132-134`），无需新增；本次只是把它们提升为系统级领域事件。
- 发布形态：`Event(type=EventTypes.TOOL_INVOCATION_COMPLETED, payload=<对应 dataclass>)`。`payload` 字段类型在 `Event` 上仍是 `Any`（避免改 `Event` 类影响所有订阅者），但通过约定保证。
- 提供帮手 `magi/events/payload_helpers.py::expect_payload(event, cls) -> cls`：isinstance 检查 + 错误日志。
- **`correlation_id` 归属**：`Event` 类已有 `correlation_id` 字段，本次新引入的 dataclass payload 中**不再**重复携带 `correlation_id`。所有跨订阅者关联（runtime_trace ↔ memory）通过 `Event.correlation_id` 完成。`ToolInvocationService` 在 publish 时设置 `Event.correlation_id`，订阅者从外层 `Event` 读。

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
                    correlation_id=correlation_id,   # 外层 Event 持有 correlation_id
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
                    ),
                ))
            except Exception:
                logger.exception("publish ToolInvocationCompleted failed")
```

改造点（全量 grep 后的 4 处）：

- `agent/execution/function_calling/step_executor.py:141` `_driver._execute_tool_call` → 改为通过 `ToolInvocationService.invoke`
- `agent/task_orchestration_workers.py:66, 133` → 同上
- `agent/task_agents/chat/planning_service.py:320` → 同上
- `agent/execution/function_calling/tool_execution.py:190` `host.tool_registry.execute(tool_name, arguments, context)` → 同上（**这是 function-calling 驱动的主路径，遗漏会让 chat 工具调用继续不发事件**）

实施前会再做一次 `grep -rn "tool_registry\.execute"`，把所有命中加进改造清单；同时在 `_tool_registry.execute()` 上加 `@deprecated_for_internal_use` 标记并打 warning，预防回归。

`ToolInvocationService.invoke` 的入参契约：
- `call: ToolCall` - 工具名 + 参数
- `ctx: InvocationContext` - 包含 `tool_category`、`task_context: TaskContext`，由调用方负责填充
- `tool_category` 来自调用上下文（function-calling 驱动里是 `"external_tool"` / `"mcp"` 等；orchestrator/planning 路径里是 `"internal"`），调用方决定
- `task_context` 各字段允许 `None`，但 chat 来源**必须**提供 `session_id`（见 §10）

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

**双订阅过渡期与去重**：

理论上"MemoryIngestionSubscriber 同时订阅新旧事件类型"可以兼容老 producer，但因 L0 `capture_event` 与 L4 `record_memory_event` 没有 idempotency 短路（只有 L1 `find_event_id_by_idempotency` 能去重），双订阅会导致 L0/L4 重复写入。**因此本次改造不采用双订阅**：

- 生产端**只发新事件**（不再发 USER_MESSAGE / SENSOR_EVENT 老类型）。MemoryIngestionSubscriber 仅订阅新事件，**不再做双订阅**。
- 老事件类型（USER_MESSAGE / AI_RESPONSE / SENSOR_EVENT 等）若仍被其他订阅者使用（非 memory 路径），由 producer 同时 publish 新旧两类事件来兼容；MemoryIngestionSubscriber 严格只接新类型。
- 终止条件：迁移阶段全量 grep `EventTypes.USER_MESSAGE` 等，确认无非 memory 订阅者后删除老 publish。
- 验证：迁移期间监控 `procedural_skills.last_seen` 增长是否符合工具调用频率，发现 2x 增长即视为重复写入。

### 7.2 RuntimeTraceSubscriber

新建 `magi/runtime_trace/subscribers/runtime_trace_subscriber.py`。

订阅 `ToolInvocationCompleted` / `TaskStarted` / `TaskCompleted` / `TaskFailed`，把现在分散在 `agent/execution/function_calling/tracing.py`、`step_executor`、orchestrator 里直接写 `runtime_trace.db` 的代码迁过来。`runtime_trace.db` 的 schema 不变；变的是写入触发方式。

通过 `correlation_id` 字段把同一次工具调用在 memory 与 runtime_trace 中关联起来。

## 8. UnifiedMemoryStore + Layer 自声明

### 8.1 接口

```python
@dataclass
class FanOutContext:
    """fan-out 时在 layer 之间传递的上下文，包含已完成 layer 的标记。"""
    markers: dict[str, Any] = field(default_factory=dict)  # e.g. {"l1_written": True, "stored_event_id": "..."}

class MemoryLayer(Protocol):
    layer_name: str
    accepts_event_types: frozenset[str]   # 静态声明，便于快速短路
    requires_write_lock: bool             # True 表示 ingest 必须在 _write_lock 下执行（L0/L1）
    def accepts(self, event: MemoryEvent, ctx: FanOutContext) -> bool: ...
    async def ingest(self, event: MemoryEvent, ctx: FanOutContext) -> LayerIngestResult: ...
```

`accepts(event, ctx)` 显式接收 `FanOutContext`，避免循环依赖（评审 issue #2）。

### 8.2 store_ingestion.py 重写

保留现有 `_write_lock` 语义（评审 issue #8）：写锁内执行 L0/L1，写锁外执行 L2/L3/L4。

```python
async def ingest_event(self, event_or_dict) -> dict:
    memory_event = normalize(event_or_dict)
    ctx = FanOutContext()
    results = {}

    locked_layers = [l for l in self._layers_in_order if l.requires_write_lock]
    deferred_layers = [l for l in self._layers_in_order if not l.requires_write_lock]

    async with self._write_lock:
        for layer in locked_layers:
            await self._dispatch(layer, memory_event, ctx, results)

    for layer in deferred_layers:
        await self._dispatch(layer, memory_event, ctx, results)

    return summarize(results)

async def _dispatch(self, layer, event, ctx, results):
    if event.event_type not in layer.accepts_event_types:
        return
    if not layer.accepts(event, ctx):
        return
    try:
        result = await layer.ingest(event, ctx)
        results[layer.layer_name] = result
        ctx.markers.update(result.markers)
    except Exception:
        logger.exception("layer %s ingest failed", layer.layer_name)
```

### 8.3 L2 双路径合并（评审 issue #1）

当前 `store_ingestion.py` 里 L2 有两条路径：

1. **L2 projection job 路径**（写锁内）：`self.l2.enqueue_projection_job(event_id, ...)` —— 当 `ingest_target.includes_l1` 且 `cognition_eligible` 时使用，需要先有 L1 event_id。
2. **L2 pipeline 路径**（写锁外）：`self.l2_pipeline.enqueue_event(memory_event)` —— 当不写 L1 或 L2 store 不存在时使用。

合并方案：
- L2 改造为**单一 layer 对象** `L2MemoryLayer`，持有 store + pipeline 两个组件。
- `L2MemoryLayer.requires_write_lock = True`（仍需在写锁内拿到 L1 写入产物）。
- `accepts(event, ctx) = event.cognition_eligible and (ctx.markers.get("l1_written") or not event.ingest_target.includes_l1 or self._l1_disabled)`。
- `ingest()` 内部根据 ctx 决定走 projection_job（已有 stored_event_id）还是走 pipeline（无 L1 路径）。
- L2 batch 控制元数据（`l2_batch_owner` 等）从 `event.metadata_json` 读取，行为与现状一致。

如此 if 链消失但语义不变。

### 8.4 各 layer 的声明

| Layer | accepts_event_types | requires_write_lock | accepts() 进一步条件 |
|-------|---------------------|---------------------|----------------------|
| L0 | `frozenset({USER_MESSAGE, USER_MESSAGE_RECEIVED, AI_RESPONSE, ASSISTANT_RESPONSE_PRODUCED, ACTION_EXECUTED, TASK_STARTED, TASK_COMPLETED, TASK_FAILED, SENSOR_EVENT, SENSOR_EVENT_EMITTED})` —— 实施时按 `l0.capture_event` 现有过滤精确化 | True | True |
| L1 | 现有 ingest_target.includes_l1 判定的事件 | True | `event.ingest_target.includes_l1` |
| L2 | 同 L1 | True | 见 §8.3 |
| L3 | 空集（schedule 触发，不走 fan-out） | n/a | n/a |
| L4 | `{ACTION_EXECUTED, TASK_COMPLETED, TASK_FAILED}` | False | `ctx.markers.get("l1_written") or event.event_type == ACTION_EXECUTED`（保留现状语义） |

### 8.5 LayerIngestResult.markers 约定

| Layer | markers 写入 |
|-------|--------------|
| L1 | `{"l1_written": bool, "stored_event_id": str}` |
| L2 | `{"l2_relation_count": int, "l2_assertion_count": int, "l2_job_enqueued": bool}` |
| L4 | `{"l4_skill_id": str | None}` |

后续 layer 通过 `ctx.markers` 读这些标记。

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

`procedural_skills` 表新增 `deleted_at REAL` 列。SQLite < 3.35 不支持 `ADD COLUMN IF NOT EXISTS`，故采用 try/catch 模式：

```python
# memory/l4/lifecycle.py initialize() 内
try:
    await db.execute("ALTER TABLE procedural_skills ADD COLUMN deleted_at REAL")
except aiosqlite.OperationalError as e:
    if "duplicate column name" not in str(e).lower():
        raise
```

`get_all_skills` / `count_skills` / `query_strategies` 等读路径过滤 `deleted_at IS NULL`。

## 10. 错误隔离 / 性能 / 关键不变量

### 10.1 错误隔离

- **EventBus 失败隔离**：`InMemoryMessageBusBackend` 现有实现的订阅者抛错隔离需要在实施前确认；如未实现，在 lifecycle 的订阅注册处统一 wrap `safe_handler(handler)`，捕获并记录异常。
- **MemoryIngestionSubscriber**：单 layer 失败由 `store_ingestion._dispatch` 隔离，整体失败仅记日志，不重抛回 EventBus。
- **ToolInvocationService**：publish 失败被 try/except 吞掉只记日志，业务返回值不受影响。

### 10.2 性能与背压

`InMemoryMessageBusBackend.publish` 当前实现按订阅者**串行 await**。若 MemoryIngestionSubscriber 直接在事件回调中执行 `record_memory_event` →（在阈值触发时）`_maybe_extract_strategy` → 调用 LLM，工具调用的 finally 会被 LLM 调用阻塞数秒。

约束：

- **订阅者必须 cheap**：MemoryIngestionSubscriber 的 handler 内不直接执行重活，将 `unified_memory.ingest_event` 调度为 `asyncio.create_task(...)`，handler 立即返回。
- 同样 RuntimeTraceSubscriber 的 db 写入使用 `create_task` 卸载。
- 副作用：失败不再传回到 publish 调用方（本来 publish 也只记录日志，符合预期）。
- **layer 内部顺序保证**：`ingest_event` 内部仍按 §8.2 的"locked → deferred"顺序串行执行；`create_task` 只是把整次 ingest 调用从 publish handler 卸载，**不破坏 layer 间顺序**。
- **测试可见性**：handler 改 `create_task` 之后，集成测试无法直接 `await` 业务返回；订阅者必须暴露 `drain()` / `wait_idle()` 钩子，在测试 setUp/tearDown 中等待 inflight task 全部完成，再做断言。

### 10.3 publish 再入

订阅者在 handler 内可能再 publish（例如 L4 未来加 `SkillUpdated`）。约定：

- 订阅者 publish 必须通过 `asyncio.create_task` 异步进行，避免在当前 handler 同步路径上递归 publish 导致顺序不可知。
- 文档级要求写在 `MemoryIngestionSubscriber` 与 `RuntimeTraceSubscriber` 类 docstring。

### 10.4 TaskContext 字段约束

- `task_id`、`turn_id`：可 `None`（很多链路无 task）。
- `user_id`：可 `None`（系统事件、awareness 时无 user）。
- `session_id`：**chat 派生的事件必须非 None**（L1 partitioning / chat session 关联依赖）。其他来源（工具执行、sensor、task 内部）允许 None；MemoryIngestionSubscriber 在翻译时做断言并打 warning。

### 10.5 性能预算

- 现网量：826 SENSOR + 32 chat 事件累计；新增 `ToolInvocationCompleted` 频率上限是工具调用频率，现网每天 < 1000 量级。
- 订阅者总数：< 5（memory / runtime_trace / 未来 metrics / behavior）。
- handler 卸载到 task 之后，publish 调用方耗时 < 1ms。

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
| chat projector 改 publish 后下游某个旧订阅者 break | 实施前 grep 全量 USER_MESSAGE / AI_RESPONSE / SENSOR_EVENT 订阅者；非 memory 订阅者继续接收老事件（producer 同时 publish 新旧），memory 侧只接新事件 |
| L4 schedule 与 strategy_extraction 抢占 LLM 资源 | maintenance 任务里强制触发 strategy_extraction 时使用与日常路径一致的速率限制 |
| schema migration 失败 | `ALTER TABLE ... ADD COLUMN deleted_at` 是 sqlite 安全操作；包一层 try 兼容已存在的列 |
| 性能：每次工具调用多一次 publish | in-memory，开销 < 1ms；事件总线已经在跑，多一个订阅者数量级不变 |

## 14. Open Questions

- **`LLM_CALL_COMPLETED` 是否纳入本次重构**：倾向"本次不动"。已有写入路径正常，待后续单独迭代。

（TaskContext 各字段的可空性在 §10.4 显式回答；不再列为 open。）

## 15. 评审记录

2026-05-05 经 spec-document-reviewer 评审，已修复以下问题：

- L2 双路径合并写法（§8.3）
- `MemoryLayer.accepts` 签名增加 `FanOutContext` 参数（§8.1）
- 工具执行调用点补全为 4 处（§5）
- `correlation_id` 归属外层 `Event`，payload 不再重复（§4.4）
- 双订阅过渡期改为"生产端只发新事件"，避免 L0/L4 重复写入（§7.1）
- L4 schema migration 改用 try/catch 处理重复列（§9.4）
- 订阅者 handler 必须卸载重活到 `create_task`，规避 publish 串行 await 阻塞（§10.2、§10.3）
- TaskContext 字段可空性：chat 来源 `session_id` 必须非 None（§10.4）
