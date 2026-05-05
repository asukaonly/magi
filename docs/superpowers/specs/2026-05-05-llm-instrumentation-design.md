# LLM 调用埋点（子项目 D）设计

日期：2026-05-05
作者：asuka
子项目代号：**D**（LLM 调用埋点，理想态架构子项目 4/4）

## 1. 背景

A/B/C 已经把工具执行 / 任务生命周期 / chat 消息 / sensor 路径全部接入 publish-subscribe + Span 范式。剩下未对齐的最大块：**LLM 调用本身**。

现状：

- `LLMCallEventPayload`（`magi/llm/usage_events.py`）持 token/cost/latency 字段。
- `provider_bridge/responses.py:378-379` 在 LLM 调用完成时用 `publish_llm_call_event(payload, publisher)` 发 `Event(LLM_CALL_COMPLETED, ...)`。
- `LLMUsageStore`（`magi/llm/usage_store.py`）订阅 `LLM_CALL_COMPLETED`，写 `llm_usage` 表。
- B 阶段把 chat post-process 的 trace 写入改成 `publish_trace_span(node_type="llm_call")`——**等于在调用方一侧补 trace_llm_calls 投影**。LLM 调用本身（provider_bridge）仍发老的 `LLM_CALL_COMPLETED` 事件。

结果：同一次 LLM 调用产生**两条事件**——一条 `LLM_CALL_COMPLETED`（token/usage 走 llm_usage 表）、一条 chat post-process 事后 publish 的 `SpanCompleted(node_type="llm_call")`（写 trace_llm_calls）。两条事件由两个不同位置发出，**容易不一致**。同时：

- 非 chat 路径的 LLM 调用（L3 summary / L2 entity / L4 strategy extraction）从未走 publish_trace_span，**没有 trace 数据**。
- chat 路径下 LLM trace 拓扑由调用方决定，不由 LLM 调用自身决定——架构上不一致。

D 把 LLM_CALL_COMPLETED 与 SpanCompleted 合并为单一事件，发布点收口到 provider_bridge，token/cost/latency 走 SpanCompleted.attributes，新增 `LLMUsageSubscriber` 投影到 llm_usage 表。

## 2. 目标 / 非目标

### 目标

1. **每次 LLM 调用 = 一条 SpanCompleted 事件**。LLM_CALL_COMPLETED 事件类型与 LLMUsageEventPublisher 退场。
2. 发布点收口到 `provider_bridge/responses.py:378`（现 publish_llm_call_event 位置）。该位置已经持有所有 token/latency/cost/preview 数据，符合 OTel OnEnd 语义。
3. **trace 上下文从 contextvars 自动继承**：当 LLM 调用嵌在 chat turn / tool / task / scheduler 等 with start_async_span 内时，LLM SpanCompleted 自动嵌入 trace 树正确位置。无父 span 时（如 maintenance 路径）LLM span 是 trace 根。
4. 新增 `LLMUsageSubscriber` 投影到 `llm_usage` 表。RuntimeTraceSubscriber 已订阅 SpanCompleted，对 `node_type="llm_call"` 已能写 trace_llm_calls + trace_spans（B 阶段就位）。
5. **chat post-process / worker_trace 中的 `publish_trace_span(node_type="llm_call")` 调用全部删除**——避免 LLM 调用产生两条 SpanCompleted。LLM span 唯一发布点 = provider_bridge。
6. 完成后：grep `LLM_CALL_COMPLETED / LLMUsageEventPublisher / publish_llm_call_event / LLMCallEventPayload` 在 src/ 业务代码中均为 0 命中。

### 非目标

- 不动 LLMUsageStore 内部 schema（llm_usage 表结构保留）。
- 不接入 OTel SDK / exporter（架构对齐而已，未来另议）。
- 不做 Scheduler 事件化（D 不在范围内，可后续单独子项目）。
- 不做 plugin/background 范式收尾（同上）。
- 不动 `LLMAdapter` 抽象基类（埋点放 provider_bridge 层）。

## 3. 整体架构

