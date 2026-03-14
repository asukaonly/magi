# Agent 核心记忆系统架构设计文档

> 版本: 1.1
> 日期: 2026-03-14
> 状态: 可实施草案

## 0. 文档目标

本文档定义 Magi 下一代核心记忆系统的可实施架构。

### 0.1 文档边界

为避免架构语义重复或冲突，本文档采用以下边界：

1. 根目录 `docs/`（`project-overview.md`、`product-configuration-guide.md`、`task-agent-runtime-architecture.md`）是项目级与产品级语义基线。
2. 本文档仅负责 memory 子系统的实现级设计、数据契约、分层策略与落地约束。
3. 若本文档与根目录 `docs/` 出现冲突，以根目录 `docs/` 为准，并在 memory 文档内同步修订。

目标不是单纯为大模型补充上下文，而是构建一个服务于用户长期记忆维护、事件回顾、模式洞察、关系感知与行为策略沉淀的本地优先记忆系统。

本文档覆盖：

1. 目标架构与边界
2. 各层数据模型与处理流程
3. 检索与 prompt 集成契约
4. 遗忘与保留策略
5. 与当前实现的替换关系
6. 分阶段落地方案与验收标准

本文档不覆盖：

1. 历史数据迁移
2. 旧表兼容
3. 向后兼容路径

本轮改造允许删除旧数据与旧表结构，直接切换到新架构。

---

## 1. 已确认的设计决策

以下决策已确认，后续实现以此为准：

1. **分层原则**：按信息生命周期分层，而不是按功能插件分层。
2. **系统目标**：核心服务于用户长期记忆与自我感知体系，而不是仅服务于回复增强。
3. **向量定位**：向量是 L1/L3/L4 的检索属性，不是独立层级。
4. **L4 定位**：L4 属于程序性记忆，负责沉淀“如何做一件事”的经验与策略，包括工具使用经验、异常处理肌肉记忆、熔断状态。
5. **L0 介质**：L0 默认以内存为主，采用 checkpoint 定时落盘到 SQLite，用于恢复与异常重启保护。
6. **ToM 必做**：L2 必须支持 ToM，但必须采用防御性设计，主观推断先进入低置信度断言层，经跨事件验证后才固化到稳定画像。
7. **LLM 策略**：本期优先采用全 LLM 抽取方案，但各层能力都必须支持独立开关。
8. **保留策略**：事件是否可压缩/删除取决于事件类型；聊天记录与用户主动记录默认不可删，浏览记录与部分外部活动默认可压缩删除。
9. **污染隔离**：L1 中允许存在运行时遥测事件，但它们必须在评分、摘要、图谱与 ToM 流程中被默认隔离，不能与用户长期经验事件混算。

---

## 2. 现状与主要问题

当前实现位于以下模块：

- [UnifiedMemoryStore](/Users/asuka/code/magi/backend/src/magi/memory/__init__.py)
- [RawEventStore](/Users/asuka/code/magi/backend/src/magi/memory/raw_event_store.py)
- [EventRelationStore](/Users/asuka/code/magi/backend/src/magi/memory/l2_event_relations.py)
- [L2UserGraphStore](/Users/asuka/code/magi/backend/src/magi/memory/l2_user_graph.py)
- [eventEmbeddingStore](/Users/asuka/code/magi/backend/src/magi/memory/l3_semantic_embeddings.py)
- [SummaryStore](/Users/asuka/code/magi/backend/src/magi/memory/l4_summaries.py)
- [CapabilityMemory](/Users/asuka/code/magi/backend/src/magi/memory/l5_capabilities.py)
- [MemoryIntegrationModule](/Users/asuka/code/magi/backend/src/magi/memory/integration.py)

当前方案的主要问题：

1. **分层语义不统一**：当前 L1-L5 更像功能模块堆叠，而不是围绕“事件 -> 认知 -> 摘要 -> 程序性经验”的生命周期演化。
2. **短期工作记忆缺位**：Prompt 组装仍然手工传入 `short_term_workbench` 等占位结构，缺少真正的 L0。
3. **L2 结构割裂**：事件关系图与用户图分成两套存储，没有统一的实体、证据、冲突与置信度模型。
4. **向量独立成层**：向量与事件本体分离，导致检索与事件主存之间缺少统一契约。
5. **摘要层定位不清**：当前 summary 更像统计 digest，而不是经过反思后的长期压缩记忆。
6. **程序性经验表达不足**：当前 capability 只覆盖简单成功率与分类匹配，无法承载更强的策略学习与熔断状态。
7. **检索链路未真正跨层**：虽然 query service 名义上支持跨层，但实际仅注册了 L1 查询处理器。
8. **污染风险存在**：当前 L1 会混入用户消息、动作执行、错误、worker 进度等事件；如果不隔离，会导致重要度评分、摘要主题、关系图与 ToM 被运行时噪声主导。

### 2.1 什么叫“评分、摘要、图谱被污染”

这里的“污染”不是指数据错误，而是指**不同语义层级的事件被混为同一种长期经验材料**，从而让下游认知结果产生系统性偏差。

典型例子：

