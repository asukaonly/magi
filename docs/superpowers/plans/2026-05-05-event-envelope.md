# Event 信封改造 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 `magi.events.events.Event` 信封补上 producer-assigned `event_id` (ULID) + `causation_id` + `trace_context`，提供 `magi.events.tracing` 模块的 contextvars 驱动 span 工具，让 MemoryEvent / L1 schema 镜像新字段。纯加法、不动业务埋点。

**Architecture:** Event 在 `__post_init__` 自动生成 ULID 形态的 `event_id`，从 contextvars 取 `trace_context`；`correlation_id` 未传时 fallback 为 `event_id`。`magi/events/tracing.py` 用 `contextvars.ContextVar` + `@contextmanager` 提供 `start_span()`。`normalize_runtime_event` 优先取信封 `event_id`，kwarg 降为 legacy 兜底。L1 `fact_events` 表 ALTER 加 4 列 + 2 索引（idempotent）。L4 不加 trace 列（避免与既有 PK `trace_id` 冲突）。

**Tech Stack:** Python 3.10+, asyncio, dataclasses, contextvars, aiosqlite, pytest + pytest-asyncio。新增依赖 `python-ulid`（纯 Python，~50KB）。

**Spec:** `docs/superpowers/specs/2026-05-05-event-envelope-design.md`

**Repository conventions:**
- 工作目录 `/Users/asuka/code/magi/.claude/worktrees/l4-event-refactor`，所有路径相对此根
- 后端代码 `backend/src/magi/`，测试 `backend/tests/`
- 测试运行：`cd backend && pytest <path> -v`
- 新文件用 `from __future__ import annotations`
- 不写代码注释（只用模块 docstring）

---

## Chunk 1: 依赖与 tracing 模块

完成后 `magi.events.tracing` 可用、被单测覆盖；Event 类暂未改造。

### Task 1: 加 python-ulid 依赖

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: 编辑 pyproject.toml**

在 `backend/pyproject.toml` 的 `dependencies = [` 列表中、`pydantic-settings>=2.1.0` 这一类核心依赖块结尾，追加：

```toml
    # Identifiers
    "python-ulid>=2.2.0",
```

- [ ] **Step 2: 安装并验证**

```bash
cd backend && pip install -e . 2>&1 | tail -5
python -c "from ulid import ULID; print(str(ULID()))"
```

期望：输出一行 26 字符的 ULID 字符串。

- [ ] **Step 3: Commit**

```bash
git add backend/pyproject.toml
git commit -m "build(backend): add python-ulid dependency"
```

---

### Task 2: tracing 模块 + 单元测试

**Files:**
- Create: `backend/src/magi/events/tracing.py`
- Create: `backend/tests/events/test_tracing.py`

- [ ] **Step 1: 写失败测试**

`backend/tests/events/test_tracing.py`：

```python
from __future__ import annotations
import asyncio
import pytest
from magi.events.tracing import (
    TraceContext,
    current_trace_context,
    start_span,
)


def test_no_span_returns_none():
    assert current_trace_context() is None


def test_start_span_root():
    with start_span() as ctx:
        assert isinstance(ctx, TraceContext)
        assert ctx.trace_id is not None
        assert ctx.span_id is not None
        assert ctx.parent_span_id is None
        assert current_trace_context() is ctx


def test_start_span_nested_inherits_trace_id():
    with start_span() as parent:
        with start_span() as child:
            assert child.trace_id == parent.trace_id
            assert child.parent_span_id == parent.span_id
            assert child.span_id != parent.span_id
        assert current_trace_context() is parent


def test_context_restored_after_exit():
    with start_span() as outer:
        assert current_trace_context() is outer
    assert current_trace_context() is None


@pytest.mark.asyncio
async def test_create_task_inherits_context():
    captured: list[TraceContext | None] = []

    async def child():
        captured.append(current_trace_context())

    with start_span() as ctx:
        task = asyncio.create_task(child())
        await task

    assert captured[0] is not None
    assert captured[0].trace_id == ctx.trace_id


@pytest.mark.asyncio
async def test_gather_siblings_same_trace_distinct_spans():
    captured: list[TraceContext | None] = []

    async def sibling():
        with start_span() as s:
            captured.append(s)

    with start_span() as parent:
        await asyncio.gather(sibling(), sibling(), sibling())

    assert all(c is not None for c in captured)
    assert all(c.trace_id == parent.trace_id for c in captured)
    span_ids = {c.span_id for c in captured}
    assert len(span_ids) == 3


@pytest.mark.asyncio
async def test_concurrent_tasks_isolated():
    captured_a: TraceContext | None = None
    captured_b: TraceContext | None = None

    async def task_a():
        nonlocal captured_a
        with start_span() as ctx:
            await asyncio.sleep(0.01)
            captured_a = ctx

    async def task_b():
        nonlocal captured_b
        with start_span() as ctx:
            await asyncio.sleep(0.01)
            captured_b = ctx

    await asyncio.gather(task_a(), task_b())
    assert captured_a is not None and captured_b is not None
    assert captured_a.trace_id != captured_b.trace_id


def test_sync_function_in_async_span_sees_context():
    seen: list[TraceContext | None] = []

    def sync_helper():
        seen.append(current_trace_context())

    async def runner():
        with start_span():
            sync_helper()

    asyncio.run(runner())
    assert seen[0] is not None


def test_explicit_trace_id_creates_root_with_that_id():
    with start_span(trace_id="custom-trace-id") as ctx:
        assert ctx.trace_id == "custom-trace-id"
        assert ctx.parent_span_id is None
```