```
┌─ provider_bridge.responses ──────────────────────────┐
│  LLM 调用 (chat / generate / embedding / image / ...) │
│  完成时 (line ~378):                                  │
│    1. 收集 token/cost/latency/previews/error          │
│    2. 取 ctx = current_trace_context() (A 信封)       │
│    3. publish_trace_span(                             │
│         event_bus=...,                                │
│         node_type="llm_call",                         │
│         name=model,                                   │
│         trace_id / parent_span_id 来自 ctx,           │
│         attributes={provider, model, tokens, cost,    │
│                     ttft_ms, thinking_*, previews,    │
│                     session_id, agent_id, ...}        │
│       )                                               │
└──────────┬───────────────────────────────────────────┘
           │
           ▼
       EventBus (SpanCompleted)
           │
   ┌───────┼───────┐
   ▼       ▼       ▼
 Runtime  LLMUsage  (其他订阅者)
 Trace    Subscr.
 Subscr.    │
   │        ▼
   │  llm_usage 表 (token/cost/latency 度量)
   ▼
 trace_spans 行 + trace_llm_calls 行
 (B 阶段 dispatch)
```

约束：
- 每次 LLM 调用产生 **1** 条 SpanCompleted，由 provider_bridge 发出。
- chat post-process / worker_trace 中所有 `publish_trace_span(node_type="llm_call")` 删除（§5）。
- 失败 LLM 调用走 `status="error"` + `error: ToolError`，与 ToolInvocation 失败语义一致。
- LLM_CALL_COMPLETED 事件类型常量删除；MemoryIngestionSubscriber 不感兴趣此 node_type，跳过即可（已是 §B-§7 的设计，无需改动）。

## 4. SpanCompleted attributes 标准字段（node_type="llm_call"）

```python
attributes = {
    # provider/model identity
    "provider": str,                # "anthropic" / "openai" / ...
    "model": str,                   # "claude-opus-4-7" / "gpt-4o" / ...
    "request_kind": str,            # "generate" / "chat" / "chat_stream" / "embedding" / "image"
    
    # token usage
    "input_tokens": int,
    "output_tokens": int,
    "reasoning_tokens": int,
    "cache_read_tokens": int,
    "cache_write_tokens": int,
    
    # cost / latency
    "cost_usd": float,
    "ttft_ms": int,                 # time to first token (streaming only; 0 otherwise)
    
    # thinking (Anthropic)
    "thinking_enabled": bool,
    "thinking_depth": str,          # "low" / "medium" / "high" / "none"
    "thinking_content": str | None, # may be truncated
    
    # previews
    "request_preview": str | None,
    "response_preview": str | None,
    
    # business context (for llm_usage indexing)
    "session_id": str | None,
    "turn_id": str | None,          # also mirrored on SpanCompleted.turn_id
    "agent_id": str | None,
}
```

`SpanCompleted.duration_ms` 已在 dataclass 上（B 阶段）；不重复成 attributes 字段。
`SpanCompleted.error` 已在 dataclass 上；失败信息在那。
`SpanCompleted.name` = `attributes["model"]`，便于 trace 树可读。

RuntimeTraceSubscriber `_record_llm_call` 已就位（B 阶段），从 attributes 读相同字段写 trace_llm_calls。新 LLMUsageSubscriber 也从同一 attributes 集合读字段写 llm_usage。两个订阅者读同一 attributes 模式，schema 演进时同步更新。

## 5. LLMUsageSubscriber

新建 `backend/src/magi/llm/subscribers/llm_usage_subscriber.py`：

