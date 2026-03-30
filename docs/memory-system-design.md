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
- 当前向量索引以 `event` 为父对象、以 `chunk` 为检索粒度：长文本会先切成多个重叠 chunk 建立向量，再在检索阶段折叠回父事件
- 当前 `L1` / `L3` / `L4` 的 hybrid retrieval 在 `RRF` 之后还会经过统一 reranker 阶段；当前支持共享 heuristic reranker，以及一个可选的 LLM reranker
- `LLM reranker` 由 `agent.memory.reranker` 驱动：`remote` 模式使用显式 provider/model，`local` 模式复用全局 `llm.providers.local` 指向的本地 OpenAI-compatible 服务
- 如果 LLM reranker 的 provider、model 或本地服务不可用，检索链路会自动回退到 heuristic reranker，不会中断主检索

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

当前 `L2` entity catalog 的向量仍然保持单实体单向量，不做 chunking；但 embedding 文本会通过统一 builder 组织 `entity_type`、`canonical_name` 和高价值 alias，以保持与其它层一致的文本构造约定。
`L2` / `L3` / `L4` 的父表现在也会记录统一的 embedding 观测字段，包括 `embedding_status`、`embedding_profile_id` 和 `last_embedded_at`，便于后续重建和诊断。仓库同时提供了 [scripts/rebuild-memory-embeddings.py](/Users/asuka/code/magi/scripts/rebuild-memory-embeddings.py) 作为离线重建入口，用于在 embedding profile、text builder 或 chunking 规则变更后批量重建各层向量。
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

### L2 写入侧语义约定

当前实现已经具备两类与写入侧语义有关的能力：

- source integration 可以通过 `MemoryEvent.metadata_json` 传入 `structured_entity_hints`
- sensor integration 可以传入 rule-based `relation_candidates`

后续的统一 source-of-truth contract 以“source-owned semantic enrichment”为目标，而不是把所有 source-specific 结构解析堆进 `L2Pipeline` 本身。

核心原则：

- 谁最了解原始数据，谁负责产出高置信结构事实
- `L2` 负责统一整合、冲突处理、持久化和 residual LLM extraction
- 插件和传感器不应绕过 `L2` 直接写 `knowledge_graph`
- 自然语言开放理解和 source-specific 结构解析必须分层

推荐的写入链路为：

```text
Plugin / Sensor / Host integration
  -> source-owned semantic enrichment
  -> MemoryEvent.metadata_json
  -> Ingestion gateway normalization + admission
  -> L2 pipeline merge / conflict handling / persistence
```

#### 语义增强的 ownership

写入前的结构化增强应按 ownership 拆分，而不是由一个“大统一 parser”承担：

- source-owned enrichers
  适用于浏览历史、日历、地图、照片库、git 活动等明确 source；由最懂原始 payload 的 integration 产出结构化 hints
- modality-owned enrichers
  适用于图片、PDF、链接等跨 source 载体；负责提取 EXIF、OCR、标题、host、canonical URL 等稳定结构
- residual LLM extraction
  用于自由聊天文本或低结构 source；只在 deterministic / structured hints 无法覆盖时补足剩余语义

`L2` 的角色因此不是“重新理解原始 source 私有格式”，而是消费统一 hint contract 并生成 durable cognition。

#### 写入时区分的事实类型

写入链路必须把“对象结构”和“用户证据”分开表示。统一的 `FactHint` / graph candidate 至少区分以下 `fact_kind`：

- `public_topology`
  对象本身的稳定结构，例如账号归属平台、地点位于城市中
- `interaction_evidence`
  用户和对象发生过的交互，例如访问、观看、关注、使用
- `stable_preference`
  用户显式表达或高置信配置导出的偏好

`喜欢` 不应在写入时被简化成一个单一 graph predicate。对多数被动 source 来说，更合理的 durable 写法是先写 interaction evidence，再由查询侧做 affinity 聚合。

#### 插件与 ingestion 的职责分工

插件层对外暴露的 contract 应以“实体 hints + 事实 hints”为核心，而不是直接暴露 `memory.l2` 内部模型。

- source integration 负责产出：
  - entity hints
  - fact hints
  - 可选 tags / batch hints