- [ ] **Step 2: 运行，期望 ImportError**

```bash
cd backend && pytest tests/events/test_tracing.py -v
```

- [ ] **Step 3: 实现**

`backend/src/magi/events/tracing.py`：

```python
"""Contextvars-driven span tracking for the event envelope.

Producers do not need to interact with this module directly: Event.__post_init__
reads `current_trace_context()` automatically. Business code that wants to open
a span (e.g. ToolInvocationService.invoke) uses `start_span()` as a context
manager. Sub-project B will integrate `start_span()` at business boundaries.
"""
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

- [ ] **Step 4: 运行，期望全过**

```bash
cd backend && pytest tests/events/test_tracing.py -v
```

期望：8 passed。

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/events/tracing.py backend/tests/events/test_tracing.py
git commit -m "feat(events): add contextvars-driven trace span helpers"
```

---

## Chunk 2: Event 信封字段

完成后 Event 自动带 event_id / trace_context；`from_dict` 支持反序列化。MemoryEvent 还没改。

### Task 3: Event 信封新增 4 字段

**Files:**
- Modify: `backend/src/magi/events/events.py:40-92`（Event 类）
- Create: `backend/tests/events/test_event_envelope.py`

- [ ] **Step 1: 写失败测试**

`backend/tests/events/test_event_envelope.py`：

```python
from __future__ import annotations
import pytest
from magi.events.events import Event, EventLevel
from magi.events.tracing import TraceContext, start_span


def test_default_event_id_is_nonempty_string():
    e = Event(type="X", data=None)
    assert isinstance(e.event_id, str)
    assert len(e.event_id) > 0


def test_explicit_event_id_preserved():
    e = Event(type="X", data=None, event_id="my-id")
    assert e.event_id == "my-id"


def test_correlation_defaults_to_event_id():
    e = Event(type="X", data=None)
    assert e.correlation_id == e.event_id


def test_explicit_correlation_id_preserved():
    e = Event(type="X", data=None, correlation_id="corr-1")
    assert e.correlation_id == "corr-1"
    assert e.event_id != "corr-1"


def test_causation_id_default_none():
    e = Event(type="X", data=None)
    assert e.causation_id is None


def test_explicit_causation_id_preserved():
    e = Event(type="X", data=None, causation_id="parent-evt")
    assert e.causation_id == "parent-evt"


def test_trace_context_default_none_outside_span():
    e = Event(type="X", data=None)
    assert e.trace_context is None


def test_trace_context_picked_up_inside_span():
    with start_span() as ctx:
        e = Event(type="X", data=None)
    assert e.trace_context is ctx


def test_explicit_trace_context_preserved_inside_span():
    explicit = TraceContext(trace_id="t", span_id="s", parent_span_id=None)
    with start_span():
        e = Event(type="X", data=None, trace_context=explicit)
    assert e.trace_context is explicit


def test_to_dict_round_trip_with_envelope_fields():
    explicit_tc = TraceContext(trace_id="t", span_id="s", parent_span_id="p")
    e = Event(
        type="X", data={"k": "v"},
        event_id="evt-1", correlation_id="corr-1",
        causation_id="caus-1", trace_context=explicit_tc,
    )
    d = e.to_dict()
    assert d["event_id"] == "evt-1"
    assert d["correlation_id"] == "corr-1"
    assert d["causation_id"] == "caus-1"
    assert d["trace_context"] == {
        "trace_id": "t", "span_id": "s", "parent_span_id": "p",
    }
    e2 = Event.from_dict(d)
    assert e2.event_id == "evt-1"
    assert e2.correlation_id == "corr-1"
    assert e2.causation_id == "caus-1"
    assert e2.trace_context == explicit_tc


def test_from_dict_missing_new_fields_fills_none():
    e = Event.from_dict({"type": "X", "data": None})
    assert e.event_id is not None  # auto-filled by __post_init__
    assert e.causation_id is None
    assert e.trace_context is None


def test_from_dict_with_null_trace_context():
    e = Event.from_dict({"type": "X", "data": None, "trace_context": None})
    assert e.trace_context is None
```