```python
"""Project SpanCompleted(node_type='llm_call') into the llm_usage table."""
from __future__ import annotations
import asyncio
import logging
import time
from typing import Optional

from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import SpanCompleted
from magi.events.payload_helpers import expect_payload, PayloadTypeError
from magi.llm.usage_store import LLMUsageStore

logger = logging.getLogger(__name__)


class LLMUsageSubscriber:
    """Subscribe SpanCompleted; route llm_call → LLMUsageStore."""

    def __init__(self, *, event_bus, llm_usage_store: LLMUsageStore) -> None:
        self._bus = event_bus
        self._store = llm_usage_store
        self._sub_id: Optional[str] = None
        self._inflight: set[asyncio.Task] = set()

    async def start(self) -> None:
        self._sub_id = await self._bus.subscribe(
            EventTypes.SPAN_COMPLETED, self._on_event,
        )

    async def stop(self) -> None:
        if self._sub_id is not None:
            try:
                await self._bus.unsubscribe(self._sub_id)
            except Exception:
                logger.exception("llm_usage_subscriber unsubscribe failed")
            self._sub_id = None
        await self.drain()

    async def drain(self) -> None:
        if not self._inflight:
            return
        await asyncio.gather(*list(self._inflight), return_exceptions=True)

    async def _on_event(self, event: Event) -> None:
        try:
            payload = expect_payload(event, SpanCompleted)
        except PayloadTypeError:
            return
        if payload.node_type != "llm_call":
            return
        task = asyncio.create_task(self._safe_record(event, payload))
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _safe_record(self, event: Event, payload: SpanCompleted) -> None:
        try:
            attrs = payload.attributes or {}
            await self._store.record_usage(
                provider=str(attrs.get("provider") or ""),
                model=str(attrs.get("model") or payload.name),
                request_kind=str(attrs.get("request_kind") or "unknown"),
                success=(payload.status == "ok"),
                input_tokens=int(attrs.get("input_tokens", 0)),
                output_tokens=int(attrs.get("output_tokens", 0)),
                reasoning_tokens=int(attrs.get("reasoning_tokens", 0)),
                cache_read_tokens=int(attrs.get("cache_read_tokens", 0)),
                cache_write_tokens=int(attrs.get("cache_write_tokens", 0)),
                cost_usd=float(attrs.get("cost_usd", 0.0)),
                ttft_ms=int(attrs.get("ttft_ms", 0)),
                latency_ms=int(payload.duration_ms),
                error=(payload.error.message if payload.error else None),
                correlation_id=event.correlation_id,
                session_id=attrs.get("session_id"),
                turn_id=payload.turn_id or attrs.get("turn_id"),
                agent_id=attrs.get("agent_id"),
                created_at=float(payload.started_at_ms) / 1000.0,
            )
        except Exception:
            logger.exception("llm_usage projection failed: span=%s", payload.span_id)
```

注：`LLMUsageStore.record_usage(...)` 的精确签名实施前需确认（§9 风险）。当前 `LLMUsageStore` 自订阅 `LLM_CALL_COMPLETED` 事件并把 payload 写入数据库；D 阶段 store 取消自订阅，改由 LLMUsageSubscriber 推动。如果 store 现有写入 API 不够直接，新增一个公共方法 `record_usage(...)` 或 `write_row(payload_dict)`，具体看现状。

## 6. provider_bridge publish 切换

`backend/src/magi/llm/provider_bridge/responses.py:378-379` 现状：

```python
publish = getattr(bridge_module, "publish_llm_call_event", publish_llm_call_event)
await publish(payload, publisher=self._usage_event_publisher)
```

改为：

```python
from magi.runtime_trace.span_publisher import publish_trace_span, resolve_event_bus
from magi.events.tracing import current_trace_context
from magi.events.domain_payloads import ToolError
import uuid

ctx = current_trace_context()
trace_id = ctx.trace_id if ctx is not None else str(uuid.uuid4())
parent_span_id = ctx.span_id if ctx is not None else None

started_at_ms = int(payload.created_at * 1000)
ended_at_ms = started_at_ms + int(payload.latency_seconds * 1000)
error = None
if not payload.success and payload.error:
    error = ToolError(type="LLMError", message=str(payload.error)[:1000])

await publish_trace_span(
    event_bus=resolve_event_bus(fallback=self._host._message_bus),
    node_type="llm_call",
    name=payload.model,
    trace_id=trace_id,
    parent_span_id=parent_span_id,
    status="ok" if payload.success else "error",
    started_at_ms=started_at_ms,
    ended_at_ms=ended_at_ms,
    error=error,
    turn_id=payload.turn_id,
    attributes={
        "provider": payload.provider,
        "model": payload.model,
        "request_kind": payload.request_kind,
        "input_tokens": payload.input_tokens,
        "output_tokens": payload.output_tokens,
        "reasoning_tokens": payload.reasoning_tokens,
        "cache_read_tokens": payload.cache_read_tokens,
        "cache_write_tokens": payload.cache_write_tokens,
        "cost_usd": payload.cost_usd,
        "ttft_ms": payload.ttft_ms,
        "thinking_enabled": payload.thinking_enabled,
        "thinking_depth": payload.thinking_depth,
        "thinking_content": payload.thinking_content,
        "request_preview": payload.request_preview,
        "response_preview": payload.response_preview,
        "session_id": payload.session_id,
        "agent_id": payload.agent_id,
    },
)
```

复用 B 阶段 `publish_trace_span` helper，复用 A 阶段 `current_trace_context()`。

