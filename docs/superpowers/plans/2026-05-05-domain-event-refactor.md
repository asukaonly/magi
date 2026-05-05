# 领域事件化重构与 L4 数据落地 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让工具执行 / 任务生命周期成为系统级领域事件，memory 子系统改为订阅者，打通 L4 写入链路并补上 L4 周期维护。

**Architecture:** 复用现有 `magi/events/InMemoryMessageBusBackend`。新增强类型 dataclass payload + `ToolInvocationService` 收口工具执行 + `MemoryIngestionSubscriber` / `RuntimeTraceSubscriber` 两个订阅者。`UnifiedMemoryStore.ingest_event` 改为按 layer.accepts() fan-out，layer 各自声明感兴趣事件类型与是否需要写锁。L4 新增 maintenance schedule。

**Tech Stack:** Python 3.10+, asyncio, dataclasses, aiosqlite, pytest + pytest-asyncio。

**Spec:** `docs/superpowers/specs/2026-05-05-domain-event-refactor-design.md`

**Repository conventions:**
- 工作目录 `/Users/asuka/code/magi`，所有路径以此为根
- 后端代码 `backend/src/magi/`，测试 `backend/tests/`
- 测试运行：`cd backend && pytest <path> -v`
- 新增模块都用 `from __future__ import annotations`
- 依赖注入风格：通过构造函数显式传入，不用全局单例

---

## Chunk 1: 领域事件契约（基础设施）

本章只动 `magi/events/`，不接入任何业务路径，纯加法。完成后总线上还没有人发新事件，但 dataclass / EventTypes 常量 / payload helper 已就绪。

### Task 1: 强类型 payload dataclasses

**Files:**
- Create: `backend/src/magi/events/domain_payloads.py`
- Test: `backend/tests/events/test_domain_payloads.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/events/test_domain_payloads.py
from __future__ import annotations
import pytest
from magi.events.domain_payloads import (
    TaskContext,
    ToolError,
    ToolInvocationCompleted,
    TaskStarted,
    TaskCompleted,
    TaskFailed,
    UserMessageReceived,
    AssistantResponseProduced,
    SensorEventEmitted,
)


def test_tool_error_truncated_default_false():
    err = ToolError(type="ValueError", message="boom")
    assert err.truncated is False


def test_tool_invocation_completed_is_frozen():
    payload = ToolInvocationCompleted(
        tool_name="shell",
        tool_category="external_tool",
        success=True,
        duration_ms=12.5,
        started_at=1.0,
        finished_at=2.0,
        args_summary="ls",
        result_summary="ok",
        error=None,
        context=TaskContext(session_id="s", turn_id="t", task_id=None, user_id=None),
    )
    with pytest.raises(Exception):
        payload.tool_name = "x"  # frozen


def test_task_failed_requires_error():
    err = ToolError(type="X", message="m")
    payload = TaskFailed(
        task_id="t1", task_type="explore",
        started_at=1.0, finished_at=2.0,
        error=err,
        context=TaskContext(session_id=None, turn_id=None, task_id="t1", user_id=None),
    )
    assert payload.error is err


def test_user_message_received_metadata_default_empty():
    payload = UserMessageReceived(
        content="hi",
        context=TaskContext(session_id="s", turn_id="t", task_id=None, user_id="u"),
    )
    assert payload.metadata == {}
```

- [ ] **Step 2: Verify failure**

```bash
cd backend && pytest tests/events/test_domain_payloads.py -v
```

Expected: ImportError on `magi.events.domain_payloads`.

- [ ] **Step 3: Implement payloads**

```python
# backend/src/magi/events/domain_payloads.py
"""Strongly-typed payloads for domain events flowing through the EventBus.

These dataclasses are carried inside Event.data (the existing envelope).
Each subclass corresponds to a single EventTypes constant.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class ToolError:
    type: str
    message: str
    truncated: bool = False


@dataclass(frozen=True)
class TaskContext:
    session_id: Optional[str]
    turn_id: Optional[str]
    task_id: Optional[str]
    user_id: Optional[str]


@dataclass(frozen=True)
class ToolInvocationCompleted:
    tool_name: str
    tool_category: str
    success: bool
    duration_ms: float
    started_at: float
    finished_at: float
    args_summary: Optional[str]
    result_summary: Optional[str]
    error: Optional[ToolError]
    context: TaskContext


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
    summary: Optional[str]
    context: TaskContext


@dataclass(frozen=True)
class TaskFailed:
    task_id: str
    task_type: str
    started_at: float
    finished_at: float
    error: ToolError
    context: TaskContext


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

- [ ] **Step 4: Run tests**

```bash
cd backend && pytest tests/events/test_domain_payloads.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/events/domain_payloads.py backend/tests/events/test_domain_payloads.py
git commit -m "feat(events): add strongly-typed domain event payloads"
```

---

### Task 2: EventTypes 常量

**Files:**
- Modify: `backend/src/magi/events/events.py` (the `class EventTypes:` block, around line 94)
- Test: `backend/tests/events/test_event_types.py`

- [ ] **Step 1: Read current EventTypes**

```bash
sed -n '94,143p' /Users/asuka/code/magi/backend/src/magi/events/events.py
```

确认 `TASK_STARTED / TASK_COMPLETED / TASK_FAILED / ACTION_EXECUTED / USER_MESSAGE / AI_RESPONSE / SENSOR_EVENT` 都已经存在（events.py:107, 132-134）。本任务只新增不存在的常量。

- [ ] **Step 2: Write failing test**

```python
# backend/tests/events/test_event_types.py
from magi.events.events import EventTypes


def test_new_constants_present():
    assert EventTypes.TOOL_INVOCATION_COMPLETED == "ToolInvocationCompleted"
    assert EventTypes.USER_MESSAGE_RECEIVED == "UserMessageReceived"
    assert EventTypes.ASSISTANT_RESPONSE_PRODUCED == "AssistantResponseProduced"
    assert EventTypes.SENSOR_EVENT_EMITTED == "SensorEventEmitted"


def test_legacy_constants_still_present():
    assert EventTypes.ACTION_EXECUTED == "ActionExecuted"
    assert EventTypes.TASK_STARTED == "TaskStarted"
    assert EventTypes.USER_MESSAGE == "UserMessage"
```

- [ ] **Step 3: Run, expect failure**

```bash
cd backend && pytest tests/events/test_event_types.py -v
```

Expected: AttributeError on the new constants.

- [ ] **Step 4: Add constants**

Edit `backend/src/magi/events/events.py`. Inside `class EventTypes:` block add:

```python
    # Domain events introduced in 2026-05 refactor
    TOOL_INVOCATION_COMPLETED = "ToolInvocationCompleted"
    USER_MESSAGE_RECEIVED = "UserMessageReceived"
    ASSISTANT_RESPONSE_PRODUCED = "AssistantResponseProduced"
    SENSOR_EVENT_EMITTED = "SensorEventEmitted"
```

Place them after the existing constants but before any methods. Don't touch `ACTION_EXECUTED` / `TASK_STARTED` / `USER_MESSAGE` etc.

- [ ] **Step 5: Run tests**

```bash
cd backend && pytest tests/events/test_event_types.py -v
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/events/events.py backend/tests/events/test_event_types.py
git commit -m "feat(events): add new domain EventTypes constants"
```

---

### Task 3: payload helper `expect_payload`

**Files:**
- Create: `backend/src/magi/events/payload_helpers.py`
- Test: `backend/tests/events/test_payload_helpers.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/events/test_payload_helpers.py
from __future__ import annotations
import pytest
from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import ToolInvocationCompleted, TaskContext
from magi.events.payload_helpers import expect_payload, PayloadTypeError