- [ ] **Step 2: 运行，期望失败**

```bash
cd backend && pytest tests/events/test_event_envelope.py -v
```

- [ ] **Step 3: 修改 Event 类**

读 `backend/src/magi/events/events.py` 当前的 Event 定义，找到 `@dataclass class Event:` 块。

修改 fields，按以下顺序：

```python
    type: str
    data: Any
    timestamp: float = field(default_factory=time)
    source: str = "unknown"
    level: EventLevel = EventLevel.INFO
    correlation_id: Optional[str] = field(default=None)
    event_id: Optional[str] = field(default=None)
    causation_id: Optional[str] = field(default=None)
    trace_context: Optional["TraceContext"] = field(default=None)
    metadata: Dict[str, Any] = field(default_factory=dict)
```

修改 `__post_init__` 为：

```python
    def __post_init__(self):
        if self.event_id is None:
            try:
                from ulid import ULID
                self.event_id = str(ULID())
            except Exception:
                import uuid
                self.event_id = uuid.uuid4().hex
        if self.correlation_id is None:
            self.correlation_id = self.event_id
        if self.trace_context is None:
            try:
                from .tracing import current_trace_context
                self.trace_context = current_trace_context()
            except Exception:
                self.trace_context = None
```

修改 `to_dict` 加 3 个字段：

```python
    def to_dict(self) -> Dict[str, Any]:
        tc = self.trace_context
        return {
            "type": self.type,
            "data": self.data,
            "timestamp": self.timestamp,
            "source": self.source,
            "level": self.level.value,
            "correlation_id": self.correlation_id,
            "event_id": self.event_id,
            "causation_id": self.causation_id,
            "trace_context": (
                {
                    "trace_id": tc.trace_id,
                    "span_id": tc.span_id,
                    "parent_span_id": tc.parent_span_id,
                }
                if tc is not None else None
            ),
            "metadata": self.metadata,
        }
```

修改 `from_dict` 加 3 个字段还原：

```python
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Event":
        from .tracing import TraceContext
        tc_dict = data.get("trace_context")
        tc = (
            TraceContext(
                trace_id=tc_dict["trace_id"],
                span_id=tc_dict["span_id"],
                parent_span_id=tc_dict.get("parent_span_id"),
            )
            if isinstance(tc_dict, dict) and tc_dict
            else None
        )
        return cls(
            type=data["type"],
            data=data["data"],
            timestamp=data.get("timestamp", time()),
            source=data.get("source", "unknown"),
            level=EventLevel(data.get("level", EventLevel.INFO)),
            correlation_id=data.get("correlation_id"),
            event_id=data.get("event_id"),
            causation_id=data.get("causation_id"),
            trace_context=tc,
            metadata=data.get("metadata", {}),
        )
```

- [ ] **Step 4: 运行新测试**

```bash
cd backend && pytest tests/events/test_event_envelope.py -v
```

期望：12 passed。

- [ ] **Step 5: 跑既有 events 测试，确认无回归**

