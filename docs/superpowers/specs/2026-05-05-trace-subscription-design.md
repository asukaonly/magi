# runtime_trace 完全订阅化（子项目 B）设计

日期：2026-05-05
作者：asuka
子项目代号：**B**（trace 重构，理想态架构子项目 2/4）

## 1. 背景

子项目 A 已经把 producer-assigned `event_id` / `causation_id` / `trace_context` 加到 Event 信封，并提供 `magi.events.tracing.start_span()` API（仅返回 frozen TraceContext，A 阶段 business 路径未埋点）。本子项目继续推进"理想态"架构：把 `runtime_trace` 从一组分散的"业务直写"改为单一订阅者投影。

现状：grep 显示 27 处业务代码直接调用 `_runtime_trace_store.upsert_span / upsert_tool_call / upsert_intent_resolution / upsert_llm_call / upsert_turn`，分布于：

- `agent/task_agents/chat/postprocess/intent.py` 多处
- `agent/task_agents/chat/postprocess/components.py` 多处
- `agent/task_agents/chat/postprocess_service.py`
- `agent/task_agents/chat_task_agent.py`
- `awareness/scheduler_contrib.py`
- `transport/chat_events.py`
- `core/container.py` / `bootstrap/*.py`（构造侧）

`runtime_trace` 表族：`trace_turns / trace_spans / trace_tools / trace_llm_calls / trace_intent_resolutions`（外加 `runtime_notifications / runtime_heartbeats / plugin_ingress_events`，本子项目不动）。

子项目 A 的 ToolInvocationService 已经发 `ToolInvocationCompleted`、TaskOrchestrator 已发 `TaskStarted/Completed/Failed`，但这些事件是为 memory 路径准备的、不投影到 runtime_trace。本子项目把这些 + 其他 trace 表的所有写入统一到一个事件类型 `SpanCompleted`。

## 2. 目标 / 非目标

### 目标

1. 引入单一领域事件 `SpanCompleted`，承载 trace 树的完整 lifecycle（OTel 风格）。
2. 升级 `magi.events.tracing` 模块：`start_span()` 返回 mutable `Span` 对象（OTel 风格 lifecycle），`current_trace_context()` 仍返回 frozen `TraceContext`。Span 在 contextvars 里，with 退出时自动 publish `SpanCompleted`。
3. 实现 `RuntimeTraceSubscriber`：订阅 `SpanCompleted`，按 `node_type` 字典表 dispatch 到 5 张 trace 表。
4. 业务路径全部从 `_runtime_trace_store.upsert_*` 直写改为 `with start_span(node_type=..., name=...) as span: ...`。
5. ToolInvocationCompleted / TaskStarted/Completed/Failed 并入 SpanCompleted，按 `node_type` 路由。memory 翻译路径同步适配。
6. 完成后 grep `_runtime_trace_store.upsert_` 在 src 业务代码中应为零命中。

### 非目标

- 不做 cross-process trace 传播（W3C Trace Context HTTP header 等）—— 留待 D 子项目。
- 不接 OTel exporter / Jaeger 后端 —— 留待 D。
- 不动 `runtime_notifications / runtime_heartbeats / plugin_ingress_events` 表 —— 与 trace 树无关。
- 不重写 `runtime_trace_store` 内部 upsert 实现 —— 订阅者继续调它，只是从一个地方调。
- 不引入 OTel SDK 依赖 —— 内部抽象，命名对齐 OTel 概念以便未来对接。

## 3. 整体架构

```
┌────── Producer (业务路径) ──────────────────────────┐
│ with start_span(node_type="tool_invocation",         │
│                 name=tool_name) as span:             │
│     span.set_attribute("tool_name", tool_name)       │
│     ...                                              │
│     span.set_attribute("success", True)              │
│ # __exit__ 时 publish SpanCompleted                  │
└──────────────┬──────────────────────────────────────┘
               │ SpanCompleted(node_type, span_id,
               │                trace_id, attributes, …)
               ▼
        EventBus（fan-out）
               │
   ┌───────────┼───────────┐
   ▼           ▼           ▼
┌────────────┐ ┌──────────────────┐
│ Memory     │ │ RuntimeTrace     │
│ Ingestion  │ │ Subscriber       │
│ Subscriber │ │  - dict dispatch │
│            │ │    by node_type  │
└────────────┘ └──────────────────┘
   写 L0/L1/L4    总是写 trace_spans
                  + 视 node_type 写
                    trace_tools /
                    trace_llm_calls /
                    trace_intent_resolutions /
                    trace_turns 之一
```

约束：
- 一个事件 = 一个事实 = 一次 RuntimeTraceSubscriber 投影。
- trace_spans 行**总是写**（任何 node_type 都是一个 span）。子表行根据 node_type optionally 写。这避免外键孤儿。
- Span lifecycle：单事件 `SpanCompleted`，no SpanStarted。事件流只表达"已发生"事实。
- 业务路径用 `with` 包裹手工 wrap，不用装饰器（attributes 在 lifecycle 内累加，装饰器表达不便）。

## 4. 领域事件契约

新增 `magi.events.domain_payloads.SpanCompleted`：

