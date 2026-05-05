# awareness 拆三订阅者 + 消除 dict 旁路（子项目 C）设计

日期：2026-05-05
作者：asuka
子项目代号：**C**（理想态架构子项目 3/4）

## 1. 背景

A 已经把 producer-assigned `event_id` + `causation_id` + `trace_context` 写进 Event 信封。B 已经把 `_runtime_trace_store.upsert_*` 全部拆为订阅者。本子项目（C）把 awareness 路径——sensor 数据从外部进入系统的入口——同样做完订阅者解耦。

现状（`awareness/ingestion_gateway.py:57-125`）：`SensorIngestionGateway.ingest()` 是个原子三步 + 1 步状态更新：

```python
async def ingest(...):
    memory_event = self._build_memory_event(...)            # 1. 构造 MemoryEvent
    memory_result = await self._unified_memory.ingest_event(memory_event)  # 2. 同步等 memory 写入
    stored_event_id = memory_result["event_id"]
    if self._timeline_adapter:
        timeline_event.event_id = stored_event_id
        await self._timeline_adapter.on_timeline_event(timeline_event)     # 3. 同步喂 timeline
    if metadata.relation_candidates:
        await self._process_relations(stored_event_id, ...)  # 4. 同步建 KG 边
    if self._state_store:
        await self._state_store.add_fingerprints(...)        # 5. 同步更新 sensor 指纹
    return SensorIngestionResult(...)
```

下游 timeline / KG 都需要 `stored_event_id`——这是同步耦合的根因。A 阶段把 producer-assigned `event_id` 引入信封后，这个同步等待已不再必要：所有消费者用同一个 producer-assigned id 即可。

## 2. 目标 / 非目标

### 目标

1. SensorIngestionGateway 变薄：只采集 sensor 上下文 → publish SensorEventEmitted → 立即返回。不再持有 `unified_memory / timeline_adapter / sensor_state_store`。
2. 三个新订阅者：`TimelineSubscriber / KGSubscriber / SensorStateUpdateSubscriber`，分别负责 timeline read model / KG 边写入 / sensor 指纹持久化。MemoryIngestionSubscriber 已存在、改 `_from_sensor` translator 走主路径。
3. **消除 dict 旁路**：把 `_build_memory_event` 从 gateway 移到独立模块 `magi.awareness.sensor_memory_projection`，供 MemoryIngestionSubscriber translator 直接调。订阅者侧不再有"如果某字段非空跳过 translate 否则走 fallback"的隐契约分支。
4. 业务侧 grep `_unified_memory\.ingest_event` 在 awareness 包内必须为 0；`upsert_user_graph_edge` 直调亦为 0。
5. 端到端：触发 sensor.ingest → fact_events 行 + timeline_adapter.on_timeline_event 调用 + KG 边写入 + sensor_state.add_fingerprints 全部达成。

### 非目标

- 不改造 sensor 本身的 SensorBase / SensorOutput 接口。
- 不改 timeline_adapter 内部实现。
- 不改 KG 存储（`upsert_user_graph_edge`）实现。
- 不引入 producer/subscriber 间的强一致性保证（CQRS 失败语义：每个订阅者独立失败）。
- 不接 OTel exporter（D 子项目）。

## 3. 整体架构

```
┌─ SensorIngestionGateway (薄 publisher) ──────────────┐
│  ingest(sensor, output, metadata,                    │
│           allowed_edge_whitelist=None)               │
│      -> SensorIngestionResult                        │
│                                                      │
│   1. event_id = ULID() (producer-assigned)           │
│   2. 收集原始上下文 (sensor_id / output_dict /        │
│      metadata_dict / policy_dict / projection_dict /  │
│      relation_candidates / allowed_edge_whitelist /   │
│      sensor_fingerprint / occurred_at /               │
│      owner_user_id) 打包为 SensorEventEmitted       │
│   3. publish SensorEventEmitted                      │
│   4. 立即返回 SensorIngestionResult(event_id, True)  │
└──────────┬───────────────────────────────────────────┘
           │
           ▼
       EventBus
           │
   ┌───────┼─────────┬──────────────┐
   ▼       ▼         ▼              ▼
 Memory  Timeline   KG          SensorState
 Subscr. Subscr.    Subscr.     Subscr.
   │       │         │              │
   │       │         │              ▼
   │       │         │       state_store
   │       │         │       .add_fingerprints
   │       │         ▼
   │       │   _process_relations
   │       │   → unified_memory
   │       │     .upsert_user_graph_edge
   │       ▼
   │ TimelineEvent.from_dict(
   │   build_timeline_event_dict(payload))
   │ → timeline_adapter
   │   .on_timeline_event
   ▼
build_sensor_memory_event(payload)
    → MemoryEvent
    → unified_memory.ingest_event
    → L0/L1/L2/L4
```