def _sample_event() -> Event:
    return Event(
        type=EventTypes.TOOL_INVOCATION_COMPLETED,
        data=ToolInvocationCompleted(
            tool_name="x", tool_category="internal",
            success=True, duration_ms=1.0,
            started_at=1.0, finished_at=2.0,
            args_summary=None, result_summary=None, error=None,
            context=TaskContext(None, None, None, None),
        ),
    )


def test_expect_payload_returns_typed_payload():
    event = _sample_event()
    payload = expect_payload(event, ToolInvocationCompleted)
    assert payload.tool_name == "x"


def test_expect_payload_raises_on_wrong_type():
    event = Event(type="Foo", data={"not": "a dataclass"})
    with pytest.raises(PayloadTypeError):
        expect_payload(event, ToolInvocationCompleted)


def test_expect_payload_raises_when_data_is_none():
    event = Event(type="Foo", data=None)
    with pytest.raises(PayloadTypeError):
        expect_payload(event, ToolInvocationCompleted)
```

- [ ] **Step 2: Verify failure**

```bash
cd backend && pytest tests/events/test_payload_helpers.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement helper**

```python
# backend/src/magi/events/payload_helpers.py
"""Helpers for working with strongly-typed payloads carried in Event.data.

These do not change the Event class. The convention is: when an event type
is a domain event, Event.data contains exactly one of the payload dataclasses
defined in magi.events.domain_payloads.
"""
from __future__ import annotations
import logging
from typing import Type, TypeVar
from .events import Event

logger = logging.getLogger(__name__)
T = TypeVar("T")


class PayloadTypeError(TypeError):
    """Raised when Event.data is not the expected payload type."""


def expect_payload(event: Event, expected: Type[T]) -> T:
    """Return event.data cast to `expected`, raising PayloadTypeError on mismatch."""
    if not isinstance(event.data, expected):
        raise PayloadTypeError(
            f"event {event.type!r} expected payload {expected.__name__}, "
            f"got {type(event.data).__name__}"
        )
    return event.data
```

- [ ] **Step 4: Run tests**

```bash
cd backend && pytest tests/events/test_payload_helpers.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/events/payload_helpers.py backend/tests/events/test_payload_helpers.py
git commit -m "feat(events): add expect_payload helper for typed payloads"
```

---

### Task 4: Chunk 1 review

- [ ] **Step 1: Run all events tests**

```bash
cd backend && pytest tests/events/ -v
```

Expected: all green.

- [ ] **Step 2: Static type sanity**

```bash
cd backend && python -c "from magi.events.domain_payloads import *; from magi.events.payload_helpers import expect_payload; print('imports ok')"
```

- [ ] **Step 3: 复核 Spec §4.1-4.4**

确认每个 dataclass 的字段名与 spec 中的列表 1:1 一致。`correlation_id` **不**出现在 payload 上（外层 Event 持有）。

---

## Chunk 2: ToolInvocationService 与 RuntimeTraceSubscriber

完成后系统中第一次开始有人发 `ToolInvocationCompleted`，runtime_trace 同源订阅写入。**memory 路径暂未接入，下一章再做**。

### Task 5: 抽出现有 runtime_trace 写入接口

**Pre-step:** 先用 grep 把现在直写 `runtime_trace.db` 的代码全部找出来：

```bash
grep -rn "runtime_trace" /Users/asuka/code/magi/backend/src --include="*.py" | grep -v "__pycache__\|/runtime_trace/"
```

记录命中位置（预期在 `agent/execution/function_calling/tracing.py`、`agent/task_orchestration_workers.py` 等处）。这些位置在 Task 9 会改造为：直接写入接口保留 + 由订阅者调用。

**Files:**
- Read: `backend/src/magi/runtime_trace/`（确认 schema 与现有 record 函数）
- Create: `backend/src/magi/runtime_trace/recorder.py`（如不存在则新建薄封装）
- Test: `backend/tests/runtime_trace/test_recorder_signature.py`

- [ ] **Step 1: 探索现有 runtime_trace 模块**

```bash
ls /Users/asuka/code/magi/backend/src/magi/runtime_trace/
grep -n "^def\|^async def\|^class" /Users/asuka/code/magi/backend/src/magi/runtime_trace/*.py | head
```

如果已有形如 `record_tool_call(...)` 的函数，本任务**只是确认**现有签名能接受 `ToolInvocationCompleted` 的全部字段；如果没有就在 `recorder.py` 中新增。

- [ ] **Step 2: 写一个 smoke test**

```python
# backend/tests/runtime_trace/test_recorder_signature.py
"""Verifies the public recorder surface used by RuntimeTraceSubscriber."""
from magi.runtime_trace import recorder  # noqa: F401


def test_recorder_module_importable():
    # Just confirm the module exists and exports something usable.
    assert hasattr(recorder, "record_tool_invocation")
```

- [ ] **Step 3: 实现 / 包装**

如果模块里已有写入函数，在 `recorder.py` 暴露：

```python
# backend/src/magi/runtime_trace/recorder.py
"""Public recorder surface for runtime_trace writes.

This module is the only place RuntimeTraceSubscriber may import from.
Internal trace_tools / trace_runs writers live in this package.
"""
from __future__ import annotations
from magi.events.domain_payloads import (
    ToolInvocationCompleted, TaskStarted, TaskCompleted, TaskFailed,
)

# TODO(impl): import the actual existing writer; if missing, implement
# minimal sqlite write here using `sqlite_connection_async` per existing pattern.

async def record_tool_invocation(payload: ToolInvocationCompleted, *, correlation_id: str) -> None: ...
async def record_task_started(payload: TaskStarted, *, correlation_id: str) -> None: ...
async def record_task_completed(payload: TaskCompleted, *, correlation_id: str) -> None: ...
async def record_task_failed(payload: TaskFailed, *, correlation_id: str) -> None: ...
```

实施时填充函数体。注意 schema 字段不变，列名直接复用。

- [ ] **Step 4: 运行测试**

```bash
cd backend && pytest tests/runtime_trace/test_recorder_signature.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/runtime_trace/recorder.py backend/tests/runtime_trace/test_recorder_signature.py
git commit -m "feat(runtime_trace): expose recorder surface for subscriber wiring"
```

---

### Task 6: ToolInvocationService 与 InvocationContext

**Files:**
- Create: `backend/src/magi/agent/execution/tool_invocation_service.py`
- Test: `backend/tests/agent/execution/test_tool_invocation_service.py`

回看 spec §5。

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/agent/execution/test_tool_invocation_service.py
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock

from magi.agent.execution.tool_invocation_service import (
    InvocationContext,
    ToolCall,
    ToolInvocationService,
)
from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import ToolInvocationCompleted, TaskContext, ToolError


@pytest.fixture
def fake_bus():
    bus = MagicMock()
    bus.publish = AsyncMock(return_value=True)
    return bus


@pytest.fixture
def fake_registry():
    reg = MagicMock()
    return reg


@pytest.fixture
def ctx():
    return InvocationContext(
        tool_category="external_tool",
        task_context=TaskContext("s", "t", None, "u"),
        execution_context=MagicMock(),  # the underlying ToolExecutionContext
    )


@pytest.mark.asyncio
async def test_publishes_tool_invocation_completed_on_success(fake_bus, fake_registry, ctx):
    fake_result = MagicMock(success=True, error=None, error_code=None, data="ok")
    fake_registry.execute = AsyncMock(return_value=fake_result)

    svc = ToolInvocationService(fake_registry, fake_bus)
    result = await svc.invoke(ToolCall(name="shell", args={"cmd": "ls"}), ctx)

    assert result is fake_result
    fake_bus.publish.assert_awaited_once()
    event: Event = fake_bus.publish.await_args.args[0]
    assert event.type == EventTypes.TOOL_INVOCATION_COMPLETED
    payload: ToolInvocationCompleted = event.data
    assert payload.tool_name == "shell"
    assert payload.success is True
    assert payload.error is None
    assert payload.tool_category == "external_tool"
    assert event.correlation_id is not None  # auto-assigned by Event


