# 记忆系统架构设计

## 目的

本文档是 Magi 记忆系统的长期 source-of-truth，用来回答两类问题：

- 对产品、运营和使用者来说：Magi 到底记住什么，不记什么，不同类型的数据分别放在哪里
- 对开发者来说：记忆系统的分层、写入、检索、身份、幂等和下游认知到底遵循什么契约

阅读本文件时，建议同时参考：

- [Project Overview](./project-overview.md)
- [Layered Agent Architecture](./layered-agent-architecture.md)
- [Task-Agent Runtime Architecture](./task-agent-runtime-architecture.md)
- [Unified Plugin Extension Architecture](./plugin-extension-architecture.md)

如果本文档与上述根文档发生冲突，应一起修订。本文档负责细化 memory 子系统，而不是重新定义项目级边界。

---

## 记忆系统解决什么问题

Magi 的记忆系统用于把本地对话、外部活动和部分运行结果，整理成可检索、可推理、可压缩的长期记忆，同时避免把聊天真相、运行时 trace、插件中间态混成一层。

它负责：

- 保存当前会话的短期工作上下文
- 把部分事实投影成持久化事件记忆
- 从保留下来的事件中提取结构化认知
- 把长历史压缩成可回顾的摘要与洞察
- 沉淀可复用的执行经验

它不负责：

- 作为完整聊天记录的 source of truth
- 作为 runtime span、tool trace、执行观测数据的 source of truth
- 永久保存每一个原始 producer payload
- 为旧架构保留兼容路径

Magi 的记忆模型按信息生命周期分层，而不是按功能插件分层：

- `L0`：工作记忆
- `L1`：标准化事件事实
- `L2`：结构化认知
- `L3`：反思与摘要
- `L4`：程序性记忆

---

## 心智模型

可以把记忆系统理解成一条稳定的数据演化链：

```text
源信号
  -> 标准化事件契约
  -> 路由与保留策略
  -> L0 和/或 L1
  -> 可选的 L2 认知
  -> 可选的 L3 反思
  -> 可选的 L4 经验沉淀
```

几个典型例子：

- 一条用户聊天消息首先是真实存在于 `chat.db` 里的聊天事实，随后其中一部分内容可能被投影成 `L1` 记忆事实
- 一段 Chrome 历史浏览会先聚组成一个 `L1` 事件，之后可能参与 `L2` 的关系抽取和 `L3` 的时间摘要
- 一次 worker heartbeat 属于运行时遥测，不应该直接进入长期用户记忆
- 一次任务完成结果可能值得保留到记忆层，但详细执行 trace 仍应留在 runtime trace store

记忆系统因此处在“原始数据源”和“上层推理”之间。它不是原始数据源本身。

---

## 运行时边界与数据存储

Magi 明确把聊天真相、运行时观测和持久记忆拆成不同存储。

### 聊天真相

- `~/.magi/data/chat/chat.db`

负责：

- `chat_sessions`
- `chat_turns`
- `chat_messages`

当你需要完整聊天记录、turn 呈现状态、chat 域读模型时，应读这里。

### 运行时观测

- `~/.magi/runtime/runtime_trace.db`

负责：

- turn summaries
- tool calls
- LLM metrics
- spans
- live notifications
- append-only 的 plugin ingress events

当你需要执行回放、排障、trace、原始插件接入事件时，应读这里。

### 持久记忆

- `~/.magi/data/memory/l1_events.db`
- `~/.magi/data/memory/memory.db`

负责：

- `L1` 事实事件主存放在 `l1_events.db`
- `L0`、`L2`、`L3`、`L4` 放在 `memory.db`

当你需要历史回忆、结构化认知、摘要、长期洞察、程序性经验时，应读这里。

### 可重建缓存

- `~/.magi/cache/plugins/<plugin_id>/`

负责插件自己的可重建中间态，例如：

- 传感器进行中的聚合状态
- flush checkpoint
- 插件本地计算缓存

重要规则：cache 不是 memory truth。

---

## 分层总览

### L0 工作记忆

`L0` 是当前 session / task 的短期工作上下文。

它主要承载：

- 当前会话状态
- 当前目标栈
- 当前活跃实体
- 临时策略与执行态上下文

关键特点：