1. 如果 `WORKER_AGENT_PROGRESS`、`LOOP_STARTED`、`TASK_ASSIGNED` 这种高频运行时事件和用户真实交互事件一起算 importance，那么真正对用户重要的聊天、日记、浏览线索会被频率更高的系统噪声淹没。
2. 如果摘要生成不区分“用户经验事件”和“系统控制事件”，周摘要可能总结成“本周大量任务启动、完成、失败重试”，而不是“用户这周主要在准备面试、浏览文档、情绪波动上升”。
3. 如果知识图谱直接吃入未经筛选的运行时事件，图谱会学到大量“事件与事件之间的流程关系”，却学不到“用户与项目、人物、主题之间的长期关系”。
4. 如果 ToM 从群聊日志、截图 OCR、worker 错误中一视同仁地深挖心理状态，就会高频产出主观而不可靠的心理断言。

因此，新架构必须允许 L1 接收多种事件，但必须在事件标准化时明确它们的记忆用途。

---

## 3. 目标架构总览

```text
┌──────────────────────────────────────────────────────────────────┐
│                     Retrieval & Prompt Layer                     │
│  HybridRetrievalService + PromptContextAssembler integration     │
└──────────────────────────────────────────────────────────────────┘
                               ↓
┌──────────────────────────────────────────────────────────────────┐
│ L0 Working Memory                                                │
│ In-memory workbench + SQLite checkpoint                          │
│ session / goal stack / active entities / temporary ToM tactics   │
├──────────────────────────────────────────────────────────────────┤
│ L1 Event Stream                                                  │
│ Immutable normalized events + embedded vectors + importance      │
│ retention policy + source taxonomy + traceability                │
├──────────────────────────────────────────────────────────────────┤
│ L2 Structured Cognition                                          │
│ knowledge_graph + tom_snapshots + tom_trait_assertions           │
│ conflict resolution + evidence validation                        │
├──────────────────────────────────────────────────────────────────┤
│ L3 Reflection Memory                                             │
│ temporal summaries + thematic summaries + distilled insights     │
│ summary vectors + evidence backtrace                             │
├──────────────────────────────────────────────────────────────────┤
│ L4 Procedural Memory                                             │
│ tool/api/workflow skills + circuit breaker + best practices      │
│ strategy templates + context affinity                            │
└──────────────────────────────────────────────────────────────────┘
                               ↑
┌──────────────────────────────────────────────────────────────────┐
│                  Ingestion & Maintenance Layer                   │
│ MemoryIntegrationModule / LLM extractors / MaintenanceDaemon     │
└──────────────────────────────────────────────────────────────────┘
```

### 3.1 核心处理原则

1. **L1 是事实主存**：所有长期记忆能力都从 L1 事件流演化。
2. **L0 是临时执行态**：L0 服务当前会话与当前任务，不直接承担长期认知结论。
3. **L2 是有证据的解释层**：所有主观认知必须带证据、置信度和可回滚状态。
4. **L3 是压缩层**：L3 不替代 L1，而是降低检索与回顾成本。
5. **L4 是经验层**：L4 把成功/失败历史转为未来执行准则。
6. **所有主观推断默认低置信度进入系统**：只有跨事件验证后才能升级为稳定记忆。

### 3.2 明确不纳入本轮重构的模块

以下模块本轮不与新记忆系统合并：

1. `SelfMemory`
2. `OtherMemory`
3. 人格配置与 scenario prompt 存储

这些模块仍然继续工作，但 prompt 组装时要新增读取新记忆系统的路径。

---

## 4. 事件来源分型与污染隔离

### 4.1 事件来源分型

L1 的每条事件必须带以下分类字段：

```python
memory_domain: Literal[
    "user_authored",      # 用户主动写下/说出的内容，如聊天、日记、手动时间线
    "interaction",        # Agent 与用户的直接交互，如回复、澄清、工具结果回传
    "external_activity",  # 浏览、终端、git、日历、健康等外部活动
    "runtime_telemetry",  # worker 进度、调度、系统错误、loop 事件
    "system_control",     # 配置变更、内部维护、checkpoint、压缩等控制类事件
]
```

### 4.2 记忆用途分型

每条事件还必须带以下策略字段：

```python
ingest_target: Literal[
    "l0_only",                  # 仅进入 L0，作为当前执行态信号
    "l0_and_l1",                # 先服务当前执行，再进入 L1 做审计/复盘
    "l1_only",                  # 直接进入 L1，不参与当前执行态缓存
]
cognition_eligible: bool        # 是否允许进入 L2/L3/L4 推导
tom_depth: Literal[
    "none",                     # 不做 ToM
    "topology_only",            # 只抽取显性关系与情感倾向
    "defensive_psychology",     # 允许做防御性心理推断
]
retention_class: Literal[
    "permanent",                # 默认不可压缩删除
    "compressible",             # 允许压缩保留摘要
    "disposable",               # 低价值可删除
]
```

### 4.3 运行时事件分流规则

对于 `WORKER_AGENT_PROGRESS`、`LOOP_STARTED`、`TASK_ASSIGNED` 这类事件，不采用“要么全进 L0，要么全进 L1”的二选一策略，而是按执行价值与长期价值分流：

1. **只服务当前运行态的高频事件**：默认 `l0_only`
2. **值得审计/复盘的里程碑事件**：默认 `l0_and_l1`
3. **不属于当前执行态，但需要长期保留的关键事件**：默认 `l1_only`

判断标准：

1. 该事件是否只服务当前执行态
2. 该事件未来是否值得审计、回放、排障
3. 该事件是否会影响未来行为策略