@pytest.mark.asyncio
async def test_publishes_failure_payload_when_result_failed(fake_bus, fake_registry, ctx):
    fake_result = MagicMock(success=False, error="boom", error_code="E1", data=None)
    fake_registry.execute = AsyncMock(return_value=fake_result)

    svc = ToolInvocationService(fake_registry, fake_bus)
    await svc.invoke(ToolCall(name="x", args={}), ctx)

    event: Event = fake_bus.publish.await_args.args[0]
    payload: ToolInvocationCompleted = event.data
    assert payload.success is False
    assert payload.error is not None
    assert payload.error.message == "boom"


@pytest.mark.asyncio
async def test_publishes_and_reraises_when_execute_throws(fake_bus, fake_registry, ctx):
    fake_registry.execute = AsyncMock(side_effect=ValueError("kaboom"))

    svc = ToolInvocationService(fake_registry, fake_bus)
    with pytest.raises(ValueError):
        await svc.invoke(ToolCall(name="x", args={}), ctx)

    fake_bus.publish.assert_awaited_once()
    payload: ToolInvocationCompleted = fake_bus.publish.await_args.args[0].data
    assert payload.success is False
    assert payload.error is not None
    assert payload.error.type == "ValueError"


@pytest.mark.asyncio
async def test_publish_failure_does_not_break_caller(fake_bus, fake_registry, ctx):
    fake_registry.execute = AsyncMock(return_value=MagicMock(success=True, error=None))
    fake_bus.publish = AsyncMock(side_effect=RuntimeError("bus dead"))

    svc = ToolInvocationService(fake_registry, fake_bus)
    # must not raise — publish failure is swallowed
    await svc.invoke(ToolCall(name="x", args={}), ctx)
```

- [ ] **Step 2: Verify failure**

```bash
cd backend && pytest tests/agent/execution/test_tool_invocation_service.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement service**

```python
# backend/src/magi/agent/execution/tool_invocation_service.py
"""Single entry point for executing tools and publishing ToolInvocationCompleted.

All business code paths that previously called tool_registry.execute() directly
should now call ToolInvocationService.invoke() instead. tool_registry.execute()
remains the underlying mechanism but is treated as an internal API.
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import (
    TaskContext, ToolError, ToolInvocationCompleted,
)

logger = logging.getLogger(__name__)
_SUMMARY_LIMIT = 500


def _summarize(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    if len(text) <= _SUMMARY_LIMIT:
        return text
    return text[: _SUMMARY_LIMIT - 3] + "..."


@dataclass
class ToolCall:
    name: str
    args: Mapping[str, Any]


@dataclass
class InvocationContext:
    """Bundle of context needed by ToolInvocationService.

    `execution_context` is the underlying ToolExecutionContext that the
    tool_registry needs. `tool_category` and `task_context` are surfacing
    metadata for the published event.
    """
    tool_category: str
    task_context: TaskContext
    execution_context: Any  # ToolExecutionContext (avoid import cycle)


class ToolInvocationService:
    def __init__(self, tool_registry, event_bus):
        self._tool_registry = tool_registry
        self._event_bus = event_bus

    async def invoke(self, call: ToolCall, ctx: InvocationContext):
        started_at = time.time()
        started_mono = time.monotonic()
        success = False
        error_obj: Optional[ToolError] = None
        result = None
        try:
            result = await self._tool_registry.execute(call.name, call.args, ctx.execution_context)
            success = bool(getattr(result, "success", False))
            if not success:
                error_obj = ToolError(
                    type=str(getattr(result, "error_code", "ToolFailure") or "ToolFailure"),
                    message=str(getattr(result, "error", "") or "")[:1000],
                )
            return result
        except Exception as exc:
            error_obj = ToolError(
                type=type(exc).__name__,
                message=str(exc)[:1000],
            )
            raise
        finally:
            finished_at = time.time()
            duration_ms = (time.monotonic() - started_mono) * 1000
            try:
                payload = ToolInvocationCompleted(
                    tool_name=call.name,
                    tool_category=ctx.tool_category,
                    success=success,
                    duration_ms=duration_ms,
                    started_at=started_at,
                    finished_at=finished_at,
                    args_summary=_summarize(call.args),
                    result_summary=_summarize(getattr(result, "data", None)) if result is not None else None,
                    error=error_obj,
                    context=ctx.task_context,
                )
                await self._event_bus.publish(Event(
                    type=EventTypes.TOOL_INVOCATION_COMPLETED,
                    data=payload,
                    source="tool_invocation_service",
                ))
            except Exception:
                logger.exception("publish ToolInvocationCompleted failed")
```

- [ ] **Step 4: Run tests**

```bash
cd backend && pytest tests/agent/execution/test_tool_invocation_service.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/agent/execution/tool_invocation_service.py \
        backend/tests/agent/execution/test_tool_invocation_service.py
git commit -m "feat(agent): add ToolInvocationService"
```

---

### Task 7: 改造 4 个工具执行调用点

**Files (修改):**
- `backend/src/magi/agent/execution/function_calling/step_executor.py:141`（`_driver._execute_tool_call` 入口）
- `backend/src/magi/agent/execution/function_calling/tool_execution.py:190`（`host.tool_registry.execute`）
- `backend/src/magi/agent/task_orchestration_workers.py:66, 133`
- `backend/src/magi/agent/task_agents/chat/planning_service.py:320`

每处改造**思路相同**：原本直接 `await self._tool_registry.execute(name, args, exec_ctx)`，改为通过 `ToolInvocationService.invoke(ToolCall(name, args), InvocationContext(tool_category=..., task_context=..., execution_context=exec_ctx))`。

`tool_category` 在 4 处的取值：
- function_calling/step_executor.py / tool_execution.py：`"external_tool"`（这是给 chat LLM 暴露的工具）
- task_orchestration_workers.py：`"orchestrator_internal"`
- chat/planning_service.py：`"planning"`

`task_context` 字段从已有变量推导：
- function_calling 路径：`session_id` / `turn_id` 从函数入参拿，`task_id` 通常 None，`user_id` 从 ctx 拿
- task_orchestration：`task_id` 必有，`session_id` 从 task 上下文拿
- planning_service：同 chat 来源

**前置：** 在改之前 **再 grep 一次**确认无遗漏：

```bash
grep -rn "tool_registry\.execute\|_tool_registry\.execute" /Users/asuka/code/magi/backend/src --include="*.py" | grep -v "__pycache__\|test\|tool_invocation_service"
```

- [ ] **Step 1: 在每个 host class 注入 ToolInvocationService 依赖**

每个调用方类（FunctionCallingDriver / TaskOrchestrationWorker / PlanningService）的 `__init__` 加一个 `tool_invocation_service: ToolInvocationService` 参数；不直接持有 tool_registry / event_bus。需要追溯它们的实例化点（一般在 lifecycle.py 或 service builder 里），把构造换成传入 `ToolInvocationService(tool_registry, event_bus)`。

执行实施前先 grep：

```bash
grep -rn "FunctionCallingDriver\|TaskOrchestrationWorker\|PlanningService(" /Users/asuka/code/magi/backend/src --include="*.py" | grep -v "__pycache__\|test"
```

- [ ] **Step 2: 改写每个调用点**