`payload.created_at` / `payload.latency_seconds` 现 `LLMCallEventPayload` 字段——实施前确认；如未存在用 monotonic 时间替代。

## 7. 删除清单

D 完成后删除（实施步骤里逐个去）：

| 文件 / 符号 | 处理 |
|------------|------|
| `magi/llm/usage_events.py` 整文件 | 删除 |
| `EventTypes.LLM_CALL_COMPLETED` 常量 | 删除 |
| `Container.llm_usage_event_publisher` provider | 删除 |
| `RuntimeBootstrapContext.llm_usage_event_publisher` 字段 | 删除 |
| `provider_bridge/__init__.py` 中 `usage_event_publisher` 参数 + `_usage_event_publisher` 属性 | 删除 |
| `provider_bridge/responses.py` 中 `from ..usage_events import ... publish_llm_call_event` | 删除 |
| LLMUsageStore 内自订阅 LLM_CALL_COMPLETED 的逻辑（如有） | 删除 |

## 8. chat post-process / worker_trace 去重

B 阶段在以下位置 publish `node_type="llm_call"` SpanCompleted：

```bash
grep -rn 'node_type="llm_call"\|node_type=.llm_call.' backend/src --include="*.py"
```

这些位置是 chat post-process 和 worker_trace 的"事后投影"。D 阶段 LLM 自身已发 SpanCompleted——这些投影代码会与 LLM 自发产生**重复事件**和**重复 trace_llm_calls 行**。

**全部删除**这些 `node_type="llm_call"` publish 调用。同时检查这些代码块原本写的 trace_spans 父 span（若 chat post-process 同时写 LLM 父 span 以建立拓扑）：父 span 的 trace_id / span_id 现在通过 contextvars 自动传给 LLM publish，无需父 span 显式 publish——chat post-process 只需保证调用 LLM 时处于 `with start_async_span(node_type="span/...")` 上下文中。

实施前完整 grep + 阶段 5 单步删除，依赖详细位置确认。

## 9. 实施分阶段

1. **`LLMUsageSubscriber` 实现 + 单测**：纯加法。subscribe SpanCompleted 但无新 producer。需要 `LLMUsageStore.record_usage(...)` 公共方法（实施前 grep 确认 / 必要时新增）。
2. **lifecycle 接入新订阅者**：注册到 bus，subscriber 已激活。LLM 调用仍发 LLM_CALL_COMPLETED 事件（旧路径），所以 LLMUsageSubscriber 暂不会被触发。
3. **provider_bridge publish 切换**（`responses.py:378`）：从 `publish_llm_call_event` 改 `publish_trace_span(node_type="llm_call")`。**关键单步切换**：发布点切换后 SpanCompleted 流向 RuntimeTraceSubscriber + LLMUsageSubscriber 两个订阅者；老 LLMUsageStore 自订阅老事件失效（无 producer）。集成测试更新。
4. **chat post-process / worker_trace 去重**：删除所有事后 `node_type="llm_call"` publish 调用。
5. **删除老链路**：
   - `magi/llm/usage_events.py` 整文件
   - `EventTypes.LLM_CALL_COMPLETED` 常量
   - Container / Context / provider_bridge 注入点
   - LLMUsageStore 内自订阅老事件的逻辑（如有）
6. **回归 + grep 验证**：
   - `LLM_CALL_COMPLETED` 在 src/ 内 0 命中
   - `LLMUsageEventPublisher / publish_llm_call_event / LLMCallEventPayload` 在 src/ 内 0 命中
   - `node_type="llm_call"` 的 publish 调用仅出现于 `provider_bridge/responses.py`

每阶段独立可发布（除 §3 是关键单步切换）。

## 10. 测试策略

### 10.1 单元

- `tests/llm/subscribers/test_llm_usage_subscriber.py`
  - 发 SpanCompleted(node_type="llm_call") with full attributes → store.record_usage 调用一次，参数齐全
  - node_type ∈ {"span", "tool_invocation", "intent_resolution"} → 不调 store
  - status="error" → record_usage 收到 success=False
  - store 抛错 → handler swallow，subscriber survive

- `tests/llm/test_provider_bridge_responses_publish.py`
  - mock event_bus，exercise 现 publish 路径 → SpanCompleted publish 一次，attributes 字段齐全
  - error 路径 → status="error" + error.message