### 4.4 默认策略矩阵

| 来源 | ingest_target | domain | cognition_eligible | tom_depth | retention_class |
|------|---------------|--------|--------------------|-----------|-----------------|
| 聊天记录 | l1_only | user_authored | true | defensive_psychology | permanent |
| 用户手动日记/时间线 | l1_only | user_authored | true | defensive_psychology | permanent |
| 浏览历史 | l1_only | external_activity | true | topology_only | compressible |
| 终端/Git 活动 | l1_only | external_activity | true | none | compressible |
| 照片/OCR/群聊 | l1_only | external_activity | true | topology_only | compressible |
| WORKER_AGENT_PROGRESS | l0_only | runtime_telemetry | false | none | disposable |
| LOOP_STARTED / LOOP_PHASE_STARTED / HEARTBEAT | l0_only | system_control | false | none | disposable |
| TASK_ASSIGNED / TASK_STARTED | l0_and_l1 | runtime_telemetry | false | none | compressible |
| TASK_COMPLETED / TASK_FAILED | l0_and_l1 | runtime_telemetry | false | none | compressible |
| 系统错误 / 熔断切换 / 策略变更 | l1_only | runtime_telemetry | false | none | compressible |

### 4.5 运行时事件的特殊说明

1. `l0_only` 事件默认不进入长期记忆主存，避免高频噪声灌爆 L1。
2. `l0_and_l1` 事件进入 L1 后，默认只用于审计、排障、回放与 L4 程序性经验提炼，不参与 L2/L3 主认知链路。
3. `TASK_COMPLETED`、`TASK_FAILED`、熔断状态变更这类事件虽然属于 runtime 事件，但可能改变未来执行路径，因此保留进入 L1 的资格。
4. 若用户未来明确要求“完整运行时回放”，可通过配置将部分 `l0_only` 事件升级为 `l0_and_l1`。

### 4.6 群体内容的特殊规则

群聊、截图 OCR、公共社交文本等多实体内容默认不做深度单体心理诊断，仅允许抽取：

1. 实体显性关系
2. 公开立场
3. 话题情绪倾向
4. 群体氛围

禁止默认产出“某个群成员存在某种深层心理问题”之类高主观结论。

---

## 5. L0 工作记忆

### 5.1 目标

L0 用于支撑单次会话与单个任务的高频上下文组装，负责：

1. 当前 session 生命周期
2. 当前目标栈与任务状态
3. 当前活跃实体卡片
4. 低置信度临时策略
5. prompt 侧的短期 workbench

L0 不承诺长期稳定，长期沉淀由 L2/L3/L4 负责。

### 5.2 存储模式

默认策略：

1. 主存：内存
2. 恢复介质：SQLite checkpoint
3. checkpoint 时机：
   - 固定时间间隔
   - 会话空闲前
   - 会话关闭前
   - 进程退出前

#### 5.2.1 配置项

```python
@dataclass
class L0Config:
    storage_mode: Literal["memory_checkpoint"] = "memory_checkpoint"
    checkpoint_db_path: str = "~/.magi/data/l0_working_context.db"
    checkpoint_interval_seconds: int = 30
    session_timeout_seconds: int = 3600
    max_active_entities_per_session: int = 64
    max_temporary_tactics_per_session: int = 32
    restore_on_restart: bool = True
```

### 5.3 数据模型

#### 5.3.1 sessions

```sql
CREATE TABLE l0_sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT,
    runtime_agent_id TEXT,
    status TEXT NOT NULL,               -- active, idle, completed, expired
    started_at REAL NOT NULL,
    last_active_at REAL NOT NULL,
    last_checkpoint_at REAL,
    metadata TEXT
);
```

#### 5.3.2 goal_stack

```sql
CREATE TABLE l0_goal_stack (
    stack_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    goal_id TEXT NOT NULL,
    parent_goal_id TEXT,
    goal_type TEXT NOT NULL,            -- task, subtask, clarification, reflection
    description TEXT NOT NULL,
    status TEXT NOT NULL,               -- pending, in_progress, completed, failed, cancelled
    priority INTEGER DEFAULT 0,
    created_at REAL NOT NULL,
    started_at REAL,
    completed_at REAL,
    result_summary TEXT,
    metadata TEXT
);
```

#### 5.3.3 active_entities

```sql
CREATE TABLE l0_active_entities (
    session_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    relevance_score REAL DEFAULT 0.0,
    snapshot_json TEXT NOT NULL,
    loaded_at REAL NOT NULL,
    last_accessed_at REAL NOT NULL,
    access_count INTEGER DEFAULT 0,
    PRIMARY KEY (session_id, entity_id, entity_type)
);
```

#### 5.3.4 temporary_tactics

用于存放仅在 L0 生效、尚未升级到 L2/L4 的临时策略，例如：

1. “当前先以倾听式回应”
2. “暂时降低追问强度”
3. “本轮不要对某主题继续推断”

```sql
CREATE TABLE l0_temporary_tactics (
    tactic_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    scope_type TEXT NOT NULL,           -- user, topic, entity, tool
    scope_id TEXT NOT NULL,
    tactic_type TEXT NOT NULL,
    tactic_payload TEXT NOT NULL,
    source_event_ids TEXT NOT NULL,
    expires_at REAL,
    created_at REAL NOT NULL
);
```