```python
@dataclass(frozen=True)
class SpanCompleted:
    # span identity (trace 树拓扑)
    span_id: str
    trace_id: str
    parent_span_id: Optional[str]

    # span semantics
    node_type: str           # 路由键: "tool_invocation" / "llm_call" /
                             # "intent_resolution" / "turn" / "task_lifecycle" /
                             # "span" (default)
    name: str                # 业务可读名: tool_name / model / "intent_resolve" / etc.
    status: str              # "ok" / "error" / "cancelled"

    # lifecycle
    started_at_ms: int
    ended_at_ms: int
    duration_ms: int

    # error / preview
    error: Optional[ToolError]
    result_preview: Optional[str]

    # routing context（需要跨表 join 时用）
    turn_id: Optional[str]

    # attributes - 子表特有字段。值类型 Any，由 RuntimeTraceSubscriber 按
    # node_type 提取。
    attributes: Mapping[str, Any] = field(default_factory=dict)
```

`attributes` 字典装下子表特有字段（订阅者 handler 按 node_type 提取）：

**通用字段**（任何 node_type 都可能填，对应 `trace_spans` 表上除 span 标识外的列）：

| key | 类型 | 来源 |
|-----|------|------|
| `attempt_index` | int | 重试场景，默认 1 |
| `retry_count` | int | 默认 0 |
| `iteration` | int | worker 循环序号，None 表非循环 |
| `execution_agent_id` | str | 业务代码 set，None 表未知 |
| `run_id` | str | task orchestration run id |
| `run_revision` | int | 默认 0 |

**子表特有字段**：

| node_type | attributes keys |
|-----------|----------------|
| `tool_invocation` | tool_name, tool_call_id, arguments_json, success, execution_time_ms, error_code, error_message, result_preview, result_json |
| `llm_call` | provider, model, input_tokens, output_tokens, reasoning_tokens, cache_read_tokens, cache_write_tokens, thinking_enabled, thinking_depth, request_preview, response_preview, thinking_content |
| `intent_resolution` | intent, execution_mode, route_reason, selected_tools_json, selected_worker_type |
| `turn` | user_id, session_id, status, started_at, updated_at, continued_from_turn_id, continued_from_trace_id, superseded_by_turn_id |
| `task_lifecycle` | task_id, task_type, started_at, finished_at, summary, error_type, error_message |
| `span` (default) | （仅写 trace_spans 基行；通用字段视情况）|

`EventTypes` 新增：

```python
SPAN_COMPLETED = "SpanCompleted"
```

`ToolInvocationCompleted` / `TaskStarted` / `TaskCompleted` / `TaskFailed` 这四个 A 阶段的事件类型**保留**（用于 memory 翻译期），但本子项目所有 producer 改发 `SpanCompleted`。MemoryIngestionSubscriber 适配（§7）。

## 5. Span 抽象升级

`magi.events.tracing` 模块：