约束：
- 一个事件 = 一个事实 = 4 个订阅者各自独立投影
- 每个订阅者独立失败、不影响其他。无跨订阅者一致性
- producer-assigned event_id 是所有下游共享的业务 id
- `SensorEventEmitted` 是"原始上下文事件"，subscriber 各自从事件字段重建自己需要的视图（MemoryEvent / TimelineEvent / KG 边）
- **订阅者内部不分支 dict 旁路**——所有 subscriber 走显式重建函数

## 4. 领域事件契约扩展

`magi.events.domain_payloads.SensorEventEmitted` 现状（A 阶段）：

```python
@dataclass(frozen=True)
class SensorEventEmitted:
    sensor_name: str
    payload: Mapping[str, Any]
    context: TaskContext
```

C 扩展为"原始上下文事件"：

```python
@dataclass(frozen=True)
class SensorEventEmitted:
    # A 已有
    sensor_name: str
    payload: Mapping[str, Any]              # 与 output_dict 同义；保留兼容老订阅者
    context: TaskContext

    # 新增（C）
    sensor_id: str
    output_dict: Mapping[str, Any]          # output.to_dict() 的显式命名字段
    metadata_dict: Optional[Mapping[str, Any]] = None    # SensorOutputMetadata.to_dict()
    policy_dict: Mapping[str, Any] = field(default_factory=dict)        # SensorMemoryPolicy.to_dict()
    projection_dict: Mapping[str, Any] = field(default_factory=dict)    # SensorProjection.to_dict() 与 metadata
    occurred_at: float = 0.0
    owner_user_id: Optional[str] = None

    # KG 投影需要
    relation_candidates: tuple[Mapping[str, Any], ...] = ()
    allowed_edge_whitelist: tuple[str, ...] = ()

    # SensorState 投影需要
    sensor_fingerprint: Optional[str] = None
```

**设计要点**：
- `payload` 字段保留名称（A 已有），但与 `output_dict` 同指；新订阅者读 `output_dict` 显式；老订阅者读 `payload` 兼容。
- 所有"重建 MemoryEvent / TimelineEvent / KG 边"所需的信息都在 payload 里——subscriber 侧无需访问 `sensor_registry` 或重新调用 `sensor.memory_policy`。
- `policy_dict` / `projection_dict` 通过显式 `to_dict()` 序列化。如果 `SensorMemoryPolicy / SensorProjection` 当前没有 `to_dict`，C 实施期间补上；同时新增对称 `from_dict` classmethod。

## 5. 共享投影模块 `magi.awareness.sensor_memory_projection`

新建模块，把 `SensorIngestionGateway._build_memory_event` 的逻辑拆到这里。两个公共函数：

```python
"""Pure functions to build canonical MemoryEvent / TimelineEvent dict from
SensorEventEmitted payload context.

Used by:
- MemoryIngestionSubscriber._from_sensor translator (memory ingest)
- TimelineSubscriber._on_event (timeline read model)
- 其他需要从 sensor 事件重建领域对象的代码
"""
from __future__ import annotations
from typing import Any, Mapping
from magi.events.domain_payloads import SensorEventEmitted
from magi.memory.event_contracts import MemoryEvent
from magi.awareness.timeline_event import TimelineEvent


def build_sensor_memory_event(
    payload: SensorEventEmitted,
    *,
    event_id: str,
    correlation_id: Optional[str] = None,
    causation_id: Optional[str] = None,
    trace_context: Optional[TraceContext] = None,
) -> MemoryEvent:
    """Pure constructor. Replaces SensorIngestionGateway._build_memory_event.
    
    `event_id` comes from the envelope (caller passes event.event_id).
    Trace fields likewise mirrored from envelope by caller.
    """
    policy = SensorMemoryPolicy.from_dict(payload.policy_dict)
    projection_metadata = dict(payload.projection_dict.get("metadata", {}))
    timeline_event_dict = build_timeline_event_dict(payload, event_id=event_id)

    metadata_json = dict(payload.output_dict.get("domain_payload") or {})
    metadata_json.update(projection_metadata)
    # L2 batch policy — 从 policy 取，与 gateway 现状逻辑一致
    if policy.l2_batch_policy:
        metadata_json.update(_serialize_l2_batch(policy.l2_batch_policy))
    metadata_json["timeline"] = timeline_event_dict
    metadata_json["memory_owner_user_id"] = payload.owner_user_id
    # ... 其余 metadata 累加（与现 _build_memory_event 完全等价）

    return MemoryEvent(
        event_id=event_id,
        correlation_id=correlation_id or event_id,
        causation_id=causation_id,
        trace_id=trace_context.trace_id if trace_context else None,
        span_id=trace_context.span_id if trace_context else None,
        parent_span_id=trace_context.parent_span_id if trace_context else None,
        timestamp=payload.occurred_at,
        created_at=time.time(),
        event_type="SENSOR_EVENT",
        source=payload.sensor_id,
        source_item_id=payload.output_dict.get("source_item_id"),
        memory_domain=policy.memory_domain,
        ingest_target=policy.ingest_target,
        cognition_eligible=bool(policy.cognition_eligible),
        tom_depth=policy.tom_depth,
        retention_class=policy.retention_class,
        session_id=None,
        turn_id=None,
        user_id=payload.owner_user_id,
        task_id=None,
        content=timeline_event_dict.get("summary", ""),
        author_type="sensor",
        content_type="text",
        importance_score=float(policy.importance_score),
        level=int(policy.level),
        idempotency_key=payload.output_dict.get("idempotency_key"),
        media_path=payload.output_dict.get("media_path"),
        metadata_json=metadata_json,
    )


def build_timeline_event_dict(
    payload: SensorEventEmitted,
    *,
    event_id: str,
) -> Mapping[str, Any]:
    """Build TimelineEvent.to_dict() shape from sensor payload context."""
    # 复用 awareness/timeline_event.py 中现有 build_sensor_timeline_event 的内核逻辑
    # 但接受 payload 而不是 sensor 对象
    ...
```