### 5.4 职责归属

| 模块 | 职责 |
|------|------|
| `ChatTaskAgent` | 建立/续期 session |
| `TaskOrchestrator` | 更新 goal stack |
| `PromptContextAssembler` | 读取 active_entities 与 temporary_tactics |
| `MaintenanceDaemon` | 清理超时 session 与 checkpoint |

---

## 6. L1 原始事件流

### 6.1 目标

L1 是所有长期记忆能力的事实主存，记录不可变事件，提供：

1. 时间序查询
2. 精确过滤
3. 语义检索
4. 证据回溯
5. 保留与压缩决策

### 6.2 标准事件契约

所有写入 L1 的事件在进入数据库前必须完成标准化：

```python
@dataclass
class MemoryEvent:
    event_id: str
    correlation_id: str
    parent_event_id: str | None
    timestamp: float
    created_at: float

    event_type: str
    source: str
    source_item_id: str | None

    memory_domain: str
    cognition_eligible: bool
    tom_depth: str
    retention_class: str

    session_id: str | None
    user_id: str | None
    task_id: str | None
    goal_id: str | None

    raw_content: str
    structured_payload: str
    metadata: str

    importance_score: float
    importance_t0_base: float
    importance_t1_score: float | None
    importance_version: int

    semantic_vector: bytes | None
    vector_model: str | None
    vector_generated_at: float | None
    vector_status: str
    vector_retry_count: int
    vector_error: str | None

    level: int
    media_path: str | None
    deleted_at: float | None
```

### 6.3 表结构

```sql
CREATE TABLE events (
    event_id TEXT PRIMARY KEY,
    correlation_id TEXT NOT NULL,
    parent_event_id TEXT,

    timestamp REAL NOT NULL,
    created_at REAL NOT NULL,

    event_type TEXT NOT NULL,
    source TEXT NOT NULL,
    source_item_id TEXT,

    memory_domain TEXT NOT NULL,
    cognition_eligible INTEGER NOT NULL DEFAULT 0,
    tom_depth TEXT NOT NULL DEFAULT 'none',
    retention_class TEXT NOT NULL DEFAULT 'compressible',

    session_id TEXT,
    user_id TEXT,
    task_id TEXT,
    goal_id TEXT,

    raw_content TEXT NOT NULL,
    structured_payload TEXT,            -- JSON
    metadata TEXT,                      -- JSON

    importance_score REAL NOT NULL DEFAULT 0.5,
    importance_t0_base REAL,
    importance_t1_score REAL,
    importance_version INTEGER NOT NULL DEFAULT 1,

    semantic_vector BLOB,
    vector_model TEXT,
    vector_generated_at REAL,
    vector_status TEXT NOT NULL DEFAULT 'pending',
    vector_retry_count INTEGER NOT NULL DEFAULT 0,
    vector_error TEXT,

    level INTEGER NOT NULL DEFAULT 1,
    media_path TEXT,
    deleted_at REAL
);

CREATE INDEX idx_events_timestamp ON events(timestamp);
CREATE INDEX idx_events_type ON events(event_type);
CREATE INDEX idx_events_source ON events(source);
CREATE INDEX idx_events_domain ON events(memory_domain);
CREATE INDEX idx_events_user ON events(user_id);
CREATE INDEX idx_events_session ON events(session_id);
CREATE INDEX idx_events_goal ON events(goal_id);
CREATE INDEX idx_events_importance ON events(importance_score DESC);
CREATE INDEX idx_events_vector_status ON events(vector_status);
CREATE INDEX idx_events_retention ON events(retention_class);
CREATE INDEX idx_events_metadata_action ON events(json_extract(metadata, '$.action'));
```

### 6.4 时间分片

L1 采用时间分片，但对上暴露统一仓储接口。

默认策略：

1. 分片粒度：月
2. 热分片：最近 2 个
3. 冷分片：其余历史分片
4. 检索策略：
   - 默认先查热分片
   - 用户明确指定长时间范围时查全分片
   - 聚类/回顾型任务允许跨分片 scatter-gather

### 6.5 importance 评分

#### 6.5.1 T0 同步规则层

写入时同步完成，保证每条事件都有基础 importance。

#### 6.5.2 T1 异步语义层

本期使用 LLM 执行，基于以下维度：

1. 新颖性
2. 目标相关性
3. 情绪强度
4. 长期价值
5. 关系变化强度

#### 6.5.3 T2 检索时动态层

检索时叠加时间衰减、source boost、evidence boost。

### 6.6 写入流程

```text
1. Runtime event / timeline event / external activity arrives
2. EventNormalizer 标准化 MemoryEvent
3. Raw event sync write into L1
4. L0 session/workbench updates
5. Async enqueue:
   - vector generation
   - T1 importance
   - L2 cognition extraction
   - L3 summary candidate update
   - L4 procedural update
6. Return ack to caller
```

说明：

1. “全 LLM”指 L2/L3/T1 的认知工作由 LLM 执行。
2. 不要求主业务请求阻塞等待所有 LLM 任务完成。
3. 任何认知失败都不能影响 L1 原始事件落库。

---

## 7. L2 结构化认知

### 7.1 目标

L2 负责把 L1 中的长期有效信息转为结构化认知，分为两类：