```python
@dataclass(frozen=True)
class TraceContext:
    """Frozen, transportable subset (OTel SpanContext 对应)。"""
    trace_id: str
    span_id: str
    parent_span_id: Optional[str]


class Span:
    """Mutable lifecycle object (OTel Span 对应)。仅在 'with' scope 内有效。"""

    def __init__(
        self,
        *,
        node_type: str,
        name: str,
        context: TraceContext,
        started_at_ms: int,
    ) -> None:
        self._context = context
        self._node_type = node_type
        self._name = name
        self._started_at_ms = started_at_ms
        self._attributes: dict[str, Any] = {}
        self._status = "ok"
        self._error: Optional[ToolError] = None
        self._result_preview: Optional[str] = None
        self._turn_id: Optional[str] = None  # 可选业务字段

    @property
    def context(self) -> TraceContext: ...

    @property
    def node_type(self) -> str: ...

    def set_name(self, name: str) -> None: ...
    def set_attribute(self, key: str, value: Any) -> None: ...
    def set_attributes(self, attrs: Mapping[str, Any]) -> None: ...
    def set_status(self, status: str) -> None: ...   # "ok" / "error" / "cancelled"
    def record_exception(self, exc: BaseException) -> None: ...
    def set_result_preview(self, preview: str) -> None: ...
    def set_turn_id(self, turn_id: str) -> None: ...

    def _to_completed_payload(self, ended_at_ms: int) -> SpanCompleted:
        return SpanCompleted(
            span_id=self._context.span_id,
            trace_id=self._context.trace_id,
            parent_span_id=self._context.parent_span_id,
            node_type=self._node_type,
            name=self._name,
            status=self._status,
            started_at_ms=self._started_at_ms,
            ended_at_ms=ended_at_ms,
            duration_ms=ended_at_ms - self._started_at_ms,
            error=self._error,
            result_preview=self._result_preview,
            turn_id=self._turn_id,
            attributes=dict(self._attributes),  # snapshot
        )


_current_trace_context: ContextVar[Optional[TraceContext]] = ContextVar(
    "magi_trace_context", default=None,
)
_current_span: ContextVar[Optional[Span]] = ContextVar(
    "magi_current_span", default=None,
)


def current_trace_context() -> Optional[TraceContext]:
    return _current_trace_context.get()


def current_span() -> Optional[Span]:
    return _current_span.get()


@contextmanager
def start_span(
    *,
    node_type: str = "span",
    name: str = "",
    trace_id: Optional[str] = None,
    delivery: str = "async",   # "async" (fire-and-forget, default) | "sync" (await before exit)
) -> Iterator[Span]:
    """Sync context manager. For async code paths use start_async_span()."""
    parent_ctx = _current_trace_context.get()
    ctx = TraceContext(
        trace_id=trace_id or (parent_ctx.trace_id if parent_ctx else str(ULID())),
        span_id=str(ULID()),
        parent_span_id=parent_ctx.span_id if parent_ctx else None,
    )
    started_at_ms = int(time.time() * 1000)
    span = Span(node_type=node_type, name=name, context=ctx, started_at_ms=started_at_ms)
    # 自动从父 span 继承 turn_id（绝大多数嵌套 span 都需要，避免业务遗漏）
    parent_span = _current_span.get()
    if parent_span is not None and parent_span._turn_id is not None:
        span._turn_id = parent_span._turn_id

    span_token = _current_span.set(span)
    ctx_token = _current_trace_context.set(ctx)
    try:
        yield span
    except asyncio.CancelledError:
        span.set_status("cancelled")
        raise
    except BaseException as exc:
        span.record_exception(exc)
        raise
    finally:
        _current_span.reset(span_token)
        _current_trace_context.reset(ctx_token)
        ended_at_ms = int(time.time() * 1000)
        try:
            _publish_span_completed(span, ended_at_ms, delivery=delivery)
        except Exception:
            logger.exception("publish SpanCompleted failed (span=%s)", span._context.span_id)


@asynccontextmanager
async def start_async_span(
    *,
    node_type: str = "span",
    name: str = "",
    trace_id: Optional[str] = None,
    delivery: str = "async",
) -> AsyncIterator[Span]:
    """Async-friendly variant. Use for `async with` blocks where the body awaits.

    Internally identical to start_span() except wrapped in @asynccontextmanager.
    Both share the same Span class, contextvars, and publish path.
    """
    parent_ctx = _current_trace_context.get()
    ctx = TraceContext(
        trace_id=trace_id or (parent_ctx.trace_id if parent_ctx else str(ULID())),
        span_id=str(ULID()),
        parent_span_id=parent_ctx.span_id if parent_ctx else None,
    )
    started_at_ms = int(time.time() * 1000)
    span = Span(node_type=node_type, name=name, context=ctx, started_at_ms=started_at_ms)
    parent_span = _current_span.get()
    if parent_span is not None and parent_span._turn_id is not None:
        span._turn_id = parent_span._turn_id

    span_token = _current_span.set(span)
    ctx_token = _current_trace_context.set(ctx)
    try:
        yield span
    except asyncio.CancelledError:
        span.set_status("cancelled")
        raise
    except BaseException as exc:
        span.record_exception(exc)
        raise
    finally:
        _current_span.reset(span_token)
        _current_trace_context.reset(ctx_token)
        ended_at_ms = int(time.time() * 1000)
        try:
            await _publish_span_completed_async(span, ended_at_ms, delivery=delivery)
        except Exception:
            logger.exception("publish SpanCompleted failed (span=%s)", span._context.span_id)


# Module-level pending-task registry, so unawaited create_task results
# survive GC and can be drained at shutdown.
_PENDING: set[asyncio.Task] = set()


def _track_pending(task: asyncio.Task) -> None:
    _PENDING.add(task)
    task.add_done_callback(_PENDING.discard)


async def drain_pending() -> None:
    """Await all in-flight publish tasks. Called by lifecycle on shutdown
    BEFORE the bus stops, so the events are delivered."""
    if not _PENDING:
        return
    await asyncio.gather(*list(_PENDING), return_exceptions=True)


def _publish_span_completed(span: Span, ended_at_ms: int, *, delivery: str) -> None:
    payload = span._to_completed_payload(ended_at_ms)
    bus = _resolve_event_bus()
    if bus is None:
        return
    event = Event(type=EventTypes.SPAN_COMPLETED, data=payload, source="tracing")
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # 同步路径外不发；正常运行不应触发
    if delivery == "sync":
        # 在同步 contextmanager 里要 await 不可行；视为退化为 async
        logger.debug("delivery=sync requested in sync start_span; degrading to async")
    task = loop.create_task(bus.publish(event))
    _track_pending(task)


async def _publish_span_completed_async(span: Span, ended_at_ms: int, *, delivery: str) -> None:
    payload = span._to_completed_payload(ended_at_ms)
    bus = _resolve_event_bus()
    if bus is None:
        return
    event = Event(type=EventTypes.SPAN_COMPLETED, data=payload, source="tracing")
    if delivery == "sync":
        # 在 async with 出栈时同步 await，确保关键 span 投递
        try:
            await bus.publish(event)
        except Exception:
            logger.exception("sync publish failed")
        return
    loop = asyncio.get_running_loop()
    task = loop.create_task(bus.publish(event))
    _track_pending(task)


def _resolve_event_bus():
    """Return the wired MessageBus or None. None on test fixtures / early bootstrap.

    Detection: Container.message_bus() default is providers.Singleton(object) which
    yields a bare `object()` lacking `publish`. We test for the publish attribute
    instead of relying on `type().__name__ == "object"` which is fragile.
    """
    try:
        from ..core.container import Container
        bus = Container.message_bus()
    except Exception:
        return None
    if bus is None or not hasattr(bus, "publish"):
        return None
    return bus
```