- 以当前执行为中心，不以长期回忆为中心
- 以内存为主，并带 checkpoint 用于恢复
- 会高频变动
- 可以在重启后部分从 durable state 恢复

`L0` 只应保存“当前轮次真的需要”的东西，而不是系统历史上曾经见过的一切。

典型例子：

- 当前 session 的活跃目标
- 当前对话正在围绕哪些实体展开
- 某一轮临时性的战术决策

### L1 标准化事件记忆

`L1` 是 durable fact layer，也是整个记忆系统的事实基座。

它保存那些已经足够稳定、值得参与后续流程的标准化事件，用于：

- recall
- search
- cognition
- reflection
- 记忆投影链路的审计与调试

如果一条事实未来会影响系统的理解、回顾或推理，它通常应该先进入 `L1`。

关键特点：

- 面向持久化的事实事件
- 统一的 source-normalized 契约
- 显式的 domain / retention / cognition 策略
- 支持向量检索和关键词检索
- 保留 source-side identity 和 business idempotency

典型例子：

- 用户主动写下的内容
- 聊天投影后的记忆事实
- Chrome history burst
- 小时级 app usage summary

反例：

- 完整聊天 transcript 真相
- heartbeat 噪声
- 详细逐步执行 trace

### L2 结构化认知

`L2` 用来保存从 `L1` 事件中提取出来的结构化理解。

它承载：

- entity mentions
- canonical entities
- knowledge graph edges
- tentative 或 validated 的 trait assertions
- 当前结构化理解的 snapshots

`L2` 是“有证据的解释层”，不是原始真相层。

关键特点：

- 由 `L1` 派生，而不是独立原始输入
- 带证据引用
- 带置信度
- 支持冲突处理和后续修正
- 默认通过 durable projection job 从 `L1` 异步派生，而不是依赖纯内存队列

`L2` 的默认执行模型是：

1. `L1` 事实先成功写入 durable store
2. 如果事件 `cognition_eligible=true`，会在 `memory.db` 中写入 `l2_projection_jobs`
3. `runtime_worker` 中的 `L2Pipeline` 只 claim 已经 ready 的 `pending` job，并把它们标记为 `queued`
4. claim 到的事件在进程内按 batch owner / session / user 聚成执行批次；worker 真正开始执行前再把对应 job 标记为 `running`
5. 抽取成功后把 job 标记为 `completed`，失败则标记为 `failed` 或重新回到 `pending`

其中：

- `batch owner` 可以由插件通过 `l2_batch_policy()` 提供，用来把同源但更语义一致的事件放进同一个 durable owner 桶
- 插件也可以通过同一个 policy 提供 advisory batching 信息，例如 `max_events`、`min_ready_events`、`max_estimated_tokens` 和 `max_wait_seconds`
- 对高吞吐 source，插件还可以额外提供 `catch_up_owner`，让 `L2` 在大 backlog 重放时把低频 owner 合并进更粗粒度的 catch-up shard
- durable owner 桶通常在“达到期望批大小”或“等待时间超过阈值”时才变成 ready；未 ready 的桶应继续留在 `pending`

这意味着：

- `L2` 的 durable progress 由 projection job state 负责
- 微批只是执行优化，不是进度真相
- `queued` 和 `running` 必须区分：排队中的 batch 不能因为短运行超时被误判成 stale
- durable claim 需要受 runtime backpressure 约束，避免在 extract queue 尚未消化时继续把大量 job 从 `pending` 推成 `claimed`
- 对高吞吐 source，等待积累通常能降低 LLM 成本并提升同域事件的一致性理解
- 对同一个 source，`L2` 可以根据 backlog 在 `catch_up` 和 `steady_state` 之间切换：
  - `catch_up` 更关注吞吐，会优先等待完整批次，并允许使用插件声明的 `catch_up_owner`
  - `steady_state` 更关注时延，会接受较小的 `min_ready_events` 阈值