1. **知识图谱**：稳定关系、实体属性、事件证据
2. **ToM**：对个体与群体的状态、偏好、情绪、压力、敏感触发器、氛围等进行防御性建模

### 7.2 为什么 ToM 需要双层结构

如果直接把 LLM 的主观推断写进稳定快照，会导致两个问题：

1. 一次性误判被固化
2. 低置信度心理判断与高置信度事实关系混杂，后续无法回滚

因此 L2 必须拆成：

1. `knowledge_graph`：稳定关系层
2. `tom_trait_assertions`：主观推断断言层
3. `tom_snapshots`：高置信度物化快照层

其中：

1. `tom_trait_assertions` 是防腐层与主观推断主存
2. `tom_snapshots` 只保存已经过验证的结果视图

### 7.3 knowledge_graph

```sql
CREATE TABLE knowledge_graph (
    triple_id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object_id TEXT NOT NULL,
    object_type TEXT NOT NULL,

    confidence REAL NOT NULL DEFAULT 0.5,
    evidence_event_ids TEXT NOT NULL,   -- JSON
    observation_count INTEGER NOT NULL DEFAULT 1,

    first_observed_at REAL NOT NULL,
    last_observed_at REAL NOT NULL,
    last_confirmed_at REAL,

    source_type TEXT,
    extraction_method TEXT,

    status TEXT NOT NULL DEFAULT 'active',   -- active, deprecated, conflicted
    deprecated_by TEXT,
    deprecated_at REAL,

    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
```

### 7.4 tom_trait_assertions

该表直接承载你确认的防误判字段。

```sql
CREATE TABLE tom_trait_assertions (
    assertion_id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,

    trait_name TEXT NOT NULL,               -- 例如“存在职场竞争焦虑”
    trait_value TEXT NOT NULL,              -- JSON 或字符串化值
    confidence_score REAL NOT NULL,         -- 0.0 - 1.0
    evidence_events TEXT NOT NULL,          -- JSON: 至少可追到多个 L1 event_id
    volatility_index REAL NOT NULL,         -- 0.0 - 1.0

    source_domain TEXT NOT NULL,            -- user_authored / external_activity ...
    inference_depth TEXT NOT NULL,          -- topology_only / defensive_psychology
    validation_state TEXT NOT NULL,         -- tentative, corroborated, stable, contradicted, expired

    first_inferred_at REAL NOT NULL,
    last_validated_at REAL NOT NULL,
    expires_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE INDEX idx_tom_assert_entity ON tom_trait_assertions(entity_id, entity_type);
CREATE INDEX idx_tom_assert_trait ON tom_trait_assertions(trait_name);
CREATE INDEX idx_tom_assert_conf ON tom_trait_assertions(confidence_score DESC);
CREATE INDEX idx_tom_assert_state ON tom_trait_assertions(validation_state);
```

### 7.5 tom_snapshots

该表保存高置信度稳定结果，供 prompt 与检索直接读取。

```sql
CREATE TABLE tom_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,

    core_traits TEXT,                  -- JSON
    sensitive_triggers TEXT,           -- JSON
    preferences TEXT,                  -- JSON
    public_sentiment_profile TEXT,     -- JSON
    relationship_topology TEXT,        -- JSON

    current_stress_level REAL DEFAULT 0.0,
    current_mood TEXT,
    current_engagement REAL DEFAULT 0.5,
    current_context TEXT,              -- JSON

    interaction_count INTEGER DEFAULT 0,
    last_interaction_at REAL,

    last_updated_at REAL NOT NULL,
    update_source_assertion_ids TEXT,  -- JSON
    snapshot_version INTEGER DEFAULT 1,
    created_at REAL NOT NULL,

    UNIQUE(entity_id, entity_type)
);
```

### 7.6 强宣称验证规则

所有主观推断默认遵循以下规则：

1. 初次抽取时 `confidence_score` 强制低分，默认不高于 `0.3`。
2. 单条事件的推断只能进入 `tentative`。
3. 只有满足以下条件，断言才允许进入 `stable` 并物化到 snapshot：
   - 至少 3 个独立的 L1 `event_id`
   - 时间跨度超过 24 小时
   - 没有明显矛盾证据
   - 置信度大于或等于 `0.8`
4. 遇到反证事件时：
   - `confidence_score` 快速下降
   - `validation_state` 可进入 `contradicted`
   - 如已物化到 snapshot，则触发回写修正
5. 低置信度推断允许只在 L0 产生短期策略，不得直接进入长期画像。

### 7.7 不同来源的 ToM 深度

#### 7.7.1 聊天 / 日记 / 用户主动记录

允许：

1. stress
2. mood
3. triggers
4. 长期偏好
5. 关系变化

#### 7.7.2 群聊 / 截图 / OCR / 照片描述

允许：

1. 公开情绪倾向
2. 实体间显性拓扑
3. 群体氛围

默认不做：

1. 深度心理诊断
2. 单实体长期病理推断

### 7.8 冲突处理

默认策略：

1. 事实关系：`confidence_wins`
2. 心理断言：`coexist + revalidate`
3. 高波动特征：优先保留时间序列，不强行合并成稳态

---

## 8. L3 反思与摘要

### 8.1 目标

L3 用于对 L1 事件进行降维压缩，产出便于长期回顾与快速检索的反思记忆。

L3 的输出分三类：