向后兼容：A 阶段 8 个 tracing 单测 `start_span()` 不传 `node_type/name` 仍能工作（默认值"span"/""）。

## 6. RuntimeTraceSubscriber

新建 `backend/src/magi/runtime_trace/subscribers/runtime_trace_subscriber.py`：

```python
class RuntimeTraceSubscriber:
    """Subscribes to SpanCompleted and projects into 5 trace tables.

    The base trace_spans row is ALWAYS written. A node_type-specific sub-table
    row is OPTIONALLY written based on the dispatch table.
    """

    def __init__(self, *, event_bus, trace_store):
        self._bus = event_bus
        self._store = trace_store
        self._sub_id: Optional[str] = None
        self._inflight: set[asyncio.Task] = set()
        self._subtable_dispatch: dict[str, Callable[[SpanCompleted], Awaitable[None]]] = {
            "tool_invocation": self._record_tool_call,
            "llm_call": self._record_llm_call,
            "intent_resolution": self._record_intent_resolution,
            "turn": self._record_turn,
        }

    async def start(self) -> None:
        self._sub_id = await self._bus.subscribe(
            EventTypes.SPAN_COMPLETED, self._on_span_completed
        )

    async def stop(self) -> None:
        if self._sub_id is not None:
            try:
                await self._bus.unsubscribe(self._sub_id)
            except Exception:
                logger.exception("unsubscribe failed")
            self._sub_id = None
        await self.drain()

    async def drain(self) -> None:
        if not self._inflight:
            return
        await asyncio.gather(*list(self._inflight), return_exceptions=True)

    async def _on_span_completed(self, event: Event) -> None:
        try:
            payload = expect_payload(event, SpanCompleted)
        except PayloadTypeError:
            logger.exception("malformed SpanCompleted payload")
            return
        task = asyncio.create_task(self._safe_project(payload))
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _safe_project(self, p: SpanCompleted) -> None:
        try:
            await self._record_span(p)  # base table 总是写
            handler = self._subtable_dispatch.get(p.node_type)
            if handler is not None:
                await handler(p)
        except Exception:
            logger.exception("runtime_trace projection failed: span=%s", p.span_id)

    async def _record_span(self, p: SpanCompleted) -> None:
        record = TraceSpanRecord(
            span_id=p.span_id,
            trace_id=p.trace_id,
            turn_id=p.turn_id,  # may be None for non-turn-scoped spans (see §6.1)
            parent_span_id=p.parent_span_id,
            node_type=p.node_type,
            name=p.name,
            status=p.status,
            attempt_index=int(p.attributes.get("attempt_index", 1)),
            retry_count=int(p.attributes.get("retry_count", 0)),
            iteration=p.attributes.get("iteration"),
            execution_agent_id=p.attributes.get("execution_agent_id"),
            result_preview=p.result_preview,
            error_text=p.error.message if p.error else None,
            run_id=p.attributes.get("run_id"),
            run_revision=int(p.attributes.get("run_revision", 0)),
            started_at_ms=p.started_at_ms,
            ended_at_ms=p.ended_at_ms,
            duration_ms=p.duration_ms,
            created_at_ms=p.started_at_ms,
            updated_at_ms=p.ended_at_ms,
        )
        await self._store.upsert_span(record)

    async def _record_tool_call(self, p: SpanCompleted) -> None: ...
    async def _record_llm_call(self, p: SpanCompleted) -> None: ...
    async def _record_intent_resolution(self, p: SpanCompleted) -> None: ...
    async def _record_turn(self, p: SpanCompleted) -> None: ...
```

### 6.1 turn_id 与 schema 微调

`trace_spans.turn_id` 现 schema 是 `TEXT NOT NULL`（无 FK 约束）。但 trace 树并非每个 span 都属于某个 chat turn——例如 awareness scheduler 触发的 span、worker 内部循环 span 等不绑定 chat turn 上下文。强制 NOT NULL 加上"空字符串兜底"是脏数据反模式（违反 NULL 与空字符串的语义区分）。

**schema 改造**：把 `trace_spans.turn_id` 从 NOT NULL 放松为 nullable。在 `runtime_trace/schema.py` 的 `ensure_runtime_trace_schema` 里加 idempotent migration（SQLite 的 ALTER COLUMN 操作复杂，用"重建表"模式或简单地容忍 NOT NULL 约束依旧存在但订阅者写 NULL → 触发迁移路径）。