辅助序列化（如 `SensorMemoryPolicy.to_dict / from_dict` / `SensorProjection.to_dict`）按需新增。

**架构合理性**：
- 这是一个纯函数模块，单一职责（"从 sensor 事件上下文构造领域对象"）。
- 没有 dict 旁路：subscriber 路径与任何其他 producer 路径走同一个 translation 模型——event → translator → MemoryEvent。
- 任何想构造 sensor MemoryEvent 的代码（包括将来可能有的 batch 处理 / replay）都用这个函数，避免逻辑重复。

## 6. SensorIngestionGateway 改造（薄 publisher）

```python
class SensorIngestionGateway:
    """Sensor ingestion publisher.
    
    Builds a SensorEventEmitted payload from sensor + output + metadata
    and publishes to the bus. Side-effects (memory / timeline / KG / state)
    are handled by independent subscribers.
    """

    def __init__(self, *, event_bus) -> None:
        self._event_bus = event_bus

    async def ingest(
        self,
        sensor: SensorBase,
        output: SensorOutput,
        metadata: Optional[SensorOutputMetadata] = None,
        *,
        allowed_edge_whitelist: Optional[list[str]] = None,
    ) -> SensorIngestionResult:
        event_id = str(ULID())
        projection = build_sensor_projection(sensor, output, metadata)
        owner_user_id = self._resolve_memory_owner_user_id(output)
        fingerprint = sensor.source_item_version_fingerprint(output.to_dict())

        payload = SensorEventEmitted(
            sensor_name=sensor.sensor_id,
            payload=output.to_dict(),
            output_dict=output.to_dict(),
            context=TaskContext(
                session_id=None, turn_id=None, task_id=None, user_id=owner_user_id,
            ),
            sensor_id=sensor.sensor_id,
            metadata_dict=metadata.to_dict() if metadata else None,
            policy_dict=sensor.memory_policy.to_dict(),
            projection_dict=projection.to_dict(),
            occurred_at=output.occurred_at,
            owner_user_id=owner_user_id,
            relation_candidates=(
                tuple(metadata.relation_candidates)
                if metadata and metadata.relation_candidates
                else ()
            ),
            allowed_edge_whitelist=tuple(allowed_edge_whitelist or ()),
            sensor_fingerprint=fingerprint,
        )

        try:
            await self._event_bus.publish(Event(
                type=EventTypes.SENSOR_EVENT_EMITTED,
                data=payload,
                event_id=event_id,
                source="sensor_ingestion_gateway",
            ))
        except Exception:
            logger.exception("publish SensorEventEmitted failed")

        return SensorIngestionResult(
            event_id=event_id,
            ingested=True,
            stats={},  # 见 §6.1 stats 字段语义变化
        )

    def _resolve_memory_owner_user_id(self, output: SensorOutput) -> Optional[str]:
        ...  # 现有实现保留
```