以 `function_calling/tool_execution.py:190` 为例：

```python
# before
result = await host.tool_registry.execute(tool_name, arguments, context)

# after
from ....agent.execution.tool_invocation_service import (
    InvocationContext, ToolCall,
)
from ....events.domain_payloads import TaskContext

result = await host.tool_invocation_service.invoke(
    ToolCall(name=tool_name, args=arguments),
    InvocationContext(
        tool_category="external_tool",
        task_context=TaskContext(
            session_id=session_id,
            turn_id=turn_id,
            task_id=getattr(context, "task_id", None),
            user_id=user_id,
        ),
        execution_context=context,
    ),
)
```

其它三处按同样模式。

- [ ] **Step 3: 单元测试改造点不破坏现有功能**

每处都要有一个集成 / smoke 测试断言：调用之后 `event_bus.publish` 被以 `ToolInvocationCompleted` 触发了一次。如果原来已有针对该模块的测试，扩展之；否则新建：

```python
# backend/tests/agent/execution/function_calling/test_tool_execution_publishes.py
import pytest
from unittest.mock import AsyncMock, MagicMock
# ... mock host with tool_invocation_service ...
# ... call _execute_tool_call ...
# ... assert host.tool_invocation_service.invoke.await_count == 1
```

- [ ] **Step 4: 运行受影响的测试**

```bash
cd backend && pytest tests/agent/ -v -k "tool_execution or step_executor or task_orchestration or planning"
```

- [ ] **Step 5: 给 tool_registry.execute 加 deprecation 提示**

`backend/src/magi/tools/registry_execution.py:24` 的 `execute` 方法 docstring 末尾追加：

```
.. deprecated::
    Direct callers in business code MUST go through ToolInvocationService.
    Calling tool_registry.execute() directly bypasses ToolInvocationCompleted
    publication and breaks L4 / runtime_trace pipelines.
```

不加运行时 warning（避免噪音），靠 grep + code review 拦截。

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(agent): route all tool_registry.execute through ToolInvocationService"
```

---

### Task 8: RuntimeTraceSubscriber

**Files:**
- Create: `backend/src/magi/runtime_trace/subscribers/runtime_trace_subscriber.py`
- Create: `backend/src/magi/runtime_trace/subscribers/__init__.py`
- Test: `backend/tests/runtime_trace/test_runtime_trace_subscriber.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/runtime_trace/test_runtime_trace_subscriber.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from magi.runtime_trace.subscribers.runtime_trace_subscriber import RuntimeTraceSubscriber
from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import ToolInvocationCompleted, TaskContext


@pytest.mark.asyncio
async def test_subscribes_to_expected_event_types():
    bus = MagicMock()
    bus.subscribe = AsyncMock(return_value="sub-id")
    sub = RuntimeTraceSubscriber(event_bus=bus)
    await sub.start()
    types = {call.kwargs.get("event_type") or call.args[0] for call in bus.subscribe.await_args_list}
    assert EventTypes.TOOL_INVOCATION_COMPLETED in types
    assert EventTypes.TASK_STARTED in types
    assert EventTypes.TASK_COMPLETED in types
    assert EventTypes.TASK_FAILED in types


@pytest.mark.asyncio
async def test_dispatches_tool_invocation_to_recorder():
    bus = MagicMock()
    bus.subscribe = AsyncMock(return_value="sub-id")
    with patch("magi.runtime_trace.subscribers.runtime_trace_subscriber.recorder") as rec:
        rec.record_tool_invocation = AsyncMock()
        sub = RuntimeTraceSubscriber(event_bus=bus)
        await sub.start()
        payload = ToolInvocationCompleted(
            tool_name="x", tool_category="internal", success=True,
            duration_ms=1.0, started_at=1.0, finished_at=2.0,
            args_summary=None, result_summary=None, error=None,
            context=TaskContext(None, None, None, None),
        )
        await sub._on_tool_invocation_completed(Event(
            type=EventTypes.TOOL_INVOCATION_COMPLETED, data=payload,
            correlation_id="corr-1",
        ))
        await sub.drain()
        rec.record_tool_invocation.assert_awaited_once()
        assert rec.record_tool_invocation.await_args.kwargs["correlation_id"] == "corr-1"
```

- [ ] **Step 2: Verify failure**

```bash
cd backend && pytest tests/runtime_trace/test_runtime_trace_subscriber.py -v
```

- [ ] **Step 3: Implement subscriber**

```python
# backend/src/magi/runtime_trace/subscribers/__init__.py
```

```python
# backend/src/magi/runtime_trace/subscribers/runtime_trace_subscriber.py
"""Subscribes to domain events and writes them to runtime_trace.db.

Heavy work is offloaded to asyncio.create_task so the event bus publish
loop does not block. Tests can call drain() to await all inflight tasks.
"""
from __future__ import annotations
import asyncio
import logging
from typing import Set

from magi.events.events import Event, EventTypes
from magi.events.payload_helpers import expect_payload
from magi.events.domain_payloads import (
    ToolInvocationCompleted, TaskStarted, TaskCompleted, TaskFailed,
)
from magi.runtime_trace import recorder

logger = logging.getLogger(__name__)


class RuntimeTraceSubscriber:
    def __init__(self, event_bus):
        self._bus = event_bus
        self._sub_ids: list[str] = []
        self._inflight: Set[asyncio.Task] = set()

    async def start(self) -> None:
        self._sub_ids.append(await self._bus.subscribe(
            EventTypes.TOOL_INVOCATION_COMPLETED, self._on_tool_invocation_completed))
        self._sub_ids.append(await self._bus.subscribe(
            EventTypes.TASK_STARTED, self._on_task_started))
        self._sub_ids.append(await self._bus.subscribe(
            EventTypes.TASK_COMPLETED, self._on_task_completed))
        self._sub_ids.append(await self._bus.subscribe(
            EventTypes.TASK_FAILED, self._on_task_failed))

    async def stop(self) -> None:
        for sid in self._sub_ids:
            try:
                await self._bus.unsubscribe(sid)
            except Exception:
                logger.exception("unsubscribe failed")
        await self.drain()

    async def drain(self) -> None:
        if not self._inflight:
            return
        await asyncio.gather(*list(self._inflight), return_exceptions=True)

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _on_tool_invocation_completed(self, event: Event) -> None:
        payload = expect_payload(event, ToolInvocationCompleted)
        self._spawn(self._safe_record(
            recorder.record_tool_invocation, payload, event.correlation_id))

    async def _on_task_started(self, event: Event) -> None:
        payload = expect_payload(event, TaskStarted)
        self._spawn(self._safe_record(
            recorder.record_task_started, payload, event.correlation_id))

    async def _on_task_completed(self, event: Event) -> None:
        payload = expect_payload(event, TaskCompleted)
        self._spawn(self._safe_record(
            recorder.record_task_completed, payload, event.correlation_id))

    async def _on_task_failed(self, event: Event) -> None:
        payload = expect_payload(event, TaskFailed)
        self._spawn(self._safe_record(
            recorder.record_task_failed, payload, event.correlation_id))

    @staticmethod
    async def _safe_record(fn, payload, correlation_id):
        try:
            await fn(payload, correlation_id=correlation_id)
        except Exception:
            logger.exception("runtime_trace record failed: %s", fn.__name__)