最简方案：保留 NOT NULL 约束不动，订阅者侧若 `p.turn_id is None` 则 fallback 到 `p.trace_id`（trace_id 永远非空）。这样既保留现有 schema，又避免空字符串。语义近似"如果不属于具体 turn，就用 trace_id 作占位"，与 trace_turns 的"trace_id PK"一致。

实施 §6.1 决定采用：**fallback 到 trace_id**（不改 schema）。

```python
turn_id_for_record = p.turn_id or p.trace_id
record = TraceSpanRecord(..., turn_id=turn_id_for_record, ...)
```

### 6.2 Lifecycle 顺序

`RuntimeTraceSubscriberModule` 的 shutdown 顺序：

1. 业务路径（chat / task / awareness）已经 stop —— producer 不再发新 SpanCompleted。
2. `tracing.drain_pending()` —— 等待所有 fire-and-forget publish 任务把事件投到 bus 队列。
3. `RuntimeTraceSubscriber.stop()` —— unsubscribe + drain inflight projection 任务。
4. `bus.stop()` —— 关闭总线。

依赖声明：`RuntimeTraceSubscriberModule` 在 `runtime_message_bus` 之后启动、之前关闭。lifecycle 模块内 shutdown 调用 `await tracing.drain_pending()` 然后 `await self._subscriber.stop()`。

如此保证：业务结束 → 投递队列空 → 订阅者投影完成 → 总线关闭。事件不丢。

接入：仿 A 的 `MemoryIngestionSubscriberModule` 模式，新建 `RuntimeTraceSubscriberModule(LifecycleModule)`，依赖 `runtime_message_bus / runtime_trace_store`。

错误隔离：handler 失败不传回订阅者；订阅者失败不传回总线。

## 7. 业务路径迁移

### 7.1 ToolInvocationService 改造

A 阶段在 finally 里 publish `Event(TOOL_INVOCATION_COMPLETED, ToolInvocationCompleted)`。改造：

```python
# Before (A)
async def invoke(self, call, ctx):
    started_at = time.time()
    started_mono = time.monotonic()
    success = False; error_obj = None; result = None
    try:
        result = await self._tool_registry.execute(...)
        ...
        return result
    finally:
        await self._event_bus.publish(Event(
            type=EventTypes.TOOL_INVOCATION_COMPLETED,
            data=ToolInvocationCompleted(...),
        ))

# After (B)
async def invoke(self, call, ctx):
    with start_span(node_type="tool_invocation", name=call.name) as span:
        span.set_turn_id(ctx.task_context.turn_id)
        span.set_attribute("tool_name", call.name)
        span.set_attribute("tool_call_id", ctx.tool_call_id or None)
        span.set_attribute("arguments_json", json.dumps(call.args))
        try:
            result = await self._tool_registry.execute(...)
            success = bool(getattr(result, "success", False))
            span.set_attribute("success", success)
            if not success:
                span.set_status("error")
                span.set_attribute("error_code", getattr(result, "error_code", None))
                span.set_attribute("error_message", getattr(result, "error", None))
            span.set_attribute("execution_time_ms", int((time.monotonic() - started_mono) * 1000))
            span.set_result_preview(_summarize(result))
            return result
        except Exception:
            span.set_status("error")
            raise
    # span.__exit__ publishes SpanCompleted(node_type="tool_invocation")
```

旧的 `Event(TOOL_INVOCATION_COMPLETED, ...)` publish 删除。

### 7.2 TaskOrchestrator 改造

A 阶段在 5 处 publish TaskStarted / TaskCompleted / TaskFailed。改造为 `task_lifecycle` node_type 的 SpanCompleted。

注意：task lifecycle **不是单点 span**——一个 task 从 start 到 complete 之间可能跑数秒到数分钟，业务上是个长 span。但 SpanCompleted 是单事件，不能两次发。两个选项：

a) **task 整体一个 span**：在 task entry 用 `async with start_span(node_type="task_lifecycle", name=task_type) as span:`，task body 全在 with 块内。with 退出时一次 publish。优点：一个 task = 一个事件，符合"事实已发生"原则。缺点：要求 task entry/exit 在同一函数（实际就是 `start_orchestration` / `process_worker_updates` 等已经成对存在）。

b) **start_orchestration 内开 span，状态变化时手工 publish 多次**：保留 A 的多 publish 模型。但破坏了 SpanCompleted 单一发送语义。

选 (a)。`TaskOrchestrator.start_orchestration` 等长函数用 `async with start_span(...)`包裹 task 主体。内部状态切换通过 `span.set_attribute("status", ...)`。task 失败 / 取消通过 `span.set_status("error" / "cancelled")`。

A 阶段的 4 个事件常量（`TASK_STARTED / TASK_COMPLETED / TASK_FAILED`）保留但 producer 不再发。

### 7.3 chat post-process 改造

`postprocess/intent.py` 现有形式：

```python
await host._runtime_trace_store.upsert_span(TraceSpanRecord(...))
await host._runtime_trace_store.upsert_intent_resolution(TraceIntentResolutionRecord(...))
await host._runtime_trace_store.upsert_llm_call(TraceLlmCallRecord(...))
```

改造：