- ingestion gateway 负责：
  - schema 校验
  - canonical ref / local ref 规范化
  - 把 hints 写入 `MemoryEvent.metadata_json`
  - 根据 admission policy 生成 rule-backed graph candidates
- `L2Pipeline` 负责：
  - 把 source-owned hints 作为结构锚点
  - 与 LLM 产出的 residual candidates 合并
  - 冲突处理、去重、持久化和 snapshot refresh

#### 写入准入规则

是否允许某条 source-owned fact 进入 durable graph，不由插件直接决定，而由 runtime 统一裁决。推荐按以下维度评估：

- `fact_kind`
- `predicate`
- `origin_mode`
  例如 `source_explicit`、`source_structured`、`heuristic`、`llm_inferred`

默认规则：

- `public_topology`
  仅允许来自 `source_explicit` 或高置信 `source_structured` 的事实直接形成 rule candidate
- `interaction_evidence`
  `VISITED`、`VIEWED`、`USES` 等真实事件通常可直接形成 rule candidate
- `stable_preference`
  默认不允许由被动 source 直接落图；只有显式自述、配置、收藏/订阅清单等强语义 source 才能直接写入

`FOLLOWS` 应比普通浏览证据更严格：单次内容页访问不足以写入 `FOLLOWS`，账号页、主页、关注列表或显式订阅清单才属于可接受的强信号。

#### LLM-facing 与 system-facing ontology

写入侧 ontology 需要区分“LLM 应该自由生成的类型”与“系统内部图需要表达但不应让 LLM 随意发明的类型”。

推荐约定：

- 继续作为 LLM-facing 的 coarse types：
  - `person`
  - `group`
  - `organization`
  - `place`
  - `software`
  - `media`
  - `topic`
- 新增但仅供 system-facing / structured hints 使用的 internal type：
  - `presence`

几个重要约束：

- 平台继续使用 `software`，不要新增 `platform` 类型
- creator identity 继续落在 `person` / `group` / `organization`
- venue / 门店 / 城市继续使用 `place`
- category 暂不作为通用 graph entity type 暴露给 LLM；应先作为 query / topology facet 处理
- extraction profile 需要区分 LLM-facing allowlist 与 structured-hint allowlist；internal type / predicate 可进入 structured-hint allowlist，但默认不进入 LLM-facing allowlist

#### 推荐的 internal topology predicates

为了表达平台归属和地点约束，写入侧推荐新增以下 internal-only predicates：

- `PRESENCE_OF`
- `ON_PLATFORM`
- `LOCATED_IN`

这些 predicate 的目标是承载结构约束，不直接替代现有行为或偏好边。行为与偏好仍继续使用：

- `FOLLOWS`
- `VISITED`
- `VIEWED`
- `USES`
- `LIKES`
- `DISLIKES`
- `INTERESTED_IN`

在这个约定下：

- `FOLLOWS` 优先指向 `presence`
- `presence -> ON_PLATFORM -> software`
- `presence -> PRESENCE_OF -> person/group/organization`
- `place -> LOCATED_IN -> place`

`HAS_CATEGORY` 暂不进入主图；分类值应先在 facet / structured hint 层承载，避免过早把 taxonomy node 体系引入主图。

#### 图存储的持久化要求

当前 `knowledge_graph` 已能保存 predicate、证据、置信度和冲突状态，但如果写入链路要稳定区分 topology、interaction evidence 与 stable preference，持久层必须保留 `fact_kind`。

因此后续实现中：

- `knowledge_graph` 应补充 `fact_kind`
- rule-backed graph candidates 与 LLM candidates 在入库前必须统一到同一套 schema
- `fact_kind` 不能只存在于 prompt 或临时 candidate 中，否则查询和冲突处理阶段会丢失语义边界

### L2 查询侧语义约定

`L2` 查询不应继续围绕粗粒度 `predicate_family -> predicates` 做规划。对自然语言回忆问题来说，真正稳定的结构不是“查哪条边”，而是：

- 回答对象是什么
- 约束作用在回答对象本身还是交互上下文
- 需要列出对象、判断单对象，还是回答 yes/no
- “喜欢”这类语义应由哪些证据聚合而成