**删除的字段/方法**：
- `_unified_memory`、`_timeline_adapter`、`_state_store` 字段
- `_build_memory_event` 方法（迁到 `sensor_memory_projection.py`）
- `_process_relations` 方法（迁到 KGSubscriber）
- 直接 `upsert_user_graph_edge` 调用

### 6.1 SensorIngestionResult.stats 字段破坏性变更

旧：`stats={"relation_count": int}` —— 同步路径下 producer 知道关系投影数。
新：`stats={}` —— producer publish 后立即返回，订阅者投影数不可知。

**实施前 grep**：

```bash
grep -rn "SensorIngestionResult\b\|\.stats\[\"relation_count\"\]" backend/src --include="*.py"
```

确认无硬依赖。如有调用方依赖该数字（例如 sensor scheduler 报告），用 metrics subscriber 暴露（D 子项目范围）。

文档化为已知破坏性变更。

## 7. 三个新订阅者

新建 `magi/awareness/subscribers/`：

### 7.1 TimelineSubscriber

```python
class TimelineSubscriber:
    """Project SensorEventEmitted into the timeline read model."""

    def __init__(self, *, event_bus, timeline_adapter) -> None:
        self._bus = event_bus
        self._adapter = timeline_adapter
        self._sub_id: Optional[str] = None
        self._inflight: set[asyncio.Task] = set()

    async def start(self) -> None:
        self._sub_id = await self._bus.subscribe(
            EventTypes.SENSOR_EVENT_EMITTED, self._on_event,
        )

    async def stop(self) -> None: ...
    async def drain(self) -> None: ...

    async def _on_event(self, event: Event) -> None:
        try:
            payload = expect_payload(event, SensorEventEmitted)
        except PayloadTypeError:
            return
        timeline_event_dict = build_timeline_event_dict(payload, event_id=event.event_id)
        timeline_event = TimelineEvent.from_dict(timeline_event_dict)
        timeline_event.event_id = event.event_id
        task = asyncio.create_task(self._safe_dispatch(timeline_event))
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _safe_dispatch(self, timeline_event: TimelineEvent) -> None:
        try:
            await self._adapter.on_timeline_event(timeline_event)
        except Exception:
            logger.exception("timeline_adapter.on_timeline_event failed (event=%s)", timeline_event.event_id)
```

`TimelineEvent.from_dict` —— 在 `awareness/timeline_event.py` 新增对称 classmethod。

### 7.2 KGSubscriber

```python
class KGSubscriber:
    """Project sensor relation candidates into the knowledge graph."""

    def __init__(self, *, event_bus, unified_memory) -> None:
        self._bus = event_bus
        self._memory = unified_memory
        self._sub_id: Optional[str] = None
        self._inflight: set[asyncio.Task] = set()

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def drain(self) -> None: ...

    async def _on_event(self, event: Event) -> None:
        try:
            payload = expect_payload(event, SensorEventEmitted)
        except PayloadTypeError:
            return
        if not payload.relation_candidates or not payload.allowed_edge_whitelist:
            return
        task = asyncio.create_task(self._process_relations(
            event_id=event.event_id,
            output_dict=payload.output_dict,
            relation_candidates=payload.relation_candidates,
            allowed_edge_whitelist=payload.allowed_edge_whitelist,
        ))
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _process_relations(
        self,
        *,
        event_id: str,
        output_dict: Mapping[str, Any],
        relation_candidates: tuple[Mapping[str, Any], ...],
        allowed_edge_whitelist: tuple[str, ...],
    ) -> int:
        # 整段从 SensorIngestionGateway._process_relations 迁过来
        # 接口签名调整：原来读 output / metadata 对象，现在读 output_dict / candidates
        ...
```

### 7.3 SensorStateUpdateSubscriber

```python
class SensorStateUpdateSubscriber:
    """Persist sensor source-item fingerprints to dedupe future ingest."""

    def __init__(self, *, event_bus, sensor_state_store) -> None:
        self._bus = event_bus
        self._state_store = sensor_state_store
        self._sub_id: Optional[str] = None
        self._inflight: set[asyncio.Task] = set()

    async def _on_event(self, event: Event) -> None:
        try:
            payload = expect_payload(event, SensorEventEmitted)
        except PayloadTypeError:
            return
        if not payload.sensor_fingerprint:
            return
        try:
            await self._state_store.add_fingerprints(
                payload.sensor_id, {payload.sensor_fingerprint},
            )
        except Exception:
            logger.exception(
                "sensor_state add_fingerprints failed (sensor=%s)", payload.sensor_id,
            )
```

简单到几乎透明，但保持范式一致。

### 7.4 Lifecycle 接入