```python
with start_span(node_type="intent_resolution", name="resolve_intent") as span:
    span.set_turn_id(turn_id)
    span.set_attribute("intent", intent.value)
    span.set_attribute("execution_mode", mode)
    span.set_attribute("route_reason", reason)
    span.set_attribute("selected_tools_json", json.dumps(tools))
    span.set_attribute("selected_worker_type", worker_type)

with start_span(node_type="llm_call", name=model) as span:
    span.set_turn_id(turn_id)
    span.set_attribute("provider", provider)
    span.set_attribute("model", model)
    span.set_attribute("input_tokens", token_in)
    ...
```

### 7.4 chat post-process/components.py 改造（trace_turns）

`upsert_turn` 调用点改为 `with start_span(node_type="turn", name=turn_id)` 并把 turn 字段全部 set_attribute。

trace_turns 表的 PK 是 `trace_id`（一条 trace 一行），所以投影时 `_record_turn` 用 `INSERT ... ON CONFLICT(trace_id) DO UPDATE SET ...` 模式。多次写同一 trace_id 是 update 行为，符合 chat turn 多阶段更新的语义。

### 7.5 MemoryIngestionSubscriber 适配

A 阶段订阅 `TOOL_INVOCATION_COMPLETED / TASK_STARTED / TASK_COMPLETED / TASK_FAILED / USER_MESSAGE_RECEIVED / ASSISTANT_RESPONSE_PRODUCED / SENSOR_EVENT_EMITTED`，本阶段：

- 改为也订阅 `SPAN_COMPLETED`
- `_on_span_completed` 按 node_type 路由：
  - `tool_invocation` → 翻译为 ACTION_EXECUTED MemoryEvent，attributes 提取 tool_name / args / result / error / duration
  - `task_lifecycle` → 翻译为 TASK_COMPLETED 或 TASK_FAILED MemoryEvent（按 status）
  - 其他 node_type（llm_call / intent_resolution / turn / span）→ 跳过（memory 不感兴趣）
- 保留 `TOOL_INVOCATION_COMPLETED / TASK_*` 老事件订阅作兼容：本阶段 producer 全切到 SpanCompleted，老订阅不会被触发，但留着不删（B 完成后下一个 PR 清理）。

`event_translation.py` 增加 `_from_span_completed(event) -> Optional[MemoryEvent]`，按 node_type dispatch 到现有的 `_from_tool_invocation` / `_from_task_completed` / `_from_task_failed`。

### 7.5b 全部 24 处迁移点清单

实施前 grep 已经枚举（24 处而非 §1 的概数 27——实际计数）：

| 文件 | 行 | 调用 | 目标 node_type | 阶段 |
|------|----|------|----------------|------|
| `agent/task_agents/chat/postprocess/intent.py` | 113 | upsert_span | `span` | 5 |
| 同上 | 130 | upsert_intent_resolution | `intent_resolution` | 5 |
| 同上 | 157 | upsert_llm_call | `llm_call` | 5 |
| 同上 | 212 | upsert_intent_resolution | `intent_resolution` | 5 |
| `agent/task_agents/chat/postprocess/trace_llm.py` | 61 | upsert_span | `span` | 5 |
| 同上 | 80 | upsert_llm_call | `llm_call` | 5 |
| 同上 | 124 | upsert_span | `span` | 5 |
| 同上 | 140 | upsert_llm_call | `llm_call` | 5 |
| `agent/task_agents/chat/postprocess/trace_runtime.py` | 47 | upsert_span | `span` | 5 |
| 同上 | 64 | upsert_span | `span` | 5 |
| 同上 | 81 | upsert_turn | `turn` | 5 |
| 同上 | 116 | upsert_turn | `turn` | 5 |
| 同上 | 132 | upsert_span | `span` | 5 |
| 同上 | 177 | upsert_turn | `turn` | 5 |
| 同上 | 205 | upsert_span | `span` | 5 |
| `agent/workers/worker_trace.py` | 52 | upsert_span | `span` | 5 |
| 同上 | 73 | upsert_llm_call | `llm_call` | 5 |
| 同上 | 159 | upsert_span | `span` | 5 |
| 同上 | 187 | upsert_span | `span` | 5 |
| 同上 | 212 | upsert_span | `span` | 5 |
| 同上 | 262 | upsert_span | `span` | 5 |
| 同上 | 307 | upsert_span | `span` | 5 |
| 同上 | 362 | upsert_span | `span` | 5 |
| 同上 | 383 | upsert_tool_call | `tool_invocation` | 5 |

外加：
- ToolInvocationService（A 已发 ToolInvocationCompleted）→ 改发 SpanCompleted (`tool_invocation`)
- TaskOrchestrator 5 处 task lifecycle → `async with start_async_span(node_type="task_lifecycle")` 包裹 task 主体

迁移按阶段：实施 plan 的 chunk 分配按表里 "阶段" 列。

### 7.6 grep 验收

完成后：

```bash
grep -rn "_runtime_trace_store\.upsert_" backend/src --include="*.py" | grep -v "__pycache__\|runtime_trace/"
```

应为 0 命中。`runtime_trace/recorder.py` 的空实现可以删除（A 阶段留的占位）。