```bash
cd backend && pytest tests/events/test_domain_payloads.py tests/events/test_event_types.py tests/events/test_payload_helpers.py tests/events/test_tracing.py -v
```

期望全过。

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/events/events.py backend/tests/events/test_event_envelope.py
git commit -m "feat(events): add event_id/causation_id/trace_context to Event envelope"
```

---

## Chunk 3: MemoryEvent 镜像 + normalize 改造

完成后 MemoryEvent 带新字段；normalize 优先用信封 event_id。

### Task 4: MemoryEvent 加 4 字段 + normalize 改造

**Files:**
- Modify: `backend/src/magi/memory/event_contracts.py:128`（MemoryEvent 类）
- Modify: `backend/src/magi/memory/event_contracts.py:200-244`（normalize_runtime_event）
- Create: `backend/tests/memory/test_event_contracts_envelope.py`

- [ ] **Step 1: 写失败测试**

`backend/tests/memory/test_event_contracts_envelope.py`：

```python
from __future__ import annotations
import pytest
from magi.events.events import Event, EventLevel
from magi.events.tracing import TraceContext, start_span
from magi.memory.event_contracts import normalize_runtime_event, MemoryEvent


def _basic_event(**kw):
    return Event(
        type="UserMessage",
        data={"content": "hi", "session_id": "s", "user_id": "u"},
        source="chat",
        **kw,
    )


def test_envelope_event_id_preserved_through_normalize():
    e = _basic_event(event_id="ulid-from-producer")
    me = normalize_runtime_event(e)
    assert me.event_id == "ulid-from-producer"


def test_envelope_event_id_takes_priority_over_kwarg():
    e = _basic_event(event_id="ulid-from-producer")
    me = normalize_runtime_event(e, event_id="kwarg-id")
    # spec §6.2: envelope wins over kwarg
    assert me.event_id == "ulid-from-producer"


def test_kwarg_used_only_when_envelope_missing():
    e = _basic_event()
    e.event_id = None  # legacy path
    me = normalize_runtime_event(e, event_id="kwarg-id")
    assert me.event_id == "kwarg-id"


def test_causation_id_mirrored():
    e = _basic_event(causation_id="parent-evt-1")
    me = normalize_runtime_event(e)
    assert me.causation_id == "parent-evt-1"


def test_causation_kwarg_fallback():
    e = _basic_event()
    me = normalize_runtime_event(e, parent_event_id="legacy-parent")
    assert me.causation_id == "legacy-parent"


def test_trace_context_split_into_three_columns():
    tc = TraceContext(trace_id="trace-x", span_id="span-y", parent_span_id="parent-z")
    e = _basic_event(trace_context=tc)
    me = normalize_runtime_event(e)
    assert me.trace_id == "trace-x"
    assert me.span_id == "span-y"
    assert me.parent_span_id == "parent-z"


def test_no_trace_context_yields_none_columns():
    e = _basic_event()
    me = normalize_runtime_event(e)
    assert me.trace_id is None
    assert me.span_id is None
    assert me.parent_span_id is None


def test_inside_span_event_normalize_picks_up_trace_columns():
    with start_span() as ctx:
        e = _basic_event()
    me = normalize_runtime_event(e)
    assert me.trace_id == ctx.trace_id
    assert me.span_id == ctx.span_id
    assert me.parent_span_id == ctx.parent_span_id
```

- [ ] **Step 2: 运行，期望失败**

```bash
cd backend && pytest tests/memory/test_event_contracts_envelope.py -v
```

- [ ] **Step 3: 扩展 MemoryEvent 字段**

读 `backend/src/magi/memory/event_contracts.py:128-160`（MemoryEvent dataclass）。在现有字段末尾、`embedding_profile_id` 之后加 4 个新字段（全 Optional + default=None）：

```python
    embedding_profile_id: Optional[str] = None
    causation_id: Optional[str] = None
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    parent_span_id: Optional[str] = None
```

注意：`MemoryEvent` 是 `@dataclass(slots=True)`，新增字段必须在所有 default 字段中保持顺序合法。如果有非 default 字段在新字段后面会报错，把新字段加到所有 default 字段集合的末尾。

- [ ] **Step 4: 扩展 to_dict()**

在 `MemoryEvent.to_dict` 末尾追加 4 个 key（保持字典顺序）：

```python
            "embedding_profile_id": self.embedding_profile_id,
            "causation_id": self.causation_id,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
        }