1. `temporal`：按小时/天/周/月的时序摘要
2. `thematic`：跨时间的主题摘要
3. `insight`：从压缩、聚类或对比中生成的高阶结论

### 8.2 表结构

```sql
CREATE TABLE summaries (
    summary_id TEXT PRIMARY KEY,
    summary_type TEXT NOT NULL,         -- temporal, thematic, insight
    summary_category TEXT NOT NULL,     -- hour/day/week/topic/...
    period_start REAL NOT NULL,
    period_end REAL NOT NULL,

    content TEXT NOT NULL,
    key_topics TEXT,
    key_entities TEXT,
    sentiment_summary TEXT,

    semantic_vector BLOB,
    vector_model TEXT,
    vector_generated_at REAL,

    source_event_ids TEXT NOT NULL,
    source_event_count INTEGER NOT NULL,

    importance_aggregate REAL,
    event_type_distribution TEXT,

    generated_by_model TEXT,
    generation_prompt TEXT,
    generation_reason TEXT,

    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
```

### 8.3 生成触发

本期先做全 LLM 方案，默认采用以下触发：

1. 时间摘要：固定周期 + importance 累积阈值
2. 主题摘要：事件聚类达到最小规模
3. insight：压缩、对比、冲突消解后触发

### 8.4 生成规则

L3 只处理以下事件：

1. `cognition_eligible = true`
2. `memory_domain != runtime_telemetry`
3. `retention_class != disposable`

### 8.5 使用原则

1. L3 用于快速回顾与召回，不替代 L1 原始证据。
2. L3 的任何结论都必须可回溯到 `source_event_ids`。
3. 对于永久事件，允许生成摘要，但默认不删除对应 L1 原文。

---

## 9. L4 程序性记忆

### 9.1 目标

L4 用于沉淀“如何做一件事”的经验，表达 Agent 在反复成功/失败后对未来执行路径的调整能力。

它本质上是基于历史交互事件提取出的程序性记忆，包括：

1. 工具/API 使用熟练度
2. 成功/失败模式
3. 异常处理肌肉记忆
4. 熔断状态
5. 最优提示模板/参数模板
6. 特定上下文下的策略偏好

### 9.2 表结构

```sql
CREATE TABLE procedural_skills (
    skill_id TEXT PRIMARY KEY,
    skill_name TEXT NOT NULL,
    skill_category TEXT NOT NULL,       -- tool, api, workflow, strategy
    skill_type TEXT NOT NULL,           -- external_tool, internal_api, composite

    proficiency REAL NOT NULL DEFAULT 0.0,
    total_attempts INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    success_rate REAL NOT NULL DEFAULT 0.0,

    avg_execution_time_ms REAL,
    min_execution_time_ms REAL,
    max_execution_time_ms REAL,
    p95_execution_time_ms REAL,

    circuit_breaker_state TEXT NOT NULL DEFAULT 'closed',
    circuit_breaker_opened_at REAL,
    circuit_breaker_failure_count INTEGER NOT NULL DEFAULT 0,
    circuit_breaker_success_count INTEGER NOT NULL DEFAULT 0,

    optimized_prompt TEXT,
    optimized_params TEXT,              -- JSON
    optimization_score REAL,
    context_affinity TEXT,              -- JSON

    source_event_ids TEXT NOT NULL,     -- JSON
    last_used_at REAL,
    last_success_at REAL,
    last_failure_at REAL,

    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,

    UNIQUE(skill_name, skill_category)
);
```

### 9.3 L4 与 L1/L0 的关系

1. L1 记录每次工具/策略尝试
2. L4 从这些事件中提炼程序性记忆
3. L0 在当前 session 中读取 L4 并决定是否采用某策略

例如：

1. 某工具连续失败，L4 熔断打开，L0 当前轮次避免再调用
2. 某类异常在过去 5 次里已有稳定处理模式，L4 返回推荐模板，L0 当前轮次直接应用

---

## 10. 检索机制与 Prompt 集成

### 10.1 统一检索目标

统一检索不是“把所有层都查一遍”，而是：

1. 根据意图决定查哪几层
2. 根据时间范围决定查哪些分片
3. 根据 source taxonomy 过滤噪声
4. 给 prompt 返回可消费的结构化 payload

### 10.2 查询契约

```python
@dataclass
class RetrievalQuery:
    query: str
    user_id: str | None
    session_id: str | None
    time_range: dict[str, Any]
    query_mode: Literal["detail", "summary", "experience", "graph", "strategy"]
    source_filters: list[str]
    domain_filters: list[str]
    limit: int
```

```python
@dataclass
class RetrievalPayload:
    l0_workbench: list[dict[str, Any]]
    l1_events: list[dict[str, Any]]
    l2_entities: list[dict[str, Any]]
    l2_relationships: list[dict[str, Any]]
    l3_reflections: list[dict[str, Any]]
    l4_procedures: list[dict[str, Any]]
    trace: dict[str, Any]
```

### 10.3 检索路由

#### 10.3.1 detail

优先 L1，必要时补充 L2 关系和 L0 workbench。

#### 10.3.2 summary

优先 L3，必要时回查 L1 原始证据。

#### 10.3.3 experience

优先 L4，补充 L1 成败样本与 L3 经验摘要。

#### 10.3.4 graph

优先 L2，补充 L1 证据。

#### 10.3.5 strategy

优先 L4，必要时补充 L0 当前上下文。