```

- [ ] **Step 4: Run tests**

```bash
cd backend && pytest tests/runtime_trace/ -v
```

- [ ] **Step 5: 把 RuntimeTraceSubscriber 接入 lifecycle**

在主 lifecycle 启动顺序里实例化并 `start()`：找到 `magi/events/lifecycle.py` 或主应用启动文件（用 grep 找已有的 message_bus 启动点），在 message_bus 启动后启动 RuntimeTraceSubscriber，停止前先 stop（含 drain）。

```bash
grep -rn "message_bus.start\|InMemoryMessageBusBackend\b\|InMemoryMessageBusBackend(" /Users/asuka/code/magi/backend/src --include="*.py" | grep -v "__pycache__"
```

在 `__init__` lifecycle 里追加：

```python
self._runtime_trace_subscriber = RuntimeTraceSubscriber(self._event_bus)
await self._runtime_trace_subscriber.start()
# ... shutdown:
await self._runtime_trace_subscriber.stop()
```

- [ ] **Step 6: 删除老的 runtime_trace 直写代码**

把 Task 5 收集到的"直写 runtime_trace"调用点全部移除（function_calling/tracing.py 等）。**前提：** 所有走 ToolInvocationService 的路径已经通过 RuntimeTraceSubscriber 把 trace 落库了。验证方式：本地起服务 → 触发一次工具调用 → 查 `~/.magi/runtime/runtime_trace.db` 表，确认行数增加。

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(runtime_trace): add RuntimeTraceSubscriber, remove direct trace writes"
```

---

### Task 9: Chunk 2 集成验证

- [ ] **Step 1: 启动后端，触发一次工具调用，查 DB**

```bash
cd backend && python -m magi  # or whatever the run command is
# in another terminal: 触发任意工具调用（如让 chat 跑一次 read_file）
sqlite3 ~/.magi/runtime/runtime_trace.db "SELECT COUNT(*) FROM trace_tools;"
sqlite3 ~/.magi/data/memory/memory.db "SELECT COUNT(*) FROM procedural_skills;"
```

期望：runtime_trace 行数增加；memory.db 仍是 0（下一章才接入）。

- [ ] **Step 2: 验证 correlation_id 一致性**

同一次调用在 runtime_trace 与（未来的）memory 中应可通过 correlation_id join。本章只能验证 runtime_trace 那一边的写入包含 correlation_id 列。

- [ ] **Step 3: Chunk 2 commit fence**

到此 Chunk 2 完成。停下来人工 review。

---

## Chunk 3: MemoryIngestionSubscriber 与 producer 改造

完成后 chat projector / awareness 不再直调 `unified_memory.ingest_event`，全部改 publish。memory 侧统一由订阅者翻译为 MemoryEvent 并下发。**L4 写入开始有数据**（前提 L4 现有 record_memory_event 路径已经接受 ActionExecuted）。

### Task 10: 翻译表函数

**Files:**
- Create: `backend/src/magi/memory/event_translation.py`
- Test: `backend/tests/memory/test_event_translation.py`

回看 spec §7.1 与 `magi/memory/event_contracts.py`（已有 MemoryEvent 构造逻辑可参考）。

- [ ] **Step 1: 阅读 MemoryEvent 现有构造方式**

```bash
grep -n "class MemoryEvent\|def from_event\|EventTypes.ACTION_EXECUTED" /Users/asuka/code/magi/backend/src/magi/memory/event_contracts.py
```

确认 MemoryEvent 字段（event_type, source, source_item_id, content, metadata_json, level, ingest_target, cognition_eligible, session_id, user_id, task_id, ...）。

- [ ] **Step 2: Write failing tests**

```python
# backend/tests/memory/test_event_translation.py
from __future__ import annotations
import pytest
from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import (
    ToolInvocationCompleted, TaskContext, ToolError,
    UserMessageReceived, AssistantResponseProduced, SensorEventEmitted,
    TaskStarted, TaskCompleted, TaskFailed,
)
from magi.memory.event_translation import translate


def test_tool_invocation_completed_to_action_executed():
    payload = ToolInvocationCompleted(
        tool_name="shell", tool_category="external_tool",
        success=True, duration_ms=12.5,
        started_at=1.0, finished_at=2.0,
        args_summary="ls -la", result_summary="ok",
        error=None,
        context=TaskContext("sess-1", "turn-1", "task-1", "user-1"),
    )
    ev = Event(type=EventTypes.TOOL_INVOCATION_COMPLETED, data=payload, correlation_id="c1")
    me = translate(ev)
    assert me.event_type == EventTypes.ACTION_EXECUTED
    assert me.source_item_id == "shell"
    assert me.session_id == "sess-1"
    assert me.task_id == "task-1"
    assert me.user_id == "user-1"
    assert me.level == 1  # success → low
    assert me.metadata_json["duration_ms"] == 12.5
    assert me.metadata_json["input"] == "ls -la"
    assert me.metadata_json["output"] == "ok"
    assert me.correlation_id == "c1"


def test_tool_invocation_failure_records_error():
    err = ToolError(type="ValueError", message="boom")
    payload = ToolInvocationCompleted(
        tool_name="shell", tool_category="external_tool",
        success=False, duration_ms=1.0,
        started_at=1.0, finished_at=2.0,
        args_summary="x", result_summary=None, error=err,
        context=TaskContext("s", "t", None, None),
    )
    me = translate(Event(type=EventTypes.TOOL_INVOCATION_COMPLETED, data=payload))
    assert me.level >= 3  # failure
    assert me.metadata_json["error"] == "boom"


def test_user_message_received_translation():
    payload = UserMessageReceived(
        content="hi",
        context=TaskContext("s", "t", None, "u"),
        metadata={"author_type": "user"},
    )
    me = translate(Event(type=EventTypes.USER_MESSAGE_RECEIVED, data=payload))
    assert me.event_type == EventTypes.USER_MESSAGE
    assert me.content == "hi"
    assert me.session_id == "s"


def test_chat_event_with_null_session_warns_but_translates():
    # session_id None for non-chat sources is fine; for chat it must emit a warning.
    # Behavior: still translates, but logger.warning called. Easiest: just make
    # sure translate() does not raise.
    payload = UserMessageReceived(
        content="hi",
        context=TaskContext(None, "t", None, "u"),
    )
    me = translate(Event(type=EventTypes.USER_MESSAGE_RECEIVED, data=payload))
    assert me.session_id is None


def test_unknown_event_type_returns_none():
    me = translate(Event(type="NeverHeardOf", data=None))
    assert me is None
```

- [ ] **Step 3: Run, expect failure**

- [ ] **Step 4: Implement**

```python
# backend/src/magi/memory/event_translation.py
"""Translate domain events into MemoryEvent for ingestion."""
from __future__ import annotations
import logging
from typing import Optional

from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import (
    ToolInvocationCompleted, TaskContext, ToolError,
    TaskStarted, TaskCompleted, TaskFailed,
    UserMessageReceived, AssistantResponseProduced, SensorEventEmitted,
)
from .event_contracts import MemoryEvent  # existing class

logger = logging.getLogger(__name__)


def translate(event: Event) -> Optional[MemoryEvent]:
    handler = _DISPATCH.get(event.type)
    if handler is None:
        return None
    return handler(event)


def _from_tool_invocation(event: Event) -> MemoryEvent:
    p: ToolInvocationCompleted = event.data
    _check_session(p.context, source="tool")
    metadata = {
        "duration_ms": p.duration_ms,
        "input": p.args_summary,
        "output": p.result_summary,
        "error": p.error.message if p.error else None,
        "tool_category": p.tool_category,
        "started_at": p.started_at,
        "finished_at": p.finished_at,
    }
    level = 1 if p.success else 3
    return MemoryEvent(
        event_type=EventTypes.ACTION_EXECUTED,
        source="tool_invocation_service",
        source_item_id=p.tool_name,
        content=p.tool_name,
        level=level,
        session_id=p.context.session_id,
        turn_id=p.context.turn_id,
        task_id=p.context.task_id,
        user_id=p.context.user_id,
        metadata_json=metadata,
        correlation_id=event.correlation_id,
    )


def _from_user_message(event: Event) -> MemoryEvent:
    p: UserMessageReceived = event.data
    _check_session(p.context, source="chat", required=True)
    return MemoryEvent(
        event_type=EventTypes.USER_MESSAGE,
        source="chat_projector",
        content=p.content,
        session_id=p.context.session_id,
        turn_id=p.context.turn_id,
        user_id=p.context.user_id,
        metadata_json=dict(p.metadata),
        correlation_id=event.correlation_id,
    )


# ... similar for AssistantResponseProduced, SensorEventEmitted, TaskStarted/Completed/Failed


def _check_session(ctx: TaskContext, *, source: str, required: bool = False) -> None:
    if ctx.session_id is None and required:
        logger.warning("memory translate: %s event missing session_id", source)


_DISPATCH = {
    EventTypes.TOOL_INVOCATION_COMPLETED: _from_tool_invocation,
    EventTypes.USER_MESSAGE_RECEIVED: _from_user_message,
    # ... wire all six event types
}
```