```

- [ ] **Step 5: 改造 normalize_runtime_event**

读现有 `normalize_runtime_event(event, *, event_id=None, idempotency_key=None, parent_event_id=None)` 实现（约 line 200-244）。

修改 event_id 解析顺序：

```python
    # 优先级: 信封 event_id > 显式 kwarg > generate_event_id() (fallback)
    resolved_event_id = event.event_id or event_id or generate_event_id()
```

修改 causation 解析：

```python
    causation = event.causation_id or parent_event_id
```

修改 MemoryEvent 构造，加 4 个字段：

```python
    tc = event.trace_context
    return MemoryEvent(
        event_id=str(resolved_event_id),
        # ... existing fields unchanged ...
        causation_id=causation,
        trace_id=tc.trace_id if tc else None,
        span_id=tc.span_id if tc else None,
        parent_span_id=tc.parent_span_id if tc else None,
    )
```

确保 `event.event_id` / `event.causation_id` / `event.trace_context` 字段都存在（Chunk 2 已加）。

- [ ] **Step 6: 运行新测试**

```bash
cd backend && pytest tests/memory/test_event_contracts_envelope.py -v
```

期望 8 passed。

- [ ] **Step 7: 跑现有 memory 测试确认无回归**

```bash
cd backend && pytest tests/memory/test_event_translation.py tests/memory/subscribers/ tests/memory/layers/ tests/memory/test_layer_protocol.py tests/integration/test_l4_end_to_end.py -v
```

全过。

- [ ] **Step 8: Commit**

```bash
git add backend/src/magi/memory/event_contracts.py backend/tests/memory/test_event_contracts_envelope.py
git commit -m "feat(memory): mirror envelope event_id/causation/trace into MemoryEvent"
```

---

## Chunk 4: L1 schema 迁移

完成后 fact_events 表带 4 个新列 + 2 索引；L1 store 写入扩列。

### Task 5: L1 schema ALTER + 写入扩列

**Files:**
- Modify: `backend/src/magi/memory/l1/storage/schema.py`（加新 migration helper）
- Modify: `backend/src/magi/memory/l1/writes.py:78-130`（INSERT 扩列）
- Create: `backend/tests/memory/l1/test_envelope_migration.py`

- [ ] **Step 1: 看现状**

```bash
sed -n '14,55p' backend/src/magi/memory/l1/storage/schema.py
```

注意现有模式：每个 migration helper 是 `_ensure_*` 方法，先 `PRAGMA table_info` 查列、缺列才 ALTER。

```bash
grep -n "_ensure_event_identity_schema\|_ensure_metadata_json_column\|_ensure_embedding_status_columns\|async def initialize" backend/src/magi/memory/l1/*.py | head
```

找到 `initialize`（或类似）方法，确认它按顺序调用各 `_ensure_*` helper。新 helper 也要在那里被调到。

- [ ] **Step 2: 写失败测试**

`backend/tests/memory/l1/test_envelope_migration.py`：

```python
from __future__ import annotations
import pytest
import tempfile
from pathlib import Path
from magi.core.sqlite import sqlite_connection_async
from magi.memory.l1.storage.schema import L1EventSchemaMixin


class _Probe(L1EventSchemaMixin):
    pass


@pytest.mark.asyncio
async def test_envelope_columns_added_to_fact_events():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "l1.db")
        # bootstrap fact_events with the bare current schema
        async with sqlite_connection_async(db_path) as db:
            await db.execute(
                """
                CREATE TABLE fact_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    correlation_id TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    created_at REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_item_id TEXT,
                    idempotency_key TEXT,
                    memory_domain INTEGER NOT NULL,
                    ingest_target INTEGER NOT NULL,
                    cognition_eligible INTEGER NOT NULL DEFAULT 0,
                    tom_depth INTEGER NOT NULL DEFAULT 1,
                    retention_class INTEGER NOT NULL DEFAULT 2,
                    session_id TEXT,
                    turn_id TEXT,
                    user_id TEXT,
                    task_id TEXT,
                    content TEXT NOT NULL,
                    author_type TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    importance_score REAL NOT NULL DEFAULT 0.5,
                    level INTEGER NOT NULL DEFAULT 1,
                    media_path TEXT
                )
                """
            )
            await db.commit()

        probe = _Probe()
        async with sqlite_connection_async(db_path) as db:
            await probe._ensure_envelope_columns(db)
            await db.commit()

        async with sqlite_connection_async(db_path) as db:
            async with db.execute("PRAGMA table_info(fact_events)") as cur:
                cols = {row[1] for row in await cur.fetchall()}
        for name in ("causation_id", "trace_id", "span_id", "parent_span_id"):
            assert name in cols


@pytest.mark.asyncio
async def test_envelope_migration_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "l1.db")
        async with sqlite_connection_async(db_path) as db:
            await db.execute(
                "CREATE TABLE fact_events ("
                " id INTEGER PRIMARY KEY, event_id TEXT NOT NULL UNIQUE,"
                " correlation_id TEXT NOT NULL, timestamp REAL NOT NULL,"
                " created_at REAL NOT NULL, event_type TEXT NOT NULL,"
                " source TEXT NOT NULL, memory_domain INTEGER NOT NULL,"
                " ingest_target INTEGER NOT NULL, content TEXT NOT NULL,"
                " author_type TEXT NOT NULL, content_type TEXT NOT NULL"
                ")"
            )
            await db.commit()

        probe = _Probe()
        # run twice, must not raise
        for _ in range(2):
            async with sqlite_connection_async(db_path) as db:
                await probe._ensure_envelope_columns(db)
                await db.commit()
```

- [ ] **Step 3: 运行，期望失败**

```bash
cd backend && pytest tests/memory/l1/test_envelope_migration.py -v
```

期望：`AttributeError: '_Probe' object has no attribute '_ensure_envelope_columns'`。

- [ ] **Step 4: 实现 migration helper**

在 `backend/src/magi/memory/l1/storage/schema.py` 的 `L1EventSchemaMixin` 类内、其它 `_ensure_*` helpers 之后追加：

```python
    async def _ensure_envelope_columns(self, db: aiosqlite.Connection) -> None:
        async with db.execute(f"PRAGMA table_info({FACT_EVENTS_TABLE})") as cursor:
            columns = {str(row[1]) for row in await cursor.fetchall()}
        for column_name in ("causation_id", "trace_id", "span_id", "parent_span_id"):
            if column_name not in columns:
                await db.execute(
                    f"ALTER TABLE {FACT_EVENTS_TABLE} ADD COLUMN {column_name} TEXT"
                )
        await db.execute(
            f"CREATE INDEX IF NOT EXISTS idx_fact_events_trace ON {FACT_EVENTS_TABLE}(trace_id)"
        )
        await db.execute(
            f"CREATE INDEX IF NOT EXISTS idx_fact_events_causation ON {FACT_EVENTS_TABLE}(causation_id)"
        )
```

- [ ] **Step 5: 在初始化流程中调用新 helper**

```bash
grep -n "_ensure_event_identity_schema\|_ensure_metadata_json_column\|_ensure_embedding_status_columns" backend/src/magi/memory/l1/storage/schema.py backend/src/magi/memory/l1/*.py | grep -v "def "
```

找到调用这些 helper 的位置（通常在 L1EventStore.initialize 或 schema.ensure_l1_schema），在最末尾追加：

```python
        await self._ensure_envelope_columns(db)
```

- [ ] **Step 6: 运行测试**

```bash
cd backend && pytest tests/memory/l1/test_envelope_migration.py -v
```

期望 2 passed。

- [ ] **Step 7: 扩展 INSERT 语句**

读 `backend/src/magi/memory/l1/writes.py:80-130` 的 INSERT。INSERT 列表加 4 个新列；VALUES 占位符同步加 4 个；参数 tuple 加 4 个 `event.causation_id / event.trace_id / event.span_id / event.parent_span_id`：

```python
            cursor = await db.execute(
                f"""
                INSERT OR IGNORE INTO {FACT_EVENTS_TABLE}(
                    event_id, correlation_id, timestamp, created_at,
                    event_type, source, source_item_id, idempotency_key, memory_domain, ingest_target,
                    cognition_eligible, tom_depth, retention_class, session_id, turn_id, user_id,
                    task_id, content, author_type, content_type, importance_score,
                    level, media_path, metadata_json, embedding_status, embedding_profile_id,
                    embedding_chunk_count, last_embedded_at, deleted_at,
                    causation_id, trace_id, span_id, parent_span_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    # ... existing 29 values ...
                    event.causation_id,
                    event.trace_id,
                    event.span_id,
                    event.parent_span_id,
                ),
            )
```

注意：占位符总数从 29 变 33；`# ... existing 29 values ...` 那一段保留原样，仅在末尾追加 4 个。

- [ ] **Step 8: 跑既有 L1 测试 + 集成测试**

```bash
cd backend && pytest tests/memory/l1/ tests/memory/test_event_translation.py tests/integration/test_l4_end_to_end.py -v
```

全过。

- [ ] **Step 9: Commit**

```bash
git add backend/src/magi/memory/l1/storage/schema.py backend/src/magi/memory/l1/writes.py backend/tests/memory/l1/test_envelope_migration.py
git commit -m "feat(memory): add fact_events envelope columns + idempotent migration"
```

---

## Chunk 5: 集成回归 + envelope 端到端测试

完成后既有所有集成测试通过；新增的"两个事件因果链 + fan-out idempotency"测试通过。

### Task 6: 端到端 envelope 测试

**Files:**
- Create: `backend/tests/integration/test_event_envelope_end_to_end.py`

- [ ] **Step 1: 写测试**

`backend/tests/integration/test_event_envelope_end_to_end.py`：

```python
"""End-to-end: envelope event_id / causation_id / trace_context flow into L1."""
from __future__ import annotations
import asyncio
import sqlite3
import tempfile
from pathlib import Path

import pytest

from magi.events.events import Event
from magi.events.in_memory_backend import InMemoryMessageBusBackend
from magi.events.tracing import start_span
from magi.memory import UnifiedMemoryStore
from magi.memory.subscribers.memory_ingestion_subscriber import MemoryIngestionSubscriber


async def _setup():
    bus = InMemoryMessageBusBackend()
    await bus.start()
    tmp = tempfile.TemporaryDirectory()
    base = Path(tmp.name)
    store = UnifiedMemoryStore(
        l1_db_path=str(base / "l1_events.db"),
        memory_db_path=str(base / "memory.db"),
        persist_dir=str(base / "memories"),
        l2_batch_flush_interval_seconds=0,
    )
    await store.initialize()
    sub = MemoryIngestionSubscriber(event_bus=bus, unified_memory=store)
    await sub.start()
    return bus, store, sub, tmp, base


async def _teardown(bus, store, sub, tmp):
    await sub.stop()
    await store.shutdown()
    await bus.stop()
    tmp.cleanup()


@pytest.mark.asyncio
async def test_envelope_event_id_lands_in_fact_events():
    bus, store, sub, tmp, base = await _setup()
    try:
        e = Event(
            type="UserMessage",
            data={"content": "hi", "session_id": "s", "user_id": "u"},
            source="chat",
        )
        envelope_id = e.event_id
        await bus.publish(e)
        await asyncio.sleep(0.05)
        await sub.drain()

        conn = sqlite3.connect(str(base / "l1_events.db"))
        try:
            row = conn.execute(
                "SELECT event_id FROM fact_events WHERE event_id = ?", (envelope_id,)
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row[0] == envelope_id
    finally:
        await _teardown(bus, store, sub, tmp)


@pytest.mark.asyncio
async def test_causation_chain_persisted():
    bus, store, sub, tmp, base = await _setup()
    try:
        with start_span():
            a = Event(
                type="UserMessage",
                data={"content": "first", "session_id": "s", "user_id": "u"},
                source="chat",
            )
            await bus.publish(a)

            b = Event(
                type="UserMessage",
                data={"content": "second", "session_id": "s", "user_id": "u"},
                source="chat",
                causation_id=a.event_id,
            )
            await bus.publish(b)

        await asyncio.sleep(0.1)
        await sub.drain()

        conn = sqlite3.connect(str(base / "l1_events.db"))
        try:
            rows = conn.execute(
                "SELECT event_id, causation_id, trace_id FROM fact_events "
                "WHERE event_id IN (?, ?) ORDER BY content",
                (a.event_id, b.event_id),
            ).fetchall()
        finally:
            conn.close()

        rows_by_id = {r[0]: r for r in rows}
        assert rows_by_id[a.event_id][1] is None
        assert rows_by_id[b.event_id][1] == a.event_id
        # both share same trace_id (entered via start_span)
        assert rows_by_id[a.event_id][2] is not None
        assert rows_by_id[a.event_id][2] == rows_by_id[b.event_id][2]
    finally:
        await _teardown(bus, store, sub, tmp)


@pytest.mark.asyncio
async def test_fanout_does_not_duplicate_event_id():
    """Publishing the same Event twice must yield a single fact_events row
    (idempotency via INSERT OR IGNORE on UNIQUE event_id)."""
    bus, store, sub, tmp, base = await _setup()
    try:
        e = Event(
            type="UserMessage",
            data={"content": "once", "session_id": "s", "user_id": "u"},
            source="chat",
        )
        await bus.publish(e)
        await bus.publish(e)
        await asyncio.sleep(0.1)
        await sub.drain()

        conn = sqlite3.connect(str(base / "l1_events.db"))
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM fact_events WHERE event_id = ?",
                (e.event_id,),
            ).fetchone()[0]
        finally:
            conn.close()

        assert count == 1
    finally:
        await _teardown(bus, store, sub, tmp)
```

- [ ] **Step 2: 运行**

```bash
cd backend && pytest tests/integration/test_event_envelope_end_to_end.py -v
```

期望 3 passed。

如果第二个测试（causation chain）的 b.event_id 与 a.event_id 因 `start_span` 内构造而共享 trace_id 但 span_id 不同——这就是预期行为。

如果第三个测试（fanout dedup）失败，可能因为 publish 同一 Event 实例两次时 ingestion_subscriber 把它当做两次事件，但底层 INSERT OR IGNORE 已经 dedupe，所以查 fact_events 仍是 1 行——只要这个不变即测试通过。

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_event_envelope_end_to_end.py
git commit -m "test(integration): verify envelope event_id/causation/trace flow"
```

---

### Task 7: 全量回归

- [ ] **Step 1: 跑触及范围内的全部测试**

```bash
cd backend && pytest tests/events/ tests/memory/ tests/integration/ tests/agent/execution/ tests/chat/ -v 2>&1 | tail -25
```

期望：之前所有通过的测试仍然通过；新加的（envelope / tracing / migration / e2e）一并通过。

如有 pre-existing failure（screen_time plugin 等），可忽略；新引入的 failure 必须修。

- [ ] **Step 2: 检查 grep**

```bash
grep -rn "generate_event_id" backend/src --include="*.py" | grep -v "__pycache__" | head
```

确认 `generate_event_id` 仅在 `event_contracts.py` 和必要 fallback 处出现。如有大量调用方仍主动传 event_id kwarg，记入 §13 的 Open Questions（实施时不强制清理，B 子项目处理）。

- [ ] **Step 3: 最终 commit fence**

无新代码。报告本 plan 完成。

---

## 风险与回退点

每个 Chunk 末尾是天然 commit fence：

- Chunk 1 失败：纯加法，直接回退 commit
- Chunk 2 失败：可能影响所有 Event 构造路径；回退 commit
- Chunk 3 失败：MemoryEvent slots dataclass 字段顺序敏感——可能需要把新字段加在合适位置；如果集成测试挂，回退 chunk 3 commit
- Chunk 4 失败：schema migration 一旦跑过、deleted_at 列已存在；幂等保证多次运行无害，本地数据库可放心
- Chunk 5 失败：不影响生产路径，仅是新测试不过；调试

特别留意：
- `MemoryEvent(slots=True)` 加新字段 → 要重启 Python 进程（slots 在加载时固化）
- 如果 chunk 2 后某个测试因 `correlation_id` 变化（旧 = 独立 UUID，新 = event_id）失败：检查测试是否在断言"correlation_id != event_id"，按 spec §4 这是有意行为变更，调整测试