### 10.4 Prompt 组装契约

`PromptContextAssembler` 需要新增对以下 payload 的读取：

```python
retrieved_memory_payload = {
    "l0_workbench": [...],
    "l2_entity_cards": [...],
    "l3_reflection_memory": [...],
    "l4_procedural_memory": [...],
    "preference_memory": {...},
}
```

#### 10.4.1 读取优先级

1. L0：当前轮次立即生效的状态与临时策略
2. L4：如何做
3. L2：当前相关实体是谁、状态如何
4. L3：近期主题回顾
5. L1：仅在需要原始证据时补充

---

## 11. 遗忘、压缩与保留

### 11.1 核心原则

1. 默认不删除用户主动创作内容
2. 默认允许压缩外部活动轨迹
3. 低价值系统遥测可丢弃
4. 压缩前必须先产出可追溯的 L3 insight 或 summary

### 11.2 默认保留策略

#### 11.2.1 永久保留

1. 聊天记录
2. 用户手动输入的日记/时间线/笔记
3. 被用户显式标注为重要的记录

#### 11.2.2 可压缩删除

1. 浏览历史
2. 终端历史
3. Git 活动
4. 低层外部活动记录

#### 11.2.3 可直接删除

1. worker 进度
2. loop 控制事件
3. checkpoint 元事件

### 11.3 压缩流程

```text
1. 筛选 compressible 且过期的 L1 事件
2. 聚合成 L3 summary / insight
3. 回写 source_event_ids
4. 记录压缩审计日志
5. 软删除或物理删除原始事件
```

---

## 12. 运行时集成方案

### 12.1 运行时职责分布

| 组件 | 职责 |
|------|------|
| `MemoryIntegrationModule` | 统一入口，负责标准化、落 L1、投递异步任务 |
| `L0WorkingMemoryStore` | 内存态 session/workbench 管理与 checkpoint |
| `L1EventStore` | 事件主存与分片路由 |
| `L2CognitionStore` | 图谱、断言、快照 |
| `L3SummaryStore` | 摘要与 insight |
| `L4ProceduralMemoryStore` | 程序性记忆 |
| `HybridRetrievalService` | 统一检索 |
| `MemoryMaintenanceDaemon` | housekeeping；不走业务 scheduler |

#### 12.1.1 为什么 maintenance 不走 SchedulerService

根据当前运行时架构，`SchedulerService` 用于业务任务，housekeeping 仍然应由维护守护进程承担。因此本轮记忆维护任务继续归属于维护守护进程，而不是业务调度器。

### 12.2 与当前文件的替换关系

| 当前模块 | 新模块/新角色 | 动作 |
|---------|---------------|------|
| `raw_event_store.py` | `l1_event_store.py` | 替换 |
| `l2_event_relations.py` | `l2_cognition_store.py` | 删除并合并 |
| `l2_user_graph.py` | `l2_cognition_store.py` | 删除并合并 |
| `l3_semantic_embeddings.py` | L1/L3 内嵌向量能力 | 删除独立层角色 |
| `l4_summaries.py` | `l3_summary_store.py` | 重命名并升级 |
| `l5_capabilities.py` | `l4_procedural_memory.py` | 替换并扩展 |
| `integration.py` | `integration.py` | 保留入口，但重写内部流程 |
| `query/*` | `hybrid_retrieval/*` | 重写 |
| `prompt_context_assembler.py` | 同文件 | 保留并扩展读取新 payload |
| `runtime/bootstrap.py` | 同文件 | 改造初始化与 wiring |

#### 12.2.1 本轮暂不替换

1. `self_memory.py`
2. `other_memory.py`
3. `scenario_prompts.py`

---

## 13. 分阶段实施方案

以下阶段按顺序实施，每个阶段必须是独立可验证、可回退的原子任务。

### 13.1 Phase 0: 事件标准与配置落地

目标：

1. 固化 L1 标准事件契约
2. 引入 source taxonomy 与 retention policy
3. 定义全局配置模型

主要变更：

1. 新增 `backend/src/magi/memory/event_contracts.py`
2. 重写或替换 `backend/src/magi/memory/integration.py`
3. 更新 `backend/src/magi/config/models.py`
4. 更新 `backend/src/magi/runtime/bootstrap.py`

验收：

1. 任意 memory event 入库前都能标准化
2. 每条事件都带 `memory_domain`、`retention_class`、`cognition_eligible`

### 13.2 Phase 1: L0 + 新 L1

目标：

1. 建立内存态 L0 workbench 与 checkpoint
2. 完成新 L1 表结构与分片路由

主要变更：

1. 新增 `backend/src/magi/memory/l0_working_memory.py`
2. 新增 `backend/src/magi/memory/l1_event_store.py`
3. 删除/替换 `backend/src/magi/memory/raw_event_store.py`
4. 更新 `backend/src/magi/memory/__init__.py`

验收：

1. 会话中可读写 goal stack / active entities / temporary tactics
2. L1 支持原始事件写入、时间过滤、source 过滤、domain 过滤
3. 重启后可从 checkpoint 恢复 L0

### 13.3 Phase 2: L2 结构化认知

目标：

1. 合并关系图与用户图
2. 引入 ToM assertion 防腐层与 snapshot 物化机制

主要变更：