实施时把每个分支补全。MemoryEvent 字段以 `event_contracts.py` 中现有定义为准（必要字段如 `ingest_target` / `memory_domain` 用 MemoryEvent 的默认值或显式传入；可参考现有 chat projector 的 MemoryEvent 构造方式）。

- [ ] **Step 5: Run, expect pass**

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/memory/event_translation.py backend/tests/memory/test_event_translation.py
git commit -m "feat(memory): add domain-event → MemoryEvent translation"
```

---

### Task 11: MemoryIngestionSubscriber

**Files:**
- Create: `backend/src/magi/memory/subscribers/__init__.py`
- Create: `backend/src/magi/memory/subscribers/memory_ingestion_subscriber.py`
- Test: `backend/tests/memory/subscribers/test_memory_ingestion_subscriber.py`

模板与 RuntimeTraceSubscriber 高度相似。要点：
- 订阅 6 类事件：`TOOL_INVOCATION_COMPLETED`, `TASK_STARTED`, `TASK_COMPLETED`, `TASK_FAILED`, `USER_MESSAGE_RECEIVED`, `ASSISTANT_RESPONSE_PRODUCED`, `SENSOR_EVENT_EMITTED`
- handler 内**只 create_task**，不直接 await ingest（spec §10.2）
- 暴露 `drain()` / `wait_idle()` 给测试

- [ ] **Step 1: 写测试**

```python
# backend/tests/memory/subscribers/test_memory_ingestion_subscriber.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from magi.memory.subscribers.memory_ingestion_subscriber import MemoryIngestionSubscriber
from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import ToolInvocationCompleted, TaskContext


@pytest.mark.asyncio
async def test_translates_and_calls_ingest():
    bus = MagicMock()
    bus.subscribe = AsyncMock(return_value="sub")
    unified = MagicMock()
    unified.ingest_event = AsyncMock()

    sub = MemoryIngestionSubscriber(event_bus=bus, unified_memory=unified)
    await sub.start()

    payload = ToolInvocationCompleted(
        tool_name="x", tool_category="external_tool",
        success=True, duration_ms=1.0,
        started_at=1.0, finished_at=2.0,
        args_summary=None, result_summary=None, error=None,
        context=TaskContext("s", "t", None, "u"),
    )
    await sub._on_tool_invocation_completed(
        Event(type=EventTypes.TOOL_INVOCATION_COMPLETED, data=payload, correlation_id="c"))
    await sub.drain()

    unified.ingest_event.assert_awaited_once()
    me = unified.ingest_event.await_args.args[0]
    assert me.event_type == EventTypes.ACTION_EXECUTED
    assert me.source_item_id == "x"


@pytest.mark.asyncio
async def test_handler_does_not_block_publisher():
    """ingest_event takes 200ms but the handler returns immediately."""
    bus = MagicMock()
    bus.subscribe = AsyncMock(return_value="sub")
    unified = MagicMock()

    async def slow_ingest(_me):
        await asyncio.sleep(0.2)
    unified.ingest_event = slow_ingest

    sub = MemoryIngestionSubscriber(event_bus=bus, unified_memory=unified)
    await sub.start()

    payload = ToolInvocationCompleted(
        tool_name="x", tool_category="t", success=True, duration_ms=1.0,
        started_at=1.0, finished_at=2.0,
        args_summary=None, result_summary=None, error=None,
        context=TaskContext(None, None, None, None))
    start = asyncio.get_event_loop().time()
    await sub._on_tool_invocation_completed(
        Event(type=EventTypes.TOOL_INVOCATION_COMPLETED, data=payload))
    elapsed = asyncio.get_event_loop().time() - start
    assert elapsed < 0.05  # handler returned without awaiting ingest

    await sub.drain()
```

- [ ] **Step 2: Implement**

依模板，handler 内 `self._spawn(self._unified.ingest_event(memory_event))`。`drain()` 与 RuntimeTraceSubscriber 同样实现。

- [ ] **Step 3: 运行测试**

- [ ] **Step 4: 接入 lifecycle**

在 `magi/memory/lifecycle.py` 的启动序列里加：

```python
from .subscribers.memory_ingestion_subscriber import MemoryIngestionSubscriber

self._memory_ingestion_subscriber = MemoryIngestionSubscriber(
    event_bus=event_bus,
    unified_memory=self._unified_memory,
)
await self._memory_ingestion_subscriber.start()

# shutdown:
await self._memory_ingestion_subscriber.stop()
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(memory): add MemoryIngestionSubscriber"
```

---

### Task 12: Producer 改造 — chat projector

**Files:**
- Modify: `backend/src/magi/chat/projector.py`（line 28-95 区域）

回看 `magi/chat/projector.py:95`：现在直接 `await self._unified_memory.ingest_event(memory_event)`。

- [ ] **Step 1: 注入 event_bus 而非 unified_memory**

修改 `Projector.__init__` 接受 `event_bus`；不再持有 `_unified_memory`（如果还需要其他读路径，保留但不再用于 ingest）。

- [ ] **Step 2: 改 publish**

```python
# 替换原来的 ingest_event 调用
from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import (
    UserMessageReceived, AssistantResponseProduced, TaskContext,
)

# user message branch (around line 28)
await self._event_bus.publish(Event(
    type=EventTypes.USER_MESSAGE_RECEIVED,
    data=UserMessageReceived(
        content=text,
        context=TaskContext(
            session_id=session_id,
            turn_id=turn_id,
            task_id=None,
            user_id=user_id,
        ),
        metadata={"author_type": "user", **extra},
    ),
    source="chat_projector",
))

# AI response branch (around line 49)
await self._event_bus.publish(Event(
    type=EventTypes.ASSISTANT_RESPONSE_PRODUCED,
    data=AssistantResponseProduced(content=text, context=..., metadata=...),
    source="chat_projector",
))
```

- [ ] **Step 3: 更新 chat projector 实例化点**

grep 找到 Projector 的构造点，把 unified_memory 参数换成 event_bus。

```bash
grep -rn "Projector(" /Users/asuka/code/magi/backend/src --include="*.py" | grep -v "__pycache__\|test"
```

- [ ] **Step 4: 现有 projector 测试**

如有 `tests/chat/test_projector.py`，把对 `unified_memory.ingest_event` 的 mock 换成对 `event_bus.publish` 的断言。

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(chat): projector publishes UserMessageReceived/AssistantResponseProduced"
```

---

### Task 13: Producer 改造 — awareness ingestion gateway