### 7.7 trace_turns ON CONFLICT 语义

`trace_turns` 表 PK 是 `trace_id`。chat turn 在 lifecycle 中可能多次更新（创建 / 状态变化 / 完成）。本子项目改造后，每次更新都是 `with start_span(node_type="turn", ...)` 退出时 publish 一次 SpanCompleted。多个 SpanCompleted 共享同一 trace_id → 投影到同一行 → 必须 UPDATE。

策略：**每次 turn span 都携带"截止此刻完整的 turn 状态"**——即 `attributes` 里所有字段都填，订阅者无脑 UPDATE 整行。这避免了 partial update 的 NULL 覆盖问题。原直写代码已经是这种模式（每次 `upsert_turn` 传完整 `TraceTurnRecord`），迁移后保持。

`_record_turn` handler 用 `INSERT INTO trace_turns ... ON CONFLICT(trace_id) DO UPDATE SET <所有列>=excluded.<所有列>`。trace_records.py 现有 SQL 已是此模式（含 COALESCE 处理 continued_from_* 等可选字段），订阅者直接复用 `_runtime_trace_store.upsert_turn`。

## 8. 测试策略

### 8.1 单元

- `tests/events/test_span.py`
  - Span.set_attribute 累加；set_attributes 批量
  - record_exception 同时 set_status("error") + 记录 error
  - _to_completed_payload 字段填充正确
  - context 派生：parent_span_id 与 nested span 关系
- `tests/events/test_tracing_b.py`
  - `start_span(node_type="tool_invocation")` 写入 `_current_span` contextvars
  - with exit 后 _current_span 恢复
  - with exit 自动 publish SpanCompleted 到 bus（mock bus）
  - publish 失败不传回业务（mock bus.publish raise）
  - bus 未 wire 时 publish silently skip（不抛异常）
  - 嵌套 span：子 trace_id == 父；子 parent_span_id == 父 span_id
  - asyncio.gather sibling spans 共享 trace_id 但 span_id 各异
- `tests/events/test_span_completed_payload.py`
  - SpanCompleted 是 frozen dataclass
  - attributes 默认空 dict

### 8.2 订阅者

- `tests/runtime_trace/test_runtime_trace_subscriber.py`
  - 5 个 node_type dispatch 矩阵：每个 node_type 各一测试，构造 SpanCompleted、调 `_on_span_completed`、await drain、断言对应的 _store.upsert_* 被调
  - base trace_spans 行**每次都写**（不论 node_type）
  - sub-table 仅在 node_type 匹配时写
  - 默认 `node_type="span"` 不写任何子表，仅 trace_spans
  - handler 抛错不影响订阅者后续事件处理

### 8.3 集成

- `tests/integration/test_b_trace_pipeline.py`
  - 启动真 InMemoryMessageBusBackend + 真 RuntimeTraceStore（temp DB）+ RuntimeTraceSubscriber
  - 业务代码用 `with start_span(node_type="tool_invocation")` 跑一次
  - 查 trace_spans + trace_tools 都有 1 行；trace_id 一致
- `tests/integration/test_l4_end_to_end.py`（既有 3 个）继续过——验证 SpanCompleted(tool_invocation) → MemoryIngestionSubscriber → L4 链路

### 8.4 回归

- chat post-process 全套测试通过——这是 trace 写入最密集的路径。
- `_runtime_trace_store.upsert_*` grep 在 src 业务代码中 0 命中。

## 9. 实施分阶段

按依赖顺序，每阶段独立可发布：

1. **Span 抽象升级** + SpanCompleted dataclass + EventTypes.SPAN_COMPLETED + 单测。A 阶段 8 个 tracing 测试不动。
2. **RuntimeTraceSubscriber** + dispatch 字典 + 单测。lifecycle 模块。**此时订阅者已就位但没有 producer。**
3. **ToolInvocationService 改造**：发 SpanCompleted 替代 ToolInvocationCompleted；MemoryIngestionSubscriber 同时认识两种事件，按 node_type 翻译。集成测试更新。
4. **TaskOrchestrator 改造**：5 处 publish 改为 `async with start_span(node_type="task_lifecycle")` 包裹 task 主体。
5. **chat post-process 改造**：intent.py / components.py / postprocess_service.py 改造。
6. **其他散落 27 处**全部清零。
7. **回归 + grep 验证**：旧调用全部消失。

## 10. 错误隔离 / 性能

### 错误隔离

- `_publish_span_completed` 完全 fire-and-forget：所有失败 logger.exception 后吞掉。
- 业务侧 `with start_span` 不感知 publish 成功与否，trace 是 best-effort。
- RuntimeTraceSubscriber._safe_project 包 try/except，handler 失败仅日志。
- bus 未注入时 publish 静默 skip（test fixture / 早期 bootstrap 场景）。

### 性能

- `start_span` 进入：ULID 生成 + 1 次 contextvars set ≈ < 5μs。
- 退出：1 次 SpanCompleted 构造 + create_task 调度 ≈ < 10μs。
- 投影：每次事件一次 trace_spans + 0~1 次子表 upsert，与现状直写工作量相同（仅迁移路径）。
- contextvars 在 `asyncio.create_task` 自动 fork——子任务能看见父 span，无需手动传播。