### 10.2 集成

- `tests/integration/test_d_llm_pipeline.py`
  - 真 InMemoryMessageBusBackend + 真 LLMUsageStore (temp DB) + RuntimeTraceSubscriber + LLMUsageSubscriber
  - mock provider_bridge bridge_module 调用 publish_trace_span 一次（模拟 LLM 完成）
  - 等 drain → 查 trace_llm_calls 表 1 行 + llm_usage 表 1 行 + trace_spans 表 1 行

### 10.3 回归

- 现 `tests/llm/test_usage_events*` 测试改/删
  - 断言对象从 `LLM_CALL_COMPLETED` 变 `SpanCompleted`
  - 删除 LLMUsageEventPublisher 测试
- chat post-process / worker_trace tests 中现有 "publish llm_call SpanCompleted" 断言改为期望 0 次（这些代码已删）；确认 LLM 自身仍 publish 1 次

## 11. 错误隔离 / 性能

### 错误隔离

- provider_bridge publish 失败 → publish_trace_span 内部 try/except 吞掉，LLM 业务返回值不受影响（与现 publish_llm_call_event 行为对齐）。
- LLMUsageSubscriber._safe_record 异常被 try/except，subscriber 后续事件处理不中断。
- RuntimeTraceSubscriber._record_llm_call 已有相同隔离。

### 性能

- 现路径：LLM 调用结束 → 1 publish + 1 store insert（事件方式）。
- D 后：LLM 调用结束 → 1 publish + 2 store insert（usage + trace_llm_calls）。
- 增加成本 ≈ 1 次 sqlite INSERT（runtime_trace），单次 < 1ms，对 LLM 调用 latency 无显著影响（LLM 调用本身秒级）。
- create_task 卸载保证两个订阅者并行投影。

## 12. 风险

| 风险 | 缓解 |
|------|------|
| LLMUsageStore 现 `record_usage` API 不存在 / 签名不同 | 实施前 grep `class LLMUsageStore`；如有 `record_event(LLMCallEventPayload)` 直接调用，subscriber 内构造 LLMCallEventPayload 适配；如无任何公共写 API 则新增 `record_usage(**kwargs)` |
| `LLMCallEventPayload` 缺 latency_seconds / cost_usd 等字段 | 实施前 grep dataclass 定义；如缺则用 monotonic 时间或 0.0 替代；不阻塞迁移 |
| 删除 LLMUsageEventPublisher 后 `LLMUsageStore.start(message_bus)` 启动逻辑失效 | 实施前 grep `LLMUsageStore.start` 调用方；若 start 仅做自订阅，删除调用；否则保留 init 逻辑、删自订阅部分 |
| chat post-process / worker_trace 删 `node_type="llm_call"` publish 后部分测试失败 | §10.3 改测试期望次数；保留 LLM 自发 publish 的断言 |
| LLM SpanCompleted 在 chat post-process 父 span 之外发出（contextvars 已离开 with 块） | publish 应在 with 块**内**触发——即 LLM 调用完成时还在父 with 范围。chat post-process 的 LLM 调用都在父 with 块内完成，no-op；仍需测试覆盖 |
| 后台 / maintenance 路径无父 span，LLM SpanCompleted 是 trace 根 | 设计预期。`current_trace_context()` 返回 None → publish_trace_span 自动生成 trace_id |
| 多 provider 并发调用同一 turn 时 trace_id 共享但 span_id 不同 | `publish_trace_span` 自动生成 span_id（不传），无冲突 |

## 13. 已知边界条件

- D 完成后 `node_type="llm_call"` SpanCompleted 的**唯一发布点**是 `provider_bridge/responses.py:378`。
- `usage_events.py` / `LLM_CALL_COMPLETED` / `LLMUsageEventPublisher` 全部删除。
- chat post-process / worker_trace 中事后 LLM trace 投影删除。LLM trace 数据现在直接来自 LLM 调用本身，与 token usage 同源。
- 接 OTel SDK 时，LLM SpanCompleted 与其他 SpanCompleted 一样可走 OTel exporter——D 完成 = 几乎 plug-and-play。

## 14. Open Questions

无。所有关键决策已通过 brainstorming 问答确定：合并为 SpanCompleted / 新增 LLMUsageSubscriber / 顶层入口埋点（在 provider_bridge.responses publish 点）/ trace 上下文从 contextvars 自动取。