同 Task 12 模式，改 `backend/src/magi/awareness/ingestion_gateway.py:97`：把 `self._unified_memory.ingest_event(memory_event)` 改为 `self._event_bus.publish(Event(SENSOR_EVENT_EMITTED, SensorEventEmitted(...)))`。

- [ ] **Step 1: 改造**

- [ ] **Step 2: 更新实例化点 + 测试**

- [ ] **Step 3: Commit**

```bash
git commit -am "refactor(awareness): ingestion gateway publishes SensorEventEmitted"
```

---

### Task 14: 老事件类型兼容窗口策略

依 spec §7.1：**memory 侧只接新事件**；如果还有非 memory 订阅者依赖 `USER_MESSAGE / AI_RESPONSE / SENSOR_EVENT` 老类型，由 producer 同时 publish 新旧两类事件。

- [ ] **Step 1: 找出非 memory 的老事件订阅者**

```bash
grep -rn "EventTypes\.USER_MESSAGE\b\|EventTypes\.AI_RESPONSE\b\|EventTypes\.SENSOR_EVENT\b" /Users/asuka/code/magi/backend/src --include="*.py" | grep -v "__pycache__\|memory/\|chat/projector\|awareness/ingestion_gateway\|test"
```

记录每个命中。

- [ ] **Step 2: 决策**

对每个命中：
- 如果是 memory 内部消费者（已被 MemoryIngestionSubscriber 取代）—— 删除老订阅
- 如果是非 memory 消费者（如 awareness sensor_hub）—— 保留，让 chat projector / awareness 同时 publish 新旧事件直到这些消费者迁移完成

- [ ] **Step 3: 在 projector / awareness 添加双发**

只在确实有非 memory 订阅者时才双发，避免无谓重复。

- [ ] **Step 4: Commit**

```bash
git commit -am "refactor: keep legacy event types for non-memory subscribers during migration"
```

---

### Task 15: Chunk 3 集成验证 — L4 数据应该开始增长

- [ ] **Step 1: 重启后端，触发工具调用**

```bash
sqlite3 ~/.magi/data/memory/memory.db "SELECT COUNT(*) FROM procedural_skills; SELECT COUNT(*) FROM l4_execution_traces;"
# 触发一次工具调用
sqlite3 ~/.magi/data/memory/memory.db "SELECT COUNT(*) FROM procedural_skills; SELECT COUNT(*) FROM l4_execution_traces;"
```

期望：两表行数都 > 0。如果仍为 0，按 spec §7.1 的"2x 增长"反向：检查是否有去重 / 是否 store_ingestion 的 L4 分支条件未命中（这块要等 Chunk 4 才彻底重写，本章 L4 仍走老的 if 链，理论上 ActionExecuted 事件能命中 `event_type == ACTION_EXECUTED` 分支）。

- [ ] **Step 2: 验证 `/api/memory/procedures` 返回非 0**

```bash
curl -s 'http://127.0.0.1:63890/api/memory/procedures?limit=50' | jq '. | length'
```

期望 > 0。

- [ ] **Step 3: Chunk 3 检查点 — 与用户对齐再继续**

到此核心问题（L4 为 0）已修复。Chunk 4-6 是架构清理，可独立发布。

---

## Chunk 4: Layer 自声明 + UnifiedMemoryStore fan-out

完成后 `store_ingestion.py` 的 if 链消失，每个 layer 用 `accepts()` 自声明。**不改写入语义**，纯结构化。

### Task 16: MemoryLayer Protocol + FanOutContext

**Files:**
- Create: `backend/src/magi/memory/layer_protocol.py`
- Test: `backend/tests/memory/test_layer_protocol.py`

- [ ] **Step 1: Define types**

```python
# backend/src/magi/memory/layer_protocol.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable
from .event_contracts import MemoryEvent


@dataclass
class FanOutContext:
    markers: dict[str, Any] = field(default_factory=dict)


@dataclass
class LayerIngestResult:
    layer_name: str
    ok: bool
    markers: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class MemoryLayer(Protocol):
    layer_name: str
    accepts_event_types: frozenset[str]
    requires_write_lock: bool

    def accepts(self, event: MemoryEvent, ctx: FanOutContext) -> bool: ...
    async def ingest(self, event: MemoryEvent, ctx: FanOutContext) -> LayerIngestResult: ...
```

- [ ] **Step 2: 简单测试**

```python
def test_protocol_runtime_checkable():
    class Dummy:
        layer_name = "x"
        accepts_event_types = frozenset({"a"})
        requires_write_lock = False
        def accepts(self, e, c): return True
        async def ingest(self, e, c): return None
    from magi.memory.layer_protocol import MemoryLayer
    assert isinstance(Dummy(), MemoryLayer)
```

- [ ] **Step 3: Commit**

---

### Task 17: 各 layer adapter

每个现有 store（L0/L1/L2/L3/L4）需要**适配出**符合 `MemoryLayer` 协议的对象。不必改 store 内部实现，可写一个薄适配器：

**Files (new):**
- `backend/src/magi/memory/layers/l0_layer.py`
- `backend/src/magi/memory/layers/l1_layer.py`
- `backend/src/magi/memory/layers/l2_layer.py`（含 §8.3 双路径合并）
- `backend/src/magi/memory/layers/l4_layer.py`
- `backend/src/magi/memory/layers/__init__.py`

L3 不参与 fan-out（schedule 触发），不需要 layer adapter，跳过。

每个 adapter 模板：

```python
# l0_layer.py
class L0Layer:
    layer_name = "l0"
    accepts_event_types = frozenset({
        EventTypes.USER_MESSAGE, EventTypes.USER_MESSAGE_RECEIVED,
        EventTypes.AI_RESPONSE, EventTypes.ASSISTANT_RESPONSE_PRODUCED,
        EventTypes.ACTION_EXECUTED,
        EventTypes.TASK_STARTED, EventTypes.TASK_COMPLETED, EventTypes.TASK_FAILED,
        EventTypes.SENSOR_EVENT, EventTypes.SENSOR_EVENT_EMITTED,
    })
    requires_write_lock = True

    def __init__(self, l0_store): self._store = l0_store
    def accepts(self, event, ctx): return True
    async def ingest(self, event, ctx):
        await self._store.capture_event(event)
        return LayerIngestResult(layer_name=self.layer_name, ok=True)
```

L1 / L4 / L2 各自的 accepts / ingest 把 `store_ingestion.py:52-127` 中对应的代码段迁过来（L1 写入 + idempotency 短路；L2 双路径合并；L4 record_memory_event）。

每个 layer 一个测试文件，覆盖：
- accepts 真值表（关键事件类型）
- ingest 写入 + markers 输出（如 L1.markers["l1_written"]=True）
- failure isolation（store 抛错时 ingest 返回 ok=False）

- [ ] **Step 1: 写 L0 layer + 测试 + 提交**
- [ ] **Step 2: 写 L1 layer + 测试 + 提交**
- [ ] **Step 3: 写 L4 layer + 测试 + 提交**
- [ ] **Step 4: 写 L2 layer（双路径合并）+ 测试 + 提交**

L2 是最重的一步。`accepts()` 返回 `event.cognition_eligible and (ctx.markers.get("l1_written") or not event.ingest_target.includes_l1 or self._l1_disabled)`；`ingest()` 内部根据 ctx 决定走 `l2.enqueue_projection_job(stored_event_id, ...)` 还是 `l2_pipeline.enqueue_event(event)`。

---

### Task 18: store_ingestion.py 重写

**Files:**
- Rewrite: `backend/src/magi/memory/store_ingestion.py:40-140`
- Modify: `backend/src/magi/memory/unified_store.py`（暴露 `_layers_in_order`）