- `runtime_worker` 重启后，未完成的 `L2` 投影可以从 job state 恢复
- 插件自己的 sync cursor 只负责“同步到 `L1`”，不负责 `L2` 进度
- `runtime_worker` 会在统一调度器里注册 `memory_l2_maintenance` 周期任务：按 `agent.memory.l2` 配置（`maintenance_enabled`、`maintenance_interval_seconds`、`maintenance_min_mentions`）对 `entity_catalog` / `knowledge_graph` 做离线式整理（幽灵 object/subject 引用、同名可合并类型归并、低提及且无图引用的孤儿实体清理）。若配置中 `L2` 总开关关闭或统一内存未初始化 L2，任务执行时会直接跳过

少数没有 `L1` durable 锚点的 runtime-only 事件，可以走进程内即时分发路径，但它们不应被视为 `L2` durable projection 的常规输入。

### L3 反思与摘要

`L3` 用来保存按时间窗或主题压缩后的反思记忆。

它存在的意义是降低以下场景的成本：

- 历史回顾
- 周期总结
- 模式识别
- 反思类 prompt 组装

典型输出包括：

- temporal summaries
- topic summaries
- state-change summaries
- trend-shift summaries
- task reflections

`L3` 应该比长串 `L1` 原始事件更易读、更容易检索，但必须始终能回溯到支持它的证据事件。

### L4 程序性记忆

`L4` 用来沉淀“以后怎么做更好”的执行经验。

它回答的问题是：

- 这里通常什么做法更有效
- 哪些流程经常失败
- 下次优先走哪条 workflow
- 哪些工具或策略应该回避

`L4` 不是在复述历史事实，而是在沉淀未来执行准则。

典型例子：

- 常用 workflow 模板
- 不稳定工具的 circuit-breaker 状态
- 某类任务的成功策略模板
- 不同上下文下的执行偏好

---

## 事件契约与路由

所有进入 durable memory 的数据，都会被标准化成 [backend/src/magi/memory/event_contracts.py](/Users/asuka/code/magi/backend/src/magi/memory/event_contracts.py) 里的 `MemoryEvent`。

一个最小可用的 durable memory event 至少包含：

- `event_id`
- `event_type`
- `source`
- `timestamp`
- `content`
- `memory_domain`
- `ingest_target`
- `cognition_eligible`
- `retention_class`
- 可选的 `source_item_id`
- 可选的 `idempotency_key`
- 可选的 `metadata_json`

### memory_domain

`memory_domain` 用来表达“这条事件在语义上属于哪一类材料”。

当前 canonical domain 为：

- `user_authored`
- `interaction`
- `external_activity`
- `runtime_telemetry`
- `system_control`

这是 Magi 用来隔离用户经验、外部活动和运行时噪声的基础字段。

### ingest_target

`ingest_target` 用来表达“这条事件首先应该落到哪里”。

当前 canonical target 为：

- `l0_only`
- `l1_only`
- `l0_and_l1`

这样可以把当前执行态信号和长期记忆事实拆开处理。

### cognition_eligible

`cognition_eligible` 是当前用于控制事件能否进入高层认知链路的粗粒度开关。

当前它仍然是布尔值：

- `true`：允许参与后续认知和摘要流程
- `false`：可以进入 `L1`，但默认不参与认知

未来如果引入更细的路由模型，也必须保持这个核心意图：durable storage 和 higher-level reasoning 不是同一件事。

### retention_class

`retention_class` 用来表达事件的生命周期策略：

- `permanent`
- `compressible`
- `disposable`

保留策略必须是显式契约，而不是隐式后处理。

---

## 事件身份规则

`L1` 现在明确区分内部主键、外部稳定引用、源侧 identity 和业务幂等键。

这些规则是强约束。

1. `id`
   SQLite 内部主键，只用于内部 join、排序和本地关系效率。

2. `event_id`
   稳定外部事件标识，用于：
   - timeline 引用
   - `L2` / `L3` 证据回溯
   - API 返回
   - 日志和调试

3. `source_item_id`
   源侧 item identity。它表示 producer 自己的业务项标识。

4. `idempotency_key`
   业务幂等键。它回答的是“这是不是同一条业务事件”，而不是“这是不是同一行数据库记录”。

### `L1` 的唯一性规则

当 `idempotency_key` 存在时，`L1` 必须按以下约束去重：

```sql
UNIQUE(source, event_type, idempotency_key)
```

这意味着：

- `event_id` 不是业务去重键
- `source_item_id` 不默认等于业务去重键
- 内部 `id` 绝不能被复用成 `event_id`

