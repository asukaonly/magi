# Event 信封改造（producer-assigned event_id + trace_context）设计

日期：2026-05-05
作者：asuka
子项目代号：**A**（事件信封改造，理想态架构子项目 1/4）

## 1. 背景

上一轮领域事件化重构（spec `2026-05-05-domain-event-refactor-design.md`）解决了 L4=0 的核心问题，但留下两个偏离点：runtime_trace 接管 / awareness 拆订阅者均未做。复盘根因：当前 Event 信封只有 `type / data / correlation_id`，缺少：

1. **producer-assigned `event_id`**：现 `MemoryEvent.event_id` 由 `normalize_runtime_event` 在 store 端生成，意味着同一 Event 被多个 store 消费时拿到不同 id，idempotency 不再 idempotent。
2. **trace_context（trace_id / span_id / parent_span_id）**：runtime_trace 树需要这些字段来还原拓扑；当前只能由各执行点直写 `runtime_trace.db` 实现。
3. **causation_id**：跨事件因果链丢失（同一 trace 内的 sibling 事件，从 span 树看不出谁触发谁）。

A 子项目补齐这三个信封字段并提供 contextvars 驱动的 span 工具，为 B/C/D 的订阅者重写打开通路。本子项目纯加法、不破坏现有契约。

## 2. 目标 / 非目标

### 目标

1. `magi.events.events.Event` 在 `__post_init__` 自动生成 ULID 形态的 `event_id`，producer 可显式覆盖。
2. Event 信封新增 `causation_id`（可选，指向触发本事件的上游 event_id）。
3. Event 信封新增 `trace_context: TraceContext | None`，由 contextvars 自动注入。
4. 提供 `magi.events.tracing` 模块：`TraceContext` 数据类、`current_trace_context()`、`start_span()` context manager。
5. `MemoryEvent` 新增镜像列 `causation_id / trace_id / span_id / parent_span_id`，从信封读取；L1 / L4 schema 增列（idempotent ALTER）。
6. `normalize_runtime_event` 改为**优先使用信封 `event_id`**，仅在缺失时 fallback 到 `generate_event_id()`。

### 非目标

- 不在本轮做业务路径埋点（`ToolInvocationService.invoke` / `TaskOrchestrator` / `ChatProjector` 等位置不调 `start_span()`）—— 留给 B 子项目。
- 不重写 awareness、不改 timeline / KG 写入路径 —— C 子项目。
- 不接管 runtime_trace 写入，旧直写代码原样保留 —— B 子项目。
- 不动 `domain_payloads.py` 中任何 payload —— trace 信息只走信封，不进 payload。
- 不动现有订阅者 / layer adapter 实现 —— 它们读 `event.event_id`、`event.trace_context` 即天然兼容。

## 3. 架构概览

```
┌──────────────────── Producer ─────────────────────┐
│  Event(type, data, correlation_id?, ...) 构造时   │
│   - __post_init__ 自动:                           │
│       event_id ← ULID() (若 producer 未传)         │
│       correlation_id ← event_id (若未传)           │
│       trace_context ← current_trace_context()     │
│         (contextvars 取，可能为 None)              │
└──────────────────────┬────────────────────────────┘
                       │
                       ▼
                 EventBus
                       │
                       ▼
┌──────────────────── Consumer ─────────────────────┐
│ normalize_runtime_event(event):                   │
│   - MemoryEvent.event_id ← event.event_id (信封)   │
│   - MemoryEvent.causation_id ← event.causation_id │
│   - MemoryEvent.trace_id ← event.trace_context     │
│         .trace_id (若有)                           │
│   - 同样 span_id / parent_span_id                  │
└────────────────────────────────────────────────────┘
```

`magi.events.tracing` 提供独立工具模块：

```
with start_span() as ctx:           # contextvars push
    # ctx.trace_id / span_id / parent_span_id 在闭包内可见
    await event_bus.publish(Event(...))   # __post_init__ 自动取 ctx
    await asyncio.create_task(child())    # asyncio 自动 fork ctx
                                          # → child 内仍能看见 parent
# context manager 出栈时自动 pop
```

## 4. Event 信封

```python
@dataclass
class Event:
    type: str
    data: Any
    timestamp: float = field(default_factory=time)
    source: str = "unknown"
    level: EventLevel = EventLevel.INFO
    correlation_id: Optional[str] = field(default=None)
    event_id: Optional[str] = field(default=None)        # 新
    causation_id: Optional[str] = field(default=None)    # 新
    trace_context: Optional["TraceContext"] = field(default=None)  # 新
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.event_id is None:
            self.event_id = str(ULID())
        if self.correlation_id is None:
            self.correlation_id = self.event_id
        if self.trace_context is None:
            from .tracing import current_trace_context
            self.trace_context = current_trace_context()
```

### 字段语义