### Hot-path 验证

- ToolInvocationService 是 hot path（每次工具调用一次 span）。开销 < 50μs，可忽略。
- chat post-process 一个 turn 内 ~5-10 个 span（intent/llm/tool/turn 各 1-2 个）。批量也小。

## 11. 风险与缓解

| 风险 | 缓解 |
|------|------|
| `with start_span` 在同步函数内调用、外层无 event loop | _publish_span_completed 用 `asyncio.get_running_loop()` 探测；无 loop 时静默 skip。本子项目的所有埋点都在 async 路径上。 |
| `asyncio.create_task` 投出后没人 await 主循环退出时被取消丢失 | 该投递是 fire-and-forget，丢失可接受；不影响业务正确性。RuntimeTraceSubscriber.drain() 在 lifecycle shutdown 调用。 |
| MemoryIngestionSubscriber 同时订阅 SpanCompleted 和老 TOOL_INVOCATION_COMPLETED 导致同一事件被翻译两次 | 本子项目内 ToolInvocationService **只发新事件**；MemoryIngestionSubscriber 翻译 SpanCompleted 走新路径，翻译 TOOL_INVOCATION_COMPLETED 走老路径——两路径同一时刻只有一路被触发，不会重复翻译。 |
| trace_turns 复杂字段（continued_from_turn_id 等）在 attributes 里类型变松 | `_record_turn` handler 内做 schema 验证 + 默认值兜底；测试覆盖关键字段缺失场景。 |
| 业务侧某处忘了 `with start_span` 包裹 | 阶段 7 最后跑 grep `_runtime_trace_store\.upsert_` 必须为 0；加 deprecated 标注于 store API。 |
| Span attribute 类型不安全（Mapping[str, Any]） | 由 RuntimeTraceSubscriber handler 内做强类型转换并验证；handler 异常被 _safe_project 吃掉、记日志。 |
| publish_span 失败但 trace_id 已嵌入下游事件（比如 ToolInvocationCompleted）→ trace 投影丢失但 memory 路径有 trace_id | trace 投影是 best-effort，丢失少量 span 不影响 memory 数据完整性。后续如果要严格保证可加 outbox 模式（D 子项目）。 |
| 阶段 3-6 中间状态：部分 producer 已切 SpanCompleted、部分仍直写 trace_store | 中间状态可接受：trace 数据仍写入，仅来源混合；新订阅者写入与旧直写并不冲突（idempotent INSERT/UPDATE）。 |

## 12. Open Questions

（无遗留 open questions —— 评审过程中所有问题已决定。）

- attribute 继承：原 Q1 已决定 = 不自动继承，但 `turn_id` 例外（`start_span/start_async_span` 内部从父 span 自动继承），见 §5。
- cancelled vs error：原 Q2 已决定 = `asyncio.CancelledError` 统一映射到 `status="cancelled"` 并 re-raise，见 §5。

## 13. 评审记录

2026-05-05 经 spec-document-reviewer 评审，已修复以下问题：

**Critical**：

- C1: `start_span` 仅有 sync `@contextmanager`，但 §7.2 task_lifecycle 需要 `async with`。新增 `start_async_span()` `@asynccontextmanager` 变体，与 sync 版本共享 Span 类、contextvars、publish 路径（§5）。
- C2: cancellation 语义未定义。`start_span` / `start_async_span` 显式捕获 `asyncio.CancelledError` → `set_status("cancelled")` + re-raise；其他 `BaseException` → `record_exception`（§5）。
- C3: `SpanCompleted` ↔ `TraceSpanRecord` 字段覆盖缺口。§4 新增"通用字段"表，列出 `attempt_index/retry_count/iteration/execution_agent_id/run_id/run_revision`。

**Important**：

- I1: 27 处迁移点未列全。§7.5b 新增完整 24 处清单（实际计数）。
- I2: lifecycle 顺序未明。§6.2 显式定义 shutdown 顺序：业务 stop → tracing.drain_pending → subscriber.stop → bus.stop。
- I3: `_track_pending` 引用未定义。§5 增加模块级 `_PENDING: set[Task]` + `_track_pending` + `drain_pending()`。
- I4: trace_turns ON CONFLICT 语义。§7.7 决定"每次 turn span 携带完整 turn 状态"，UPDATE 整行（依赖原直写已有此模式）。
- I5: 同步 publish 逃生通道。§5 `start_span/start_async_span` 增加 `delivery="async" | "sync"` 参数；async 变体在 sync 模式下 await publish 完成；sync 变体 sync 模式降级为 async（同步 contextmanager 无法 await）。

**Minor**：

- §5 `_resolve_event_bus` 用 `hasattr(bus, "publish")` 替代 `type(bus).__name__ == "object"` 哨兵，更稳健。
- `turn_id` 自动继承：嵌套 span 自动从父 span 拷贝（§5），减少业务遗忘。
- §6.1 trace_spans.turn_id NOT NULL 约束保留，订阅者侧 fallback 到 trace_id 而非空字符串。