### 一个具体例子

一条 Chrome history burst 可能长这样：

- `id = 128431`
- `event_id = "evt_01JQ..."`
- `source = "chrome_history"`
- `event_type = "SENSOR_EVENT"`
- `source_item_id = "181979-181982"`
- `idempotency_key = "default:181979-181982"`

系统会：

- 用 `event_id` 作为跨层稳定引用
- 用 `id` 做内部 join
- 用 `source_item_id` 展示或回显源侧 identity
- 用 `(source, event_type, idempotency_key)` 判断业务幂等

---

## `L1` 事实事件存储

`L1` 的 canonical store 位于 [backend/src/magi/memory/l1/event_store.py](/Users/asuka/code/magi/backend/src/magi/memory/l1/event_store.py)。

当前 `fact_events` 的核心结构是：

```sql
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
    media_path TEXT,
    metadata_json TEXT,
    deleted_at REAL,

    UNIQUE(source, event_type, idempotency_key)
);
```

关键说明：

- `event_id` 仍然是对外稳定引用键
- `id` 是内部关系主键
- `metadata_json` 用于附着结构化事件 payload
- durable events 通过 `deleted_at` 支持软删除

---

## 数据如何进入记忆系统

虽然 producer 很多，但最后都会收敛到同一套 memory contract。

### 聊天投影

聊天真相先写入 `chat.db`。

其中一部分内容随后会被投影成 `L1` 的 canonical facts。

这个投影是有意做成 lossy 的：

- 它保留记忆所需的信息
- 它不试图复制整份 transcript truth

### sensors 与 plugins

sensor 运行在 awareness 层，产出 `SensorOutput`。

`SensorIngestionGateway` 负责把这些输出投影进 memory。

这是以下来源进入记忆层的主路径：

- browser history
- app usage
- terminal / Git activity
- 其他 external activity 插件

### runtime 生成事件

部分 runtime 事件在值得审计或值得未来学习时，也可能被标准化进 memory。

但运行时观测和 durable memory 是两个系统。默认原则是：高频执行遥测不进入长期记忆。

---

## 检索与 Prompt 集成

memory 层负责 recall、检索、排序和跨层证据组织；context 层负责 prompt shaping 和最终注入策略。

这是一个刻意的边界：

- memory 决定“查到了什么”
- context 决定“哪些结果真的应该进入 prompt”

因为并不是所有可检索到的记忆，都适合被隐式注入到普通对话里。

### 典型检索意图

当前检索大体支持以下意图：

- detail recall
- summary-oriented recall
- experience / workflow reuse
- graph-oriented lookup
- strategy-oriented lookup

不同层的贡献不同：

- `L1` 负责主要事实回忆
- `L2` 负责结构化证据
- `L3` 负责压缩后的总结上下文
- `L4` 负责执行经验和可复用策略

### 当前 prompt 策略

当前 implicit injection 仍然偏保守：

- `L0` 是默认隐式上下文
- 更高层的记忆需要有明确理由才注入
- 显式历史回忆和隐式 prompt 注入是两类不同决策

这样可以避免把陈旧、弱相关或噪声记忆过度塞进普通对话。

---

## 保留、压缩与删除

保留策略按事件类型和用途定义，而不是全局一刀切。

### 一般规则

- 用户主动创作的 durable memory 默认保留更强
- external activity 往往更适合 `compressible`
- runtime telemetry 默认被严格限制或直接排除
- 摘要和程序性记忆必须保留回溯证据的能力

### 压缩的含义

压缩并不等于“随便删”。

压缩意味着：

- 保留历史的重要形状
- 允许低价值原始细节被缩减
- 仍然保留足够的引用来解释某条 summary 或 procedure 为什么存在

压缩不能以丢失唯一的重要 durable representation 为代价。

---

## 当前运行规则

下面这些规则是日常改代码时必须遵守的：

1. 聊天 transcript truth 在 `chat.db`，不在 `L1`
2. runtime trace truth 在 `runtime_trace.db`，不在 `L1`
3. `L1` 是 canonical fact projection layer
4. `L2`、`L3`、`L4` 都是 derived layers，必须能从下层解释来源
5. cache 是可重建层，不能变成隐式真相层
6. `event_id` 是稳定外部引用，不是 source identity 的替身，也不是 business dedupe key
7. 当 `idempotency_key` 存在时，业务唯一性由 `(source, event_type, idempotency_key)` 定义
8. 读路径如果需要 producer-side 业务标识，应优先取 `source_item_id`，其次 `idempotency_key`，而不是 `event_id`