| 字段 | 用途 | 默认 |
|------|------|------|
| `event_id` | 全局唯一标识本 Event；下游 store 直接用作主键，确保 idempotency | ULID() |
| `causation_id` | 指向触发本事件的上游 event_id；用于跨事件因果链重建 | None |
| `correlation_id` | 业务相关 id（保留原义）；未显式传入时 fallback 为 event_id（自串联） | event_id |
| `trace_context` | trace 树拓扑（trace_id/span_id/parent_span_id） | `current_trace_context()` |

### `to_dict` / `from_dict` 同步

二者扩展为持久化与还原所有信封字段。`trace_context` 序列化为嵌套 dict：

```python
"trace_context": {
    "trace_id": "...",
    "span_id": "...",
    "parent_span_id": "..." | None,
} | None
```

### `correlation_id` 语义微调

旧：`__post_init__` 中独立生成 UUID。
新：未显式传入时，`correlation_id = event_id`，等价于"事件自串联自己一条 chain"。已在用 correlation_id 串联多事件的代码（chat projector 用 turn_id，task_orchestrator 用 state.correlation_id）显式传入参数，不受影响。

## 5. tracing 模块

新建 `backend/src/magi/events/tracing.py`：

```python
from __future__ import annotations
import contextvars
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Optional
from ulid import ULID


@dataclass(frozen=True)
class TraceContext:
    trace_id: str
    span_id: str
    parent_span_id: Optional[str]


_current: contextvars.ContextVar[Optional[TraceContext]] = contextvars.ContextVar(
    "magi_trace_context", default=None,
)


def current_trace_context() -> Optional[TraceContext]:
    return _current.get()


@contextmanager
def start_span(*, trace_id: Optional[str] = None) -> Iterator[TraceContext]:
    """Open a new span scope.

    - If a parent context exists in contextvars: inherit its trace_id;
      parent_span_id = parent.span_id.
    - Else: start a new trace tree (trace_id auto-generated unless provided).
    """
    parent = _current.get()
    new_ctx = TraceContext(
        trace_id=trace_id or (parent.trace_id if parent else str(ULID())),
        span_id=str(ULID()),
        parent_span_id=parent.span_id if parent else None,
    )
    token = _current.set(new_ctx)
    try:
        yield new_ctx
    finally:
        _current.reset(token)
```

### 异步语义

`contextvars` 是 asyncio 默认隔离机制：

- `asyncio.create_task(child())` fork 当前 context，子任务能看到父 span。
- 同级 task 不互相污染（Python runtime 保证）。
- 跨 await 边界自动保留。

### 不在本轮做的

- `start_span()` 不接受 `name` / `attributes` 等参数 —— B 接入 OTel-style attributes 时再扩。
- 没有 `end_span()` 之类的命令式 API —— 强制用 context manager 控制生命周期。
- 没有 sampling、export hooks —— 这些是 B 的工作（subscriber 决定怎么投影）。

## 6. MemoryEvent 适配

### 6.1 字段扩展

`MemoryEvent` 新增（`backend/src/magi/memory/event_contracts.py`）：

```python
@dataclass(slots=True)
class MemoryEvent:
    # ... 现有字段 ...
    causation_id: Optional[str] = None        # 新
    trace_id: Optional[str] = None            # 新
    span_id: Optional[str] = None             # 新
    parent_span_id: Optional[str] = None      # 新
```

`to_dict()` 同步扩展。

### 6.2 normalize_runtime_event 行为变更

```python
def normalize_runtime_event(event, *, event_id=None, idempotency_key=None, parent_event_id=None):
    # 优先级:
    # 1. 显式参数 event_id（产线兼容性，给老调用方）
    # 2. event.event_id (信封)
    # 3. generate_event_id() (fallback，新代码不应触发)
    resolved_event_id = event_id or event.event_id or generate_event_id()
    
    # causation_id 优先用信封，再用 parent_event_id 参数兜底
    causation = event.causation_id or parent_event_id
    
    # trace_context → 三列
    tc = event.trace_context
    return MemoryEvent(
        event_id=resolved_event_id,
        causation_id=causation,
        trace_id=tc.trace_id if tc else None,
        span_id=tc.span_id if tc else None,
        parent_span_id=tc.parent_span_id if tc else None,
        # ... 其余字段不变 ...
    )
```

### 6.3 Schema 迁移

`backend/src/magi/memory/l1/storage/schema.py`（或同位置的 `ensure_*_schema`）：

```sql
ALTER TABLE fact_events ADD COLUMN causation_id TEXT;
ALTER TABLE fact_events ADD COLUMN trace_id TEXT;
ALTER TABLE fact_events ADD COLUMN span_id TEXT;
ALTER TABLE fact_events ADD COLUMN parent_span_id TEXT;
CREATE INDEX IF NOT EXISTS idx_fact_events_trace ON fact_events(trace_id);
CREATE INDEX IF NOT EXISTS idx_fact_events_causation ON fact_events(causation_id);
```

每条 ALTER 包 try/except 处理重复列（与 `pending_trace_count` / `deleted_at` 的现有迁移模式一致）。