- [ ] **Step 1: 写新版 ingest_event**

按 spec §8.2 的伪码实现。重点：locked → deferred 两段 dispatch；ctx.markers 串联；每个 layer 失败被 try/except 隔离。

- [ ] **Step 2: 删除老 if 链**

整段 `if self.l0 ... if self.l1 ... if self.l4 ...` 删除，替换为 fan-out 循环。

- [ ] **Step 3: 集成测试 — 老语义不变**

构造一个 ActionExecuted MemoryEvent 走 ingest_event：
- L0 capture 被调用
- L1 store 被调用（前提 ingest_target.includes_l1 = True）
- L2 enqueue_projection_job 被调用（前提 cognition_eligible = True）
- L4 record_memory_event 被调用，markers 含 `l4_skill_id`

```bash
cd backend && pytest tests/memory/test_store_ingestion_fanout.py -v
```

- [ ] **Step 4: Commit**

```bash
git commit -am "refactor(memory): replace ingest if-chain with layer.accepts() fan-out"
```

---

### Task 19: Chunk 4 集成回归

- [ ] **Step 1: 跑全 memory 测试**

```bash
cd backend && pytest tests/memory/ -v
```

- [ ] **Step 2: 实际后端跑一次工具调用**

确认 4 表（L0 / l1 fact_events / l2 任意一张 / procedural_skills）行数都增加；correlation_id 一致。

- [ ] **Step 3: commit fence**

---

## Chunk 5: Task 生命周期事件

完成后 task agent 在 task 启动 / 完成 / 失败时也 publish 主总线事件。L4 接收 TaskCompleted/TaskFailed，记录 workflow 类 skill。

### Task 20: TaskOrchestrator publish

**Files:**
- Modify: `backend/src/magi/agent/task_orchestration_workers.py`（已知调用点 line 66, 133；具体 publish 时机在 task 入口/出口）
- Modify: `backend/src/magi/agent/task_agents/explore/postprocess_service.py`
- Modify: 其他 task agent 的 post-process（用 grep 找 ExploreTaskCompletedPayload 等）

实施前 grep：

```bash
grep -rn "TaskCompletedPayload\|task.*complete\|task.*fail" /Users/asuka/code/magi/backend/src/magi/agent --include="*.py" | grep -v "__pycache__\|test"
```

- [ ] **Step 1: 在 task 启动节点 publish TaskStarted**
- [ ] **Step 2: 在终态节点 publish TaskCompleted / TaskFailed**
- [ ] **Step 3: 保留 task agent 内部 message bus（用于 UI 渲染），不影响**
- [ ] **Step 4: 测试每个 publish 点**
- [ ] **Step 5: 集成验证：L4 procedural_skills 多了 workflow 类 skill 行**
- [ ] **Step 6: Commit**

---

## Chunk 6: L4 maintenance schedule

回看 spec §9。

### Task 21: 配置项

**Files:**
- Modify: `backend/src/magi/config/memory_models.py`（找到 `MemoryL4Settings`）

新增字段：
- `breaker_open_timeout_seconds: int = 600`
- `breaker_halfopen_idle_seconds: int = 1800`
- `inactive_skill_retention_days: int = 30`
- `inactive_skill_min_attempts: int = 5`
- `maintenance_enabled: bool = True`

测试 + commit。

---

### Task 22: schema migration — `deleted_at`

**Files:**
- Modify: `backend/src/magi/memory/l4/lifecycle.py initialize()` 内

```python
try:
    await db.execute("ALTER TABLE procedural_skills ADD COLUMN deleted_at REAL")
except aiosqlite.OperationalError as e:
    if "duplicate column name" not in str(e).lower():
        raise
```

修改读路径（`get_all_skills` / `count_skills` / `query_strategies`）增加 `WHERE deleted_at IS NULL`。

测试：迁移幂等（跑两次不报错）；读路径过滤已软删行。

Commit。

---

### Task 23: maintenance schedule 主体

**Files:**
- Create: `backend/src/magi/memory/l4/maintenance_schedule.py`
- Test: `backend/tests/memory/l4/test_maintenance_schedule.py`

参考 `magi/memory/l3/summary_schedule.py` 的结构。每个周期任务一个独立 async function：

```python
class L4MaintenanceSchedule:
    def __init__(self, store, settings):
        self._store = store
        self._settings = settings
        self._tasks: list[asyncio.Task] = []

    async def start(self):
        if not self._settings.maintenance_enabled: return
        self._tasks = [
            asyncio.create_task(self._loop(self._decay_breakers, 300)),
            asyncio.create_task(self._loop(self._check_pending_traces, 900)),
            asyncio.create_task(self._loop(self._check_fts_consistency, 3600)),
            asyncio.create_task(self._loop(self._soft_delete_inactive, 86400)),
        ]

    async def stop(self): ...

    async def _decay_breakers(self): ...   # spec §9.1 row 1
    async def _check_pending_traces(self): ...  # row 2
    async def _check_fts_consistency(self): ...  # row 3
    async def _soft_delete_inactive(self): ...   # row 4
```

- [ ] **Step 1: 测试 _decay_breakers**

构造一个 `circuit_state="open"` + `circuit_opened_at` 超时的 skill，跑一次 → 验证 state 改为 `half_open`。

- [ ] **Step 2: 测试 _check_pending_traces**
- [ ] **Step 3: 测试 _check_fts_consistency**
- [ ] **Step 4: 测试 _soft_delete_inactive**
- [ ] **Step 5: Implementation**
- [ ] **Step 6: 接入 lifecycle**

在 `magi/memory/lifecycle.py` 或 L4 自己的 lifecycle 里 instantiate + start，shutdown 时 stop。

- [ ] **Step 7: Commit**

---

### Task 24: Chunk 6 集成验证

- [ ] **Step 1: 跑后端一段时间，确认无异常日志**
- [ ] **Step 2: 人工触发各任务**

可在 maintenance_schedule 上加一个 `run_once()` 暴露给测试 / 调试。

---

## 收尾

### Task 25: 清理与文档

- [ ] **Step 1: 删除老的 USER_MESSAGE / SENSOR_EVENT 双发**

如果 Task 14 中保留的非 memory 老订阅者已迁移到新事件，移除 producer 端的双发。否则文档化为已知技术债。

- [ ] **Step 2: 在 docs/ 下加一段架构说明**

`docs/memory/architecture.md`（如不存在则新建）补充 EventBus 章节，简短说明：
- 领域事件层（domain_payloads.py）
- ToolInvocationService 收口
- MemoryIngestionSubscriber + RuntimeTraceSubscriber 两路订阅
- 各 layer 的 accepts 矩阵

- [ ] **Step 3: 全量测试**

```bash
cd backend && pytest -v
```

- [ ] **Step 4: 跑一次本地端到端**

`/api/memory/procedures?limit=50` 返回非空；`/api/memory/statistics` 各 layer 计数正常。

- [ ] **Step 5: Final commit**

```bash
git commit -am "docs: domain-event architecture overview"
```

---

## 风险与回退点

每个 Chunk 末尾都是天然的 commit fence；如发现问题：

- Chunk 1 失败：纯加法，无影响
- Chunk 2 失败：runtime_trace 可能漂移；回退方案：保留老的直写代码，删除 RuntimeTraceSubscriber 注册
- Chunk 3 失败：chat / awareness 主链路退化；回退到上一个 commit
- Chunk 4 失败：memory ingest 行为可能变化；回退到 Chunk 3 之后
- Chunk 5 失败：仅影响 L4 的 workflow 类 skill；回退影响小
- Chunk 6 失败：maintenance 不跑只是不衰减，无新 bug