---

## 开发者入口

当前主要实现入口如下：

- [backend/src/magi/memory/__init__.py](/Users/asuka/code/magi/backend/src/magi/memory/__init__.py)
  统一 memory facade 与 lifecycle coordination

- [backend/src/magi/memory/event_contracts.py](/Users/asuka/code/magi/backend/src/magi/memory/event_contracts.py)
  标准事件契约和标准化逻辑

- [backend/src/magi/memory/l0/working_memory.py](/Users/asuka/code/magi/backend/src/magi/memory/l0/working_memory.py)
  `L0` 工作记忆

- [backend/src/magi/memory/l1/event_store.py](/Users/asuka/code/magi/backend/src/magi/memory/l1/event_store.py)
  `L1` 事实事件存储、检索和向量索引

- [backend/src/magi/memory/l2/pipeline.py](/Users/asuka/code/magi/backend/src/magi/memory/l2/pipeline.py)
  `L2` 抽取与认知流水线，以及 durable projection job claim / batching

- [backend/src/magi/memory/l2/store.py](/Users/asuka/code/magi/backend/src/magi/memory/l2/store.py)
  `L2` durable cognition store，包括 `l2_projection_jobs`

- [backend/src/magi/memory/l3/summary_store.py](/Users/asuka/code/magi/backend/src/magi/memory/l3/summary_store.py)
  `L3` 摘要和证据回链

- [backend/src/magi/memory/l4/procedural_memory.py](/Users/asuka/code/magi/backend/src/magi/memory/l4/procedural_memory.py)
  `L4` 程序性记忆

- [backend/src/magi/memory/hybrid_retrieval/service.py](/Users/asuka/code/magi/backend/src/magi/memory/hybrid_retrieval/service.py)
  跨层统一检索入口

- [backend/src/magi/memory/integration.py](/Users/asuka/code/magi/backend/src/magi/memory/integration.py)
  runtime-facing memory integration boundary

- [backend/src/magi/awareness/ingestion_gateway.py](/Users/asuka/code/magi/backend/src/magi/awareness/ingestion_gateway.py)
  sensor / plugin -> memory 的投影入口

---

## 给插件和功能开发者的检查单

当你要接一个新的记忆来源时，先回答这几个问题：

1. 它是 transcript truth、runtime trace，还是 durable memory projection
2. 它应该先落 `L0`、`L1`，还是两者都要
3. 正确的 `memory_domain` 是什么
4. 它是否应该参与下游 cognition
5. 正确的 `retention_class` 是什么
6. 它的 source-side item identity 是什么
7. 它的 business idempotency key 是什么

如果这些问题回答不清楚，这个功能通常还不适合直接写进 memory。

### 常见错误

- 把原始 runtime telemetry 直接写进 `L1`
- 把 `event_id` 当成业务来源 ID 使用
- 默认把 `source_item_id` 当成 dedupe key
- 把可变的运行时中间态写进 durable memory store
- 在 `L1` 里复制完整 chat transcript truth

---

## 本文档刻意不做什么

本文档不负责描述：

- 分阶段实施计划
- 临时迁移 choreography
- 旧 schema 的兼容层
- `L4` 之后的推测性新层级

这些内容应该写在任务计划、设计草案或变更说明里，而不是长期 source-of-truth 文档里。

---

## 总结

Magi 的记忆系统建立在一个很简单但必须坚持的分离上：

- chat truth 不是 memory
- runtime trace 不是 memory
- durable memory 从标准化后的 `L1` facts 开始

在这个前提下：

- `L0` 支撑当前执行
- `L1` 保存 canonical durable facts
- `L2` 结构化理解
- `L3` 压缩和反思
- `L4` 沉淀可复用执行经验

同时，身份模型必须始终明确：

- `id`：内部 join 主键
- `event_id`：稳定外部引用
- `source_item_id`：源侧 identity
- `idempotency_key`：业务幂等键