L4 `l4_execution_traces` 同步加 `trace_id / span_id` 两列（不加 causation：trace 内已隐式表达）。

L1 store 的 INSERT 语句扩列；read 路径默认 SELECT * 自动带上。

## 7. 测试策略

### 7.1 单元

- `tests/events/test_event_envelope.py`
  - 默认 `event_id` 是 26 字符 ULID
  - producer 显式传 event_id 不被覆盖
  - producer 不传 correlation_id → fallback 为 event_id
  - producer 显式传 correlation_id → 不被 event_id 覆盖
  - causation_id 默认 None
  - to_dict / from_dict 往返不丢字段（含 trace_context）

- `tests/events/test_tracing.py`
  - `current_trace_context()` 在无 span 时返回 None
  - `start_span()` 内 → 返回非 None
  - 嵌套 span：子继承父 trace_id；parent_span_id == 父 span_id
  - context manager 退出后自动恢复
  - `asyncio.create_task` 内能看到父 ctx
  - 并发 task 之间 ctx 隔离
  - Event 在 span 内构造时自动取到 trace_context

- `tests/memory/test_event_contracts.py`
  - normalize 优先用信封 event_id
  - 显式参数 event_id 覆盖信封
  - 信封带 trace_context → MemoryEvent 三列填充
  - causation_id 镜像

### 7.2 集成

- `tests/integration/test_l4_end_to_end.py` 既有 3 个测试**全部不修改、全部通过**。
- 新增 `tests/integration/test_event_envelope_end_to_end.py`：
  - 在 `start_span()` 内连续构造两个 Event，B 的 `causation_id` 设为 A 的 `event_id`，publish 二者
  - 查 fact_events 表 → 两行 trace_id 一致、span_id 不同、第二行 causation_id == 第一行 event_id

### 7.3 schema migration

- 第一次 init 在空 DB 上跑，列存在
- 第二次 init 在已 migrate DB 上跑，不抛错（duplicate column ignored）
- 旧 db（无新列）能被新代码读取，缺列读出 None

## 8. 依赖

新增 `python-ulid` 到 `pyproject.toml`（约 50KB，纯 Python，无传递依赖）。

## 9. 错误隔离

- `__post_init__` 中 `current_trace_context()` 不应抛错；如果 contextvars 模块异常，trace_context 默认 None，不阻塞 Event 构造。
- ULID 生成失败（极端情况，时间倒退？）也用 try/except 包裹，fallback 到 `uuid4().hex`。
- normalize_runtime_event 容忍 `event.event_id` / `event.trace_context` 为 None（旧代码路径仍可工作）。

## 10. 性能

- `__post_init__` 增加 1 次 ULID 生成 + 1 次 contextvars get：单次 < 5μs。Event 构造频率本来就以 publish 为单位（< 1k QPS），影响可忽略。
- `start_span()` push/pop 是 contextvars `set` + `reset`：< 1μs 量级。
- schema 加列：SQLite ALTER 是元数据操作，无数据迁移。新列 nullable 不影响现有行。

## 11. 风险

| 风险 | 缓解 |
|------|------|
| `correlation_id` 默认值变化（旧 = 独立 UUID，新 = event_id）影响日志 / 监控 | 现有显式传 correlation_id 的代码不受影响。隐式生成路径只用于"未串联事件"，监控价值低。文档化变更。 |
| `from_dict` 反序列化老快照（无新字段） | 字段全 Optional + default=None，from_dict 缺 key 自动填 None |
| ULID 时钟单调依赖 | python-ulid 处理时钟回退；fallback 到 uuid4 兜底 |
| trace_context 进 contextvars 但用户在线程池里 publish | 线程池不自动 fork contextvars。用 `loop.run_in_executor` 时需 `contextvars.copy_context()` 包装。文档化此 caveat。生产代码主要是 asyncio，不受影响 |

## 12. 实施分阶段

按依赖顺序：

1. **依赖与工具**：加 python-ulid、写 tracing.py 与单元测试
2. **Event 信封**：扩字段、`__post_init__`、to_dict/from_dict、单元测试
3. **MemoryEvent 镜像**：MemoryEvent 加列、normalize 改造、单元测试
4. **Schema migration**：fact_events / l4_execution_traces ALTER + 测试
5. **集成回归**：跑 e2e、补 envelope 端到端测试

每阶段独立可发布；前一阶段失败不阻塞下一阶段（除 1 是其他所有阶段的依赖）。

## 13. Open Questions

- ULID 与 UUID4 共存：现有 `magi/memory/event_contracts.py::generate_event_id()` 用 `uuid4().hex` + 前缀（如 `evt_xxx`）。新代码 ULID 没有前缀。两种 id 字符串混存于 fact_events 是否影响某些字符串前缀检查？需要 grep `event_id.startswith("evt_")` 类用法。倾向：保留 generate_event_id 作 fallback，新代码不依赖前缀。