因此 `L2` 检索的核心 contract 应升级为语义查询帧，而不是只传入 `predicate_family`。

#### 查询帧

推荐的 `L2` 查询帧至少应表达以下槽位：

- `query_family`
  例如 `affinity`、`relationship`、`profile`、`activity`、`lookup`
- `subject_scope`
  `self`、`explicit`、`none`
- `answer_kind`
  例如 `creator`、`place`、`topic`、`person`、`software`
- `answer_unit`
  例如 `identity`、`presence`、`place`、`mixed`
- `answer_shape`
  例如 `list`、`single`、`boolean`
- `polarity`
  `positive`、`negative`、`neutral`、`any`
- `entity_mentions`
  供后续解析和候选绑定使用的显式 mention
- `constraints`
  受控的约束列表，而不是任意自由图查询

其中：

- `喜欢`、`讨厌`、`偏好` 不应直接绑定到某个单一 predicate，而应落在 `query_family=affinity`
- `answer_kind` 决定候选对象的类型
- `answer_shape` 决定结果投影方式，不能推迟到最终回答阶段再猜

#### 约束与作用域

查询约束必须带作用域。当前推荐先支持两类作用域：

- `target`
  修饰回答对象本身，例如“B 站上的 UP 主”“杭州的咖啡馆”
- `interaction`
  修饰交互发生时的上下文，例如“我在杭州的时候常去哪些店”“我用 B 站的时候常看谁”

受控 facet 建议先收敛到：

- `platform`
- `located_in`
- `category`

解析后约束分两类：

- entity-backed constraint
  可解析成图实体，例如 `B站 -> software:bilibili`、`杭州 -> place:hangzhou`
- facet-backed constraint
  先不进入主图、由 facet registry / structured hint 承载，例如 `咖啡馆 -> coffee_shop`

当前实现中，这类 facet 通过 `entity_facets` sidecar 持久化，写入来源优先是 source-owned `structured_graph_hints.attributes`，而不是主图中的 taxonomy node。

默认规则：

- 直接修饰回答对象的限定词优先解释为 `target`
- 表示“在某时/某地/某平台使用过程中”的状语优先解释为 `interaction`
- 模糊时优先 `target`

#### 查询执行流水线

推荐把 `L2` 查询执行固定为以下四步：

```text
Natural language
  -> SemanticFrame
  -> ResolvedFrame
  -> CandidateSet + EvidenceSet
  -> RankedAnswer
```

每一层职责如下：

- `SemanticFrame`
  从自然语言中提取稳定语义槽位，不直接决定底层 graph predicate
- `ResolvedFrame`
  把平台、地点、类别、显式对象等约束解析成可执行约束
- `CandidateSet`
  先根据 topology / facet 约束找“有资格成为答案”的对象集合
- `EvidenceSet`
  收集用户和候选之间的 direct / lifted evidence
- `RankedAnswer`
  对候选按查询语义聚合和排序，生成列表、单对象结果或布尔判断

#### 候选优先，再做证据聚合

`affinity` 查询默认采用“先找候选，再算喜欢程度”的模式，而不是直接从一条偏好边反推对象。

这意味着：

- 平台、地点、类别等约束先用于筛候选对象
- 用户与候选之间的边用于计算 affinity
- 回答对象的资格和强度由两层不同的机制决定

例如：

- “我 B 站喜欢哪些 UP 主”
  先找 `presence -> ON_PLATFORM -> software:bilibili` 的候选，再看 `user -> candidate` 的 evidence
- “我在杭州喜欢去哪些咖啡馆”
  先找 `place -> LOCATED_IN -> place:hangzhou` 且 `category=coffee_shop` 的候选，再看 `VISITED` / `LIKES`

#### Affinity 是读时聚合，不是单一 predicate

`affinity` 不应被实现成对 `LIKES` 的单条边查询。对不同回答对象，强证据可以不同：

- creator
  `FOLLOWS`、显式 `LIKES`、`INTERESTED_IN`、重复消费内容证据
- place
  显式 `LIKES`、重复 `VISITED`
- software
  `USES`、显式 `LIKES` / `DISLIKES`