`backend/src/magi/awareness/lifecycle.py` 新增 3 个 LifecycleModule（仿 B 的 RuntimeTraceSubscriberModule 模式）：

- `TimelineSubscriberModule` — deps `runtime_message_bus / runtime_timeline`
- `KGSubscriberModule` — deps `runtime_message_bus / runtime_memory`
- `SensorStateUpdateSubscriberModule` — deps `runtime_message_bus / runtime_core_dependencies`

shutdown 顺序按 §B-§6.2 模式：业务 stop → tracing.drain_pending → subscriber.stop → bus.stop。

## 8. MemoryIngestionSubscriber 适配

`event_translation.py::_from_sensor` 改造（消除 dict 旁路）：

```python
def _from_sensor(event: Event) -> Optional[MemoryEvent]:
    payload = expect_payload(event, SensorEventEmitted)
    if isinstance(payload.policy_dict, Mapping) and payload.policy_dict:
        # C 阶段主路径：用共享投影函数
        return build_sensor_memory_event(
            payload,
            event_id=event.event_id,
            correlation_id=event.correlation_id,
            causation_id=event.causation_id,
            trace_context=event.trace_context,
        )
    # A 阶段旧 producer（无 policy_dict）继续走老合成路径
    return _from_sensor_legacy(event)


def _from_sensor_legacy(event: Event) -> Optional[MemoryEvent]:
    """Pre-C path: SensorEventEmitted with only sensor_name + payload + context.
    
    Used by chat projector and any transitional producer that emits the lean
    A-era SensorEventEmitted shape. Will be removed when all producers upgrade.
    """
    # 现有 _from_sensor 实现移到这里
    ...
```

**设计要点**：
- 没有"如果 X 字段存在跳过 translate"那种隐契约——只有"new producer 用主路径，pre-C producer 用 legacy 路径"显式分支
- legacy 分支文档化为过渡期支持，可在所有 producer 迁移后删除
- 主路径是公共投影函数 `build_sensor_memory_event`——其他想构造 sensor MemoryEvent 的代码也复用

## 9. 测试策略

### 9.1 单元

- `tests/awareness/test_sensor_memory_projection.py`
  - `build_sensor_memory_event(payload)` 在不同 sensor / policy 组合下输出正确 MemoryEvent
  - `build_timeline_event_dict(payload)` 字段齐全
  - 与现 `SensorIngestionGateway._build_memory_event` 输出等价（参考用例）

- `tests/awareness/test_ingestion_gateway_publish.py`
  - mock event_bus，gateway.ingest 后 `SensorEventEmitted` publish 一次、所有字段齐全
  - publish 失败不影响返回值
  - SensorIngestionResult.event_id == publish 的 event.event_id（producer-assigned）

- `tests/awareness/subscribers/test_timeline_subscriber.py`
  - 发 `SensorEventEmitted` → `timeline_adapter.on_timeline_event` 调用一次，TimelineEvent.event_id == event.event_id
  - publish 失败不影响其他订阅者

- `tests/awareness/subscribers/test_kg_subscriber.py`
  - relation_candidates 矩阵：空 / 含候选 / whitelist 限制
  - `unified_memory.upsert_user_graph_edge` 调用次数与候选数一致
  - 个别候选失败不影响其他候选

- `tests/awareness/subscribers/test_sensor_state_subscriber.py`
  - 含 fingerprint → add_fingerprints 调用
  - 缺 fingerprint → 跳过

- `tests/memory/test_event_translation.py` 扩展
  - `_from_sensor` 主路径（含 policy_dict）测试
  - `_from_sensor_legacy` 路径（仅 A 字段）测试
  - 两路径输出语义等价（同样的 MemoryEvent.event_type / content / metadata_json）

### 9.2 集成

- `tests/integration/test_c_sensor_pipeline.py`
  - 真 InMemoryMessageBusBackend + 真 UnifiedMemoryStore + mock TimelineAdapter + mock SensorStateStore + 4 subscriber 全 wire
  - 手动构造一个 sensor + output → gateway.ingest()
  - 等待 drain → 验证：fact_events 行存在 + timeline_adapter.on_timeline_event 调用一次 + KG `upsert_user_graph_edge` 调用一次 + state_store.add_fingerprints 调用一次
  - 全部用同一 producer-assigned event_id 关联

### 9.3 回归

- 现有 `tests/awareness/` 测试：mock `unified_memory.ingest_event` 的断言改为 mock `event_bus.publish` 或 mock subscribers
- `tests/integration/test_l4_end_to_end.py` 不受影响（不涉及 sensor 路径）
- 端到端冒烟：触发 sensor → memory.db / timeline / KG 全部有数据