1. 新增 `backend/src/magi/memory/l2_cognition_store.py`
2. 删除 `backend/src/magi/memory/l2_event_relations.py`
3. 删除 `backend/src/magi/memory/l2_user_graph.py`
4. 新增 `backend/src/magi/memory/l2_extractors.py`

验收：

1. 能从 L1 事件提取三元组
2. 能生成 `tentative` ToM 断言
3. 满足验证条件后可物化到 snapshot

### 13.4 Phase 3: L3 反思记忆

目标：

1. 把当前 summary 升级成真正的反思记忆
2. 支持 temporal / thematic / insight 三类输出

主要变更：

1. 新增 `backend/src/magi/memory/l3_summary_store.py`
2. 删除/替换 `backend/src/magi/memory/l4_summaries.py`
3. 新增 `backend/src/magi/memory/l3_generators.py`

验收：

1. 生成摘要时默认过滤 runtime telemetry
2. L3 结果可回溯到 source events
3. 对永久事件只摘要不删除

### 13.5 Phase 4: L4 程序性记忆

目标：

1. 让 capability 升级为 procedural memory
2. 引入熔断器、上下文亲和度、最优模板

主要变更：

1. 新增 `backend/src/magi/memory/l4_procedural_memory.py`
2. 删除/替换 `backend/src/magi/memory/l5_capabilities.py`

验收：

1. 能记录工具/策略尝试
2. 能根据历史成功率更新技能熟练度
3. 能在连续失败后打开熔断并在检索中返回

### 13.6 Phase 5: 检索与 Prompt 集成

目标：

1. 重建统一检索
2. 让 prompt 真正读到 L0/L2/L3/L4

主要变更：

1. 新增 `backend/src/magi/memory/hybrid_retrieval/`
2. 删除/替换 `backend/src/magi/memory/query/`
3. 修改 `backend/src/magi/tools/memory_query.py`
4. 修改 `backend/src/magi/memory/prompt_context_assembler.py`
5. 修改 `backend/src/magi/agent/task_agents/chat/prompt_service.py`

验收：

1. `detail / summary / experience / graph / strategy` 五种模式可跑通
2. prompt payload 中能读取 L0/L2/L3/L4
3. 检索结果默认不被 runtime telemetry 主导

### 13.7 Phase 6: 维护、API 与清理

目标：

1. 完成 maintenance daemon 集成
2. 更新 memory API
3. 删除旧实现

主要变更：

1. 修改 `backend/src/magi/api/routers/memory.py`
2. 修改维护守护进程相关模块
3. 清理旧表、旧查询与旧测试

验收：

1. 可按 retention policy 执行压缩/删除
2. API 能展示新层统计、ToM 断言、L4 技能
3. 旧模块不再被 bootstrap 引用

---

## 14. 验收与测试清单

每个阶段至少补齐以下测试：

### 14.1 L0 / L1

1. session 创建、checkpoint、恢复
2. 新事件标准化写入
3. 时间分片查询
4. retention policy 标记

### 14.2 L2

1. 三元组提取
2. ToM 低置信度进入 assertion
3. 多事件验证后提升为 stable
4. 反证事件触发降级

### 14.3 L3

1. temporal summary 生成
2. thematic summary 生成
3. insight 压缩
4. 永久事件不删除

### 14.4 L4

1. 成功率累计
2. 熔断开启/恢复
3. 最优模板回收
4. strategy query 返回正确技能

### 14.5 检索

1. detail query 不被 telemetry 噪声压制
2. summary query 优先命中 L3
3. experience query 优先命中 L4
4. graph query 带 L1 证据回链

### 14.6 Prompt

1. 当前会话能读到 L0
2. 关系/画像能读到 L2
3. 回顾记忆能读到 L3
4. 如何做能读到 L4

---

## 15. 配置总览

```python
@dataclass
class MemorySystemConfig:
    enable_l0: bool = True
    enable_l1: bool = True
    enable_l2: bool = True
    enable_l3: bool = True
    enable_l4: bool = True

    enable_t1_importance: bool = True
    enable_l2_llm_extraction: bool = True
    enable_l3_llm_summary: bool = True
    enable_l4_skill_extraction: bool = True

    l0: L0Config = field(default_factory=L0Config)
    l1: L1Config = field(default_factory=L1Config)
    l2: L2Config = field(default_factory=L2Config)
    l3: L3Config = field(default_factory=L3Config)
    l4: L4Config = field(default_factory=L4Config)

    embedding_model: str = "text-embedding-3-small"
    maintenance_interval_seconds: int = 300
```

---

## 16. 本轮实现边界

为了保证可以真正落地，本轮实现边界明确如下：

1. 不做历史数据迁移
2. 不做旧 API 兼容
3. 不与 `SelfMemory` / `OtherMemory` 合并
4. 不引入外部图数据库
5. 不引入外部向量数据库
6. 默认全部基于 SQLite + 内存态缓存实现

---

## 17. 结论

该方案相对于当前实现的核心变化不是“多了几张表”，而是把记忆系统从功能堆叠改造成统一的生命周期系统：

1. L1 负责真实经历
2. L2 负责有证据的认知
3. L3 负责长期压缩
4. L4 负责程序性经验
5. L0 负责当前执行态

同时，通过 source taxonomy、ToM 防腐层、分层检索和按类型保留策略，系统可以在服务长期记忆目标的前提下，避免被运行时噪声主导。