- topic
  `INTERESTED_IN`、显式 `LIKES`、重复消费相关内容

因此 `affinity` 应是读时 evidence aggregation。写入侧负责保留结构事实和交互证据，查询侧负责按 `answer_kind` 聚合为“喜欢/讨厌/偏好”。

推荐的分数模型：

- 正向证据和负向证据分别聚合
- direct evidence 权重大于 lifted evidence
- 多条弱证据应采用饱和聚合，而不是简单线性叠加
- yes/no 判断应基于正负证据分别建模，而不是只看单一总分

#### 策略注册表，而不是 query if/else

查询执行模板不应按具体问法硬编码，而应围绕稳定的语义组合注册策略。推荐按：

- `query_family`
- `answer_kind`

选择执行策略。

例如：

- `("affinity", "creator")`
- `("affinity", "place")`
- `("affinity", "software")`
- `("affinity", "topic")`

每个策略应由可组合原语构成，而不是一整段 query-specific 分支逻辑：

- candidate provider
- constraint handlers
- evidence collectors
- grouper
- scorer
- projector

扩展规则：

- 新说法只改查询帧生成规则
- 新约束只加 facet / constraint resolver
- 新证据只加 evidence collector
- 只有出现新的回答对象类型时，才新增策略注册项

#### `presence` 在查询侧的角色

查询侧不应把 creator identity 和 platform presence 混为一谈。

推荐约定：

- creator affinity 的候选优先基于 `presence`
- `presence -> ON_PLATFORM -> software`
- `presence -> PRESENCE_OF -> person/group/organization`
- 默认回答按 identity 聚合输出
- 只有当用户明确问账号、频道、主页时，才按 `presence` 输出

这样平台约束、账号级行为证据和最终面向用户的 creator 回答可以同时成立，而不需要误用 `WORKS_AT` 之类不精确 predicate。

#### L1 与 L2 的协同

不是所有带有“喜欢”字样的问题都应完全交给 `L2`。推荐的层协同规则：

- `L2` 负责稳定结构约束和长期 affinity
- `L1` 负责强时间窗口、单次经历、顺序、次数等事件性证据

因此：

- “我喜欢哪些 UP 主” 应优先走 `L2`
- “我最近三天都看了谁” 应优先走 `L1`
- “我最近在杭州喜欢去哪些咖啡馆” 这类同时包含稳定对象约束和时间窗口的问题，应允许 `L2` 提供候选对象、`L1` 提供时间切片证据，再在 affinity 层聚合

#### 查询侧的可观测性要求

为了避免再次退化成“只有一个模糊 predicate family”的黑盒查询，执行 trace 至少应包含：

- 生成的 `SemanticFrame`
- 解析后的 `ResolvedFrame`
- 选中的 strategy key
- 生效的 candidate provider / evidence collectors
- 命中的 constraints
- 对最终结果贡献最大的证据项

调试时必须能回答：

- 这次回答对象为什么是这类实体
- 哪个约束起效了，哪个没有起效
- 为什么这次结果是 `FOLLOWS` 驱动，而不是 `LIKES` 驱动
- 为什么最终走了 `L2`、`L1` 或两者协同

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

当前 `L3` 向量索引也采用 `summary` 为父对象、`chunk` 为检索粒度的方式：较长 summary 会先切成多个重叠 chunk 建立向量，再在语义检索阶段折叠回父 summary。

### L4 程序性记忆

`L4` 用来沉淀“以后怎么做更好”的执行经验。

它回答的问题是：

- 这里通常什么做法更有效
- 哪些流程经常失败
- 下次优先走哪条 workflow
- 哪些工具或策略应该回避

`L4` 不是在复述历史事实，而是在沉淀未来执行准则。

当前 `L4` 向量索引采用 `skill` 为父对象、`chunk` 为检索粒度的方式：较长 procedural prompt 会先切成多个重叠 chunk 建立向量，再在语义检索阶段折叠回父 skill。

`L1` / `L2` / `L3` / `L4` 的向量写入链路现在共用一个共享 embedding pipeline；各层只定义自己的 text builder、chunk 策略、父表状态回写和检索折叠逻辑。

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