## 10. 实施分阶段

按依赖顺序，每阶段独立可发布：

1. **基础序列化**：
   - `SensorMemoryPolicy.to_dict / from_dict`：dataclass 字段 + `IngestTarget / MemoryDomain / TomDepth / RetentionClass` 这些 `_LabeledIntEnum` 全部用 **label 字符串**（如 `"l0_and_l1"`）作为 wire 格式（人类可读且 enum 已自带 `from_value` 兼容 label）。round-trip 单测覆盖。
   - `SensorProjection.to_dict`：当前不存在，新增；返回 `{"summary": ..., "metadata": {...}, ...}`。
   - `TimelineEvent.from_dict`：**已存在**于 `magi/timeline/contracts.py:43`——只需校验字段覆盖，不重写。
   - `MemoryEvent.from_dict`：评审反馈 #C3 指出本 spec 不需要——删除此项。
2. **`magi.awareness.sensor_memory_projection` 新模块**：`build_sensor_memory_event(payload, *, event_id, correlation_id, causation_id, trace_context)` + `build_timeline_event_dict(payload, *, event_id)`。逻辑等价于现 `_build_memory_event` + `build_sensor_timeline_event`。单测覆盖与现 gateway 输出等价（同 sensor / output / metadata 输入产生同 MemoryEvent / TimelineEvent dict）。
3. **SensorEventEmitted payload 扩字段**：纯加法，dataclass 新字段全 default。
4. **L1Layer idempotency 修订**（§12.1）：当 `find_event_id_by_idempotency` 返回 `existing_event_id != event.event_id` 时记 warning + 用 envelope id 作 stored_event_id。单测覆盖。
5. **TimelineSubscriber + 单测 + lifecycle module**。订阅者注册到 bus；gateway 仍直跑 timeline；新订阅者收不到事件（gateway 还没 publish）——无双写。
6. **KGSubscriber + `_process_relations` 迁过来 + lifecycle module**。同上。**实施前 grep `SensorOutput.to_dict` 实现，确认 `occurred_at / source_type` 字段在产出 dict 中**（评审 #C4）；如不齐先补 `to_dict()`。
7. **SensorStateUpdateSubscriber + lifecycle module**。同上。
8. **MemoryIngestionSubscriber `_from_sensor` 改主/legacy 双路径**。
9. **Gateway 改造为薄 publisher**：删除 `_unified_memory / _timeline_adapter / _state_store` 字段 + 删除 `_build_memory_event / _process_relations / 直接持有的 upsert_user_graph_edge 调用` + lifecycle 实例化更新（`SensorIngestionGateway(event_bus=...)`）+ 集成测试。**关键单步切换**：此阶段 publish 上线，所有订阅者立即激活。
10. **回归 + grep 验证（评审 #C9 扩展）**：
    - `grep "_unified_memory\." backend/src/magi/awareness/` → 0 命中
    - `grep "_timeline_adapter" backend/src/magi/awareness/ingestion_gateway.py` → 0 命中
    - `grep "_state_store" backend/src/magi/awareness/ingestion_gateway.py` → 0 命中
    - `grep "SensorIngestionGateway(" backend/src --include="*.py"` → 仅 `awareness/lifecycle.py:70` 一处
    - `grep "from .ingestion_gateway import" backend/src --include="*.py"` 与 lifecycle.py 唯一引用一致

每阶段独立可发布；中间状态下旧 gateway 路径与新订阅者不冲突（订阅者注册但收不到事件，因 gateway 阶段 9 才 publish）。完成后旧直调代码消失。
9. **回归 + grep**：`grep "_unified_memory" backend/src/magi/awareness/` 应为 0；`grep "_timeline_adapter" backend/src/magi/awareness/ingestion_gateway.py` 应为 0。

每阶段独立可发布；中间状态下旧 gateway 路径与新订阅者并存（无写入冲突，因 producer-assigned event_id idempotent）。完成后旧直调代码消失。

## 11. 错误隔离 / 性能

### 错误隔离

- gateway publish 失败 → 仅日志、返回 ingested=True 的 result（caller 看不出失败）
- TimelineSubscriber / KGSubscriber / SensorStateUpdateSubscriber 各自 try/except 包裹核心逻辑，handler 抛错被 subscriber 内部吞下
- 单订阅者失败不影响其他订阅者
- MemoryIngestionSubscriber 失败也不影响 timeline / KG / state

**与现状对比**：旧代码下任一步失败都会让后续步骤跳过（早 return）。CQRS 后每步独立。这是有意的语义升级。

### 性能

- gateway publish 路径：1 次 ULID + 数次 dict 序列化（policy / projection / metadata）+ 1 次 publish。比现状少了 4 次同步 await（memory / timeline / KG / state），latency 明显下降。
- 4 个订阅者并发投影（每个 create_task）。InMemoryMessageBusBackend 内部串行触发 handler，但 handler 立即 create_task 卸载。
- sensor 频率：现有 awareness 配置下平均 < 1 次/秒，余量充足

## 12. 风险与缓解

| 风险 | 缓解 |
|------|------|
| `SensorIngestionResult.stats["relation_count"]` 调用方依赖被破坏 | 实施前 grep；若发现真实依赖，保留字段但语义文档化为"候选数"，长期废弃 |
| MemoryPolicy / SensorProjection 没有完整 to_dict/from_dict 对称 | C-1 阶段先补全，单测覆盖 round-trip |
| `_from_sensor` 主路径与 legacy 路径输出不一致 | C-7 阶段写"两路径输出等价"测试，确保 chat projector 时代行为不变 |
| Sensor scheduler 与新 gateway 实例化签名变化 | grep `SensorIngestionGateway(` → 已知唯一调用点 `awareness/lifecycle.py:70`，统一改 |
| timeline_adapter 内部假设"事件已写入 memory" | 调研：`on_timeline_event` 只是 read model 更新，不依赖 memory 写入。OK |
| KG `upsert_user_graph_edge` 内部假设"event_id 在 fact_events 已存在"（FK 或 join） | 调研：`upsert_user_graph_edge` 只把 event_id 当字符串存到 evidence_event_ids，不做 join。OK |
| 4 个订阅者订阅同一事件 → bus 串行触发 → 累计延迟 | handler 内 create_task 卸载；累计 < 1ms；非 hot path |
| **L1 idempotency dedupe → producer event_id ≠ stored_event_id** | 见 §12.1 单独处理 |
| **阶段 4-7 中间状态下双写 timeline / KG**（gateway 直跑 + 新订阅者已注册） | 见 §12.2 单独处理 |

### 12.1 L1 idempotency 与 producer event_id 一致性

**问题**：当 `MemoryEvent.idempotency_key` 命中 L1 既有行（`find_event_id_by_idempotency` 返回 `existing_event_id`），L1Layer 把 `markers["stored_event_id"]` 设为旧行的 id，与 envelope 持有的 producer event_id 不同。Timeline / KG / SensorState 订阅者按设计用 envelope id；MemoryIngestionSubscriber 走 ingest 后内部用 stored_event_id（老行）。下游 `evidence_event_ids=[envelope_id]` 会指向一行不存在的 fact_events。

**采用策略 (a)：producer event_id 是权威 id**：
- MemoryIngestionSubscriber 在调 `unified_memory.ingest_event` 之前，先用 envelope `event_id` 覆盖 `MemoryEvent.event_id`（C-7 阶段 `_from_sensor` 已经这么做）。L1Layer 收到的 `event` 已带正确 id。
- L1Layer 中的 idempotency fast-path 仍可能命中，**但命中行的 event_id 应当与 envelope id 相同**——因为：
  - producer-assigned event_id 由 ULID 生成，不会重复
  - 真正命中的场景是事件**重放**（相同 envelope event_id + 相同 idempotency_key）—— 此时 dedupe 是正确行为
- 改造 L1Layer：当 `find_event_id_by_idempotency` 返回的 `existing_event_id` ≠ `event.event_id` 时，记 warning + 优先使用 `event.event_id`（拒绝静默换 id）。强约束：每个业务事件 id 唯一权威。

```python
# l1_layer.py 改造
if existing_event_id is not None and existing_event_id != event.event_id:
    logger.warning(
        "L1 idempotency hit returned a DIFFERENT event_id; honoring envelope id "
        "to preserve cross-subscriber consistency",
        envelope_id=event.event_id,
        existing_id=existing_event_id,
        idempotency_key=event.idempotency_key,
    )
    # 仍然走 dedupe（不重复 INSERT），但 markers 用 envelope id
    stored_event_id = event.event_id
elif existing_event_id is not None:
    stored_event_id = existing_event_id  # == event.event_id, no-op
else:
    stored_event_id = await self._store.store(event)
```

测试：构造同 idempotency_key 不同 envelope id 的两次 ingest，断言 markers["stored_event_id"] == 第二次的 envelope id。

### 12.2 阶段 4-7 中间状态下的双写问题

**问题**：spec §10 阶段 4-7 完成后 TimelineSubscriber / KGSubscriber / SensorStateUpdateSubscriber 已注册，但 gateway 还在 §10 阶段 8 才改成 publisher——中间状态下，每次 sensor.ingest：
1. gateway 同步直跑 timeline / KG / state（旧路径）
2. gateway 调 publish（A 阶段已有的 SensorEventEmitted publish——但当前 gateway 没 publish 这条事件！）

确认：A 阶段对 sensor 路径**没有改 publish**——只有 chat projector 改了。所以 gateway 现状只直跑、不 publish；新订阅者注册后也不会被触发。**中间状态实际无双写**。

**重新校正阶段 8**：当 gateway 改成 publisher 时，订阅者已就位、立即开始接收事件、gateway 旧路径删除——单步切换。

**实施前 grep 验证**：

```bash
grep -rn "SENSOR_EVENT_EMITTED\|publish.*SensorEventEmitted" backend/src/magi/awareness backend/src/magi/chat --include="*.py"
```

确认现有代码无 sensor publish 路径。

如果 grep 结果发现 awareness 路径已 publish（A 阶段做了但本 spec 没记到），则把 §10 改为：阶段 4-7 增加 feature flag `enable_subscribers=False` 守门，阶段 8 再 flip 为 True。

### 12.3 _process_relations 输入字段映射验证

KGSubscriber 的 `_process_relations` 从 gateway 迁移时签名变化：
- 旧：读 `output.occurred_at` / `output.source_type` / `metadata.relation_candidates` (list of dict)
- 新：读 `output_dict["occurred_at"]` / `output_dict["source_type"]` / `relation_candidates: tuple[Mapping]`

实施前 grep `output.to_dict()` 实现，确认 `occurred_at / source_type` 都在产出 dict 中。如不齐，先补 `to_dict()`。

| **`default_user_id` 参数实际未使用** | 删除 §6 gateway 的 `default_user_id` 参数。owner 解析现有 `_resolve_memory_owner_user_id` 已经从 `runtime_defaults.DEFAULT_USER_ID` 兜底，不需 gateway 持有 |

## 13. 已知技术债（接受）

C 完成后仍存在，留给后续迭代：

- **胖 SensorEventEmitted**：所有 4 订阅者用的字段共存于一个事件。若未来字段超过 ~12 或多个订阅者忽略同一字段，应考虑拆分事件类型（D 子项目时机）。
- **SensorStateUpdateSubscriber 几乎为空**：3 行有效逻辑、为范式一致性付费。如果 sensor_state 永远只是 add_fingerprints，订阅者层是个轻量包装。可接受。
- **legacy `_from_sensor_legacy` 路径**：A 阶段 chat projector 仍在用。完全移除需要后续清理。

## 14. Open Questions

无。

## 15. 评审记录

2026-05-05 经 spec-document-reviewer 评审，已修复以下问题：

**Critical**：
- C1: L1 idempotency dedupe 时 producer event_id ≠ stored_event_id 会让 timeline / KG 引用一个 fact_events 中不存在的 id。新增 §12.1 决定"producer event_id 是权威 id"，L1Layer 检测 mismatch 时以 envelope id 作 stored_event_id。
- C2: §6 gateway 引入了未使用的 `default_user_id` 参数。删除。
- C3: §10 阶段 1 的序列化清单：`TimelineEvent.from_dict` **已存在**于 `magi/timeline/contracts.py:43`，无需重写；`MemoryEvent.from_dict` 不在本 spec 范围内，删除；`SensorMemoryPolicy` enum 字段用 label 字符串作为 wire format（人类可读且现 enum 已有 `from_value(label)` 兼容）；`SensorProjection.to_dict` 当前不存在，C-1 阶段新增。

**Important**：
- C4: KGSubscriber `_process_relations` 迁移时输入字段从 object 变 dict——§10.6 增加"实施前 grep `SensorOutput.to_dict` 实现确认 occurred_at / source_type 字段齐全"。
- C5: §10 阶段 4-7 中间状态双写疑虑澄清——A 阶段 sensor 路径未改 publish，gateway 仍走老同步路径、新订阅者注册但收不到事件——无双写。§12.2 文档化此事实并要求实施前 grep 确认。spec §10 阶段重新编号：4 是 L1 idempotency 修订（新增）、5/6/7 注册三订阅者、8 改 gateway 是关键单步切换。
- C6: KG 双写 idempotency 在 §12.2 单步切换设计下不再发生。

**Minor**：
- §12 新增"L1 idempotency"和"中间状态双写"风险条目。
- §10.10 grep 验证清单扩展：`_state_store / SensorIngestionGateway( / from .ingestion_gateway import` 均加入。
