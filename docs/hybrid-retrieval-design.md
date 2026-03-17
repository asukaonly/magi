# 混合检索方案设计文档

> 版本: 0.2（所有开放问题已确认）
> 日期: 2026-03-17
> 状态: 已确认，待实施
> 依赖: `docs/memory-system-design.md` 第 10 节

## 0. 文档边界

1. 本文档仅定义 `HybridRetrievalService` 及其下游组件的检索方案。
2. 写入链路（Ingestion）由 `memory-system-design.md` 和 `memory-system-execution-plan.md` 定义，本文不涉及。
3. Prompt 组装由 `PromptContextAssembler` 负责，本文仅定义其输入契约。
4. 若本文档与 `memory-system-design.md` 冲突，以后者为准。

---

## 1. 现状与问题

### 1.1 当前实现

| 组件 | 位置 | 现状 |
|------|------|------|
| `HybridRetrievalService` | `memory/hybrid_retrieval/service.py` | 按 `query_mode` 硬路由到各层，无意图分析 |
| `MemoryQueryTool` | `tools/builtin/memory_query_tool.py` | 透传查询，不做拆分 |
| `ContextDecider` | `tools/context_decider.py` | 关键词匹配触发记忆需求，规则推断时间/类型 |
| `ContextRetrievalService` | `context/retrieval.py` | 用 task_category 做 3 次并行 mode 查询，拼 prompt payload |
| L1 search | `memory/l1_event_store.py` | 向量优先 → keyword LIKE 兜底 |
| L3 search | `memory/l3_summary_store.py` | 向量优先 → keyword LIKE 兜底 |
| L4 search | `memory/l4_procedural_memory.py` | 向量优先 → keyword LIKE 兜底 |

### 1.2 核心问题

1. **无查询拆分**：用户复合查询（"昨天浏览的 React 文章，以及我和张三聊了什么"）被当作单条查询发到各层。
2. **无意图分析**：`query_mode` 由调用方硬指定或默认 `detail`，系统不具备根据查询内容自适应路由的能力。
3. **time_range 未消费**：`RetrievalQuery.time_range` 存在于契约中但各层 handler 未使用。
4. **无结果融合**：多层结果直接拼接返回，无去重、无跨层重排、无 token 预算控制。
5. **keyword 搜索质量差**：LIKE + 全词 AND 匹配无法处理部分匹配与权重排序。
6. **无 BM25**：缺少统计权重的全文检索，向量搜索在短查询/精确查询场景效果不佳。

---

## 2. 目标架构

### 2.1 检索数据流

```
┌─────────────────────────────────────────────────────────┐
│  调用入口                                                 │
│  MemoryQueryTool / ContextRetrievalService / API         │
│  （主 LLM 已完成查询拆分，每次调用传入单条语义意图）          │
└────────────────────────┬────────────────────────────────┘
                         │ RetrievalQuery
                         ▼
┌─────────────────────────────────────────────────────────┐
│  HybridRetrievalService                                  │
│                                                          │
│  ┌───────────────┐                                       │
│  │ L0 无条件加载   │ ← session_id 存在即读                 │
│  └───────────────┘                                       │
│                                                          │
│  ┌───────────────────────────────────────────────────┐   │
│  │ IntentDecider（意图决策器）                          │   │
│  │ 输入: query + user_id + session_id + time_range    │   │
│  │ 输出: List[LayerQueryPlan]                         │   │
│  │   - 查哪层 + 时间范围 + 结构化条件 + 是否兜底        │   │
│  └───────────────────────────────────────────────────┘   │
│                         │                                │
│                         ▼                                │
│  ┌──────── 并发执行非兜底查询 ────────┐                   │
│  │  L1Handler  L2Handler  L3Handler  L4Handler          │
│  │  (BM25+Vec  (图谱查询)  (BM25+Vec  (BM25+Vec         │
│  │   +Keyword)              +Keyword)  +Keyword)         │
│  └──────────────────────────────────┘                    │
│                         │                                │
│                         ▼                                │
│  ┌───────────────────────────────────────────────────┐   │
│  │ 结果判定：非兜底结果是否满足最低阈值？                 │   │
│  │   是 → 跳过兜底                                      │   │
│  │   否 → 执行兜底查询                                   │   │
│  └───────────────────────────────────────────────────┘   │
│                         │                                │
│                         ▼                                │
│  ┌───────────────────────────────────────────────────┐   │
│  │ ResultFusion（结果融合）                             │   │
│  │ 去重 + 跨层重排 + token 预算裁剪                      │   │
│  └───────────────────────────────────────────────────┘   │
│                         │                                │
└─────────────────────────┼───────────────────────────────┘
                          │ RetrievalPayload
                          ▼
               PromptContextAssembler / Tool 返回
```

### 2.2 各阶段职责边界

| 阶段 | 职责 | 不负责 |
|------|------|--------|
| **主 LLM（tool call 入口）** | 把用户自然语言拆成多条独立检索意图，每条意图作为一次 `memory_query` 调用 | 不理解记忆分层，不决定查哪层 |
| **IntentDecider** | 拿到单条查询意图后决定：查哪几层、时间范围、每层的结构化条件、哪些是兜底 | 不做查询拆分，不做数据库查询 |
| **LayerHandler** | 拿到结构化条件后执行数据库查询（BM25/向量/关键字/图谱） | 不调 LLM，不做意图分析 |
| **ResultFusion** | 多层结果去重、重排、裁剪 | 不改变各层原始查询逻辑 |

---

## 3. 已确认的设计决策

1. **意图决策器统一下发结构化条件**：各 handler 不二次调 LLM。
2. **L0 无条件加载**：不经过意图决策，session_id 存在即读。
3. **L1 引入 BM25**：基于 SQLite FTS5 实现三路检索（BM25 + 向量 + 关键字）。
4. **兜底查询由意图决策器声明**：不 hardcode 在 service 里。
5. **结果融合层必做**：去重 + 统一排序 + token 预算裁剪。
6. **意图决策采用 LLM 为主 + 规则 shadow 评估**：LLM 决策结果用于实际查询，规则引擎并行运行做 shadow 评估，两者的决策结果比对后入库，积累数据用于后续优化。

---

## 4. 待确认的设计决策

> **[Q1] 已确认**：意图决策采用 LLM 为主 + 规则 shadow 评估方案。
>
> - LLM 每次都调用，其决策结果用于实际检索路由。
> - 规则引擎同步并行执行，其决策结果仅用于 shadow 比对。
> - 两者的决策差异入库记录，积累真实数据用于后续分析。
> - 时间范围解析始终由规则层执行（LLM 对日历计算不如规则准确），LLM 输出中不包含时间解析。
> - LLM 失败/超时时降级到规则层结果。

> **[Q2] 已确认**：复用现有 `LLMScenario.CONTEXT_DECIDER`，不新增 scenario。
>
> 当前 `CONTEXT_DECIDER` 已配置为轻量模型（Anthropic: claude-haiku-4-5，GLM: glm-4.6），调用参数也已优化（`disable_thinking=True`，temperature 0.3，max_tokens 1024），适合记忆意图决策场景。

> **[Q3] 已确认**：使用 jieba 外部预处理 + FTS5 `simple` tokenizer。
>
> 写入时用 `jieba.cut_for_search()` 分词后空格拼接存入 FTS5；查询时对查询文本做同样分词处理。
> 相比 `unicode61` 按字分词，jieba 词级分词让 BM25 评分更准确，复合词查询（如"性能优化""机器学习"）精度显著优于按字分词。
> 成本：`pip install jieba`（~15MB），一个 `tokenize_for_fts()` 工具函数（~20行），写入/查询各调用一次。

> **[Q4] 已确认**：固定 token 上限，由配置项 `RetrievalConfig.default_max_tokens` 控制，默认 8192。
>
> retrieval service 内部按此值裁剪，调用方无需传入。

> **[Q5] 已确认**：L3/L4 也引入 FTS5 BM25，但优先级低于 L1，安排在独立的 Phase 5D 实施。
>
> L1 在 Phase 5B 完成三路检索后，Phase 5D 复用相同的 `fts_utils.tokenize_for_fts()` 和 RRF 融合逻辑，为 L3/L4 添加 FTS5。

> **[Q6] 已确认**：双层策略——向量搜索层过滤 + 纯条数兜底。
>
> 1. **向量搜索层**：`SqliteVecIndex.search()` 增加 `max_distance` 参数（默认 0.7，对应 cosine similarity ≈ 0.3），低置信度结果在搜索层直接丢弃。
> 2. **兜底层**：纯条数判断，count = 0 才触发兜底（`fallback_trigger_threshold = 1`）。
>
> 这样不需要在结果结构中携带 similarity 分数，兜底逻辑保持简单。

---

## 5. 核心数据契约

### 5.1 IntentDecider 输入

```python
@dataclass
class IntentDeciderInput:
    """传入意图决策器的查询上下文。"""
    query: str                              # 单条语义意图文本
    user_id: str | None
    session_id: str | None
    raw_time_range: dict[str, Any] | None   # 调用方传入的原始时间约束
    source_filters: list[str]               # 调用方级别的 source 过滤
    domain_filters: list[str]               # 调用方级别的 domain 过滤
```

### 5.2 IntentDecider 输出

```python
@dataclass
class TimeRange:
    """标准化的时间范围。"""
    start: float | None     # unix timestamp
    end: float | None       # unix timestamp

@dataclass
class LayerQueryPlan:
    """单层的查询计划。"""
    layer: Literal["L1", "L2", "L3", "L4"]
    time_range: TimeRange | None
    is_fallback: bool                       # True = 仅在上层无结果时执行
    conditions: L1Conditions | L2Conditions | L3Conditions | L4Conditions

@dataclass
class L1Conditions:
    """L1 查询条件：支持 BM25 + 向量 + 关键字。"""
    content_query: str                      # 用于 BM25 和向量检索的文本
    event_types: list[str] | None           # 事件类型过滤
    source_filters: list[str] | None        # source 过滤
    domain_filters: list[str] | None        # memory_domain 过滤
    importance_min: float | None            # 最低 importance 阈值
    limit: int = 10

@dataclass
class L2Conditions:
    """L2 查询条件：面向知识图谱与 ToM。"""
    entities: list[str] | None              # 待查实体列表
    entity_types: list[str] | None          # 实体类型过滤
    predicates: list[str] | None            # 关系谓词过滤
    include_tom_snapshot: bool = True       # 是否拉取 ToM 快照
    include_relationships: bool = True      # 是否拉取关系三元组
    limit: int = 20

@dataclass
class L3Conditions:
    """L3 查询条件：面向反思摘要。"""
    content_query: str                      # 用于向量+LIKE 检索的文本
    summary_types: list[str] | None         # temporal / thematic / insight
    limit: int = 5

@dataclass
class L4Conditions:
    """L4 查询条件：面向程序性记忆。"""
    content_query: str                      # 用于向量+LIKE 检索的文本
    skill_categories: list[str] | None      # tool / api / workflow / strategy
    limit: int = 5

@dataclass
class IntentDecision:
    """意图决策器的完整决策结果。"""
    plans: list[LayerQueryPlan]
    time_range: TimeRange | None            # 规则层解析的时间范围（始终来自规则层）
    reasoning: str | None                   # 决策理由（debug 用）
    source: str = "llm"                     # "llm" | "rule_fallback"
```

### 5.3 RetrievalQuery 扩展

在现有 `RetrievalQuery` 基础上扩展：

```python
@dataclass
class RetrievalQuery:
    """扩展后的查询契约。"""
    query: str
    user_id: str | None
    session_id: str | None
    time_range: dict[str, Any]              # 保留原始格式，由 IntentDecider 标准化
    query_mode: str | None                  # 保留兼容，可选；有值时作为 hint
    source_filters: list[str]
    domain_filters: list[str]
    limit: int = 10
```

> `max_tokens` 不再由调用方传入，统一从 `RetrievalConfig.default_max_tokens`（默认 8192）读取。

### 5.4 RetrievalPayload 不变

保持现有 `RetrievalPayload` 结构不变，新增 trace 细节：

```python
@dataclass
class RetrievalPayload:
    l0_workbench: list[dict]
    l1_events: list[dict]
    l2_entity_cards: list[dict]
    l2_relationships: list[dict]
    l3_reflections: list[dict]
    l4_procedures: list[dict]
    trace: dict                             # 含 intent_decision、各层耗时、fusion 状态
```

---

## 6. IntentDecider 设计

### 6.0 核心策略：LLM 为主 + 规则 Shadow 评估

意图决策器采用双轨并行模式：

1. **LLM 决策（主路径）**：每次查询都调用轻量 LLM 进行意图分类，其输出作为实际检索路由依据。
2. **规则决策（shadow 路径）**：同步并行执行规则引擎，产出规则层的决策结果，不影响实际检索。
3. **比对入库**：两者的决策结果做结构化比对，差异与一致性数据写入 `intent_evaluation_log` 表。
4. **LLM 降级**：LLM 超时或失败时，自动降级使用规则层结果。
5. **时间独占规则层**：时间范围解析始终由规则层负责（LLM 对 "上周三" 这种需要日历计算的场景不如规则准确），LLM 输出不包含时间字段。

```
┌─────────────────────────────────────────────────────┐
│                  IntentDecider                       │
│                                                      │
│   IntentDeciderInput                                 │
│        │                                             │
│        ├──────────────┬───────────────┐              │
│        │              │               │              │
│        ▼              ▼               │              │
│  ┌──────────┐  ┌──────────┐          │              │
│  │ LLM 决策  │  │ 规则决策  │          │              │
│  │ (主路径)  │  │ (shadow) │          │              │
│  └────┬─────┘  └────┬─────┘          │              │
│       │              │               │              │
│       │   ┌──────────┴──────┐        │              │
│       │   │ 时间范围解析     │        │              │
│       │   │ (始终来自规则层) │        │              │
│       │   └──────────┬──────┘        │              │
│       │              │               │              │
│       ▼              ▼               │              │
│  ┌─────────────────────────────┐     │              │
│  │ 比对 + 合并                  │     │              │
│  │ LLM 层级路由 + 规则时间范围  │     │              │
│  │ 差异写入 evaluation_log     │     │              │
│  └──────────┬──────────────────┘     │              │
│             │                        │              │
│             ▼            LLM 失败时 ──┘              │
│       IntentDecision     降级到规则结果              │
└─────────────────────────────────────────────────────┘
```

### 6.1 规则层（RuleBasedIntentDecider）

规则层同步执行，零 LLM 开销。负责两件事：

1. **时间范围解析**（始终生效，作为最终时间来源）
2. **层级路由**（作为 shadow 比对基线 + LLM 降级兜底）

#### 6.1.1 时间范围解析

从 `query` + `raw_time_range` 中提取时间约束，规则如下：

| 关键词/raw_time_range | 解析结果 |
|------------------------|---------|
| `raw_time_range = {"relative": "1d"}` | `TimeRange(now - 86400, now)` |
| `raw_time_range = {"start": ts, "end": ts}` | 直接使用 |
| 查询含 "昨天" / "yesterday" | `TimeRange(昨天 00:00, 昨天 23:59)` |
| 查询含 "前天" / "day before yesterday" | `TimeRange(前天 00:00, 前天 23:59)` |
| 查询含 "上周" / "last week" | `TimeRange(上周一 00:00, 上周日 23:59)` |
| 查询含 "上周三" / "last Wednesday" | `TimeRange(上周三 00:00, 上周三 23:59)` |
| 查询含 "上个月" / "last month" | `TimeRange(上月 1 日 00:00, 上月末 23:59)` |
| 查询含 "最近" / "recently" | `TimeRange(now - 7d, now)` |
| 查询含 "今天" / "today" | `TimeRange(今天 00:00, now)` |
| 查询含 "这周" / "this week" | `TimeRange(本周一 00:00, now)` |
| 查询含 "N天前" / "N days ago" | `TimeRange(N天前 00:00, N天前 23:59)` |
| 查询含具体日期（"3月10号"、"March 5th"） | 解析为对应日期区间 |
| 无时间信号 | `None`（不限时间） |

#### 6.1.2 层级路由规则

| 信号 | 路由 | 兜底 |
|------|------|------|
| 查询含人名 / "关系" / "谁" / "认识" | L2（主）+ L1（兜底） | |
| 查询含 "总结" / "回顾" / "这周" | L3（主）+ L1（兜底） | |
| 查询含 "怎么做" / "上次怎么" / "经验" | L4（主）+ L1（兜底） | |
| 查询含 "浏览" / "看了" / "聊了" / 具体事件 | L1（主）+ L3（兜底） | |
| `query_mode` 被显式指定 | 按 mode 映射（detail→L1, summary→L3, graph→L2, experience/strategy→L4），附加兜底 | |
| 规则层无法判断 | L1（主）+ L3（兜底）作为默认路由 | |

#### 6.1.3 source / domain 过滤推断

| 信号 | source_filters | domain_filters |
|------|---------------|----------------|
| "浏览" / "browsing" | `["browser_history"]` | `["external_activity"]` |
| "聊天" / "对话" | `["chat"]` | `["user_authored"]` |
| "终端" / "git" | `["terminal", "git"]` | `["external_activity"]` |
| "日记" / "笔记" | `["journal", "note"]` | `["user_authored"]` |
| "日历" / "开会" / "calendar" | `["calendar"]` | `["external_activity"]` |
| "音乐" / "听了" / "music" | `["music"]` | `["external_activity"]` |

### 6.2 LLM 层（LLMIntentDecider）

每次查询都调用轻量 LLM 进行意图分类。LLM 只负责层级路由和条件生成，不负责时间解析。

#### 6.2.1 Prompt 模板

```text
你是一个记忆系统的检索意图分析器。根据用户的查询意图，决定应该查询哪些记忆层，并生成每层的检索条件。

记忆层说明：
- L1（事件流）：具体的历史事件、聊天记录、浏览记录、活动记录
- L2（知识图谱）：人物关系、实体属性、用户画像
- L3（反思摘要）：时期总结、主题回顾、洞察结论
- L4（程序性记忆）：工具使用经验、操作策略、最佳实践

用户查询：{query}

注意：
- 时间范围解析由系统处理，你不需要输出时间信息。
- 可以选择多层查询。
- 标记 is_fallback=true 的层只在主查询无结果时执行。
- 对 L2 查询，请提取相关实体名。
- content_query 是传入该层检索引擎的优化后查询文本，应去除时间词和无关修饰。

请返回 JSON：
{
  "layers": [
    {
      "layer": "L1" | "L2" | "L3" | "L4",
      "is_fallback": false | true,
      "content_query": "用于该层检索的关键文本",
      "entities": ["实体名"],
      "source_filters": ["chat", "browser_history", ...],
      "domain_filters": ["user_authored", "external_activity", ...]
    }
  ],
  "reasoning": "简短解释"
}
```

#### 6.2.2 LLM 调用约束

- 复用 `LLMScenario.CONTEXT_DECIDER`（已有轻量模型配置：Anthropic claude-haiku-4-5 / Zhipuai glm-4.6）
- 超时：3 秒
- 失败降级：使用规则层的完整决策结果

### 6.3 组合策略与 Shadow 比对

```python
class IntentDecider:
    """LLM 为主 + 规则 shadow 评估的组合意图决策器。"""

    async def decide(self, input: IntentDeciderInput) -> IntentDecision:
        # 1. 规则层始终执行（同步，用于时间解析 + shadow 比对基线）
        rule_decision = self._rule_engine.evaluate(input)
        time_range = rule_decision.time_range  # 时间始终来自规则层

        # 2. LLM 决策（主路径）
        llm_decision: IntentDecision | None = None
        if self._llm_enabled:
            llm_decision = await self._llm_decider.evaluate(input)

        # 3. 确定最终决策
        if llm_decision is not None:
            # LLM 成功：用 LLM 的层级路由 + 规则的时间范围
            final_decision = self._merge_decisions(
                llm_routing=llm_decision,
                rule_time_range=time_range,
            )
            decision_source = "llm"
        else:
            # LLM 失败：降级到规则层完整结果
            final_decision = rule_decision
            decision_source = "rule_fallback"

        # 4. Shadow 比对入库（异步，不阻塞主流程）
        asyncio.create_task(self._log_evaluation(
            input=input,
            rule_decision=rule_decision,
            llm_decision=llm_decision,
            final_decision=final_decision,
            decision_source=decision_source,
        ))

        return final_decision

    def _merge_decisions(
        self,
        llm_routing: IntentDecision,
        rule_time_range: TimeRange | None,
    ) -> IntentDecision:
        """合并 LLM 的层级路由与规则层的时间范围。"""
        for plan in llm_routing.plans:
            plan.time_range = rule_time_range
        return llm_routing
```

### 6.4 Shadow 评估日志

#### 6.4.1 日志表结构

```sql
CREATE TABLE intent_evaluation_log (
    log_id TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    user_id TEXT,
    session_id TEXT,
    created_at REAL NOT NULL,

    -- 规则层决策
    rule_layers TEXT NOT NULL,           -- JSON: [{"layer": "L1", "is_fallback": false, ...}]
    rule_time_range TEXT,                -- JSON: {"start": ..., "end": ...}
    rule_source_filters TEXT,            -- JSON
    rule_domain_filters TEXT,            -- JSON

    -- LLM 决策
    llm_layers TEXT,                     -- JSON: [{"layer": "L1", ...}], null if LLM failed
    llm_reasoning TEXT,
    llm_latency_ms REAL,
    llm_error TEXT,                      -- null if success

    -- 最终使用的决策
    final_source TEXT NOT NULL,          -- 'llm' | 'rule_fallback'
    final_layers TEXT NOT NULL,          -- JSON

    -- 比对结果
    layers_match INTEGER NOT NULL,       -- 1=两者层级路由完全一致, 0=不一致
    diff_summary TEXT,                   -- 差异描述，如 "rule=L1+L3, llm=L2+L1"

    -- 检索结果反馈（由 service 回写）
    result_count INTEGER,                -- 最终返回的结果总数
    fallback_triggered INTEGER           -- 是否触发了兜底查询
);

CREATE INDEX idx_eval_log_created ON intent_evaluation_log(created_at);
CREATE INDEX idx_eval_log_match ON intent_evaluation_log(layers_match);
CREATE INDEX idx_eval_log_source ON intent_evaluation_log(final_source);
```

#### 6.4.2 比对逻辑

```python
def _compute_diff(
    rule_decision: IntentDecision,
    llm_decision: IntentDecision | None,
) -> tuple[bool, str]:
    """比对规则与 LLM 决策，返回 (是否一致, 差异摘要)。"""
    if llm_decision is None:
        return False, "llm_failed"

    rule_layers = sorted({p.layer for p in rule_decision.plans if not p.is_fallback})
    llm_layers = sorted({p.layer for p in llm_decision.plans if not p.is_fallback})

    if rule_layers == llm_layers:
        return True, "match"

    return False, f"rule={'+'.join(rule_layers)}, llm={'+'.join(llm_layers)}"
```

#### 6.4.3 数据分析用途

积累到足够数据后，可以做以下分析：

1. **规则覆盖率**：`layers_match = 1` 的比例，即规则与 LLM 结论一致的占比
2. **规则偏差分布**：按 `diff_summary` 聚合，看规则层最常在哪些场景与 LLM 不一致
3. **LLM 失败率**：`llm_error IS NOT NULL` 的比例
4. **LLM 延迟分布**：`llm_latency_ms` 的 P50/P95/P99
5. **兜底触发率**：`fallback_triggered = 1` 的比例
6. **决策有效性**：`result_count = 0` 的比例（决策是否导致检索空结果）

当规则覆盖率达到目标阈值（如 85%+），且规则偏差集中在少数可识别模式时，可以考虑对高置信场景切换为规则优先，降低 LLM 成本。

---

## 7. LayerHandler 设计

### 7.1 L1Handler：三路混合检索

L1 事件量最大、查询最频繁，需要最完整的检索能力。

#### 7.1.1 三路检索架构

```
L1Conditions.content_query
     ├── FTS5 BM25 查询  → top K₁ candidates (bm25 score)
     ├── sqlite-vec 向量  → top K₂ candidates (cosine similarity)
     └── SQL 关键字匹配   → top K₃ candidates (存在性 boost)
              ↓
      Reciprocal Rank Fusion (RRF)
              ↓
      + time_range 过滤
      + source/domain 过滤
      + importance boost
              ↓
      Final ranked results (limit)
```

#### 7.1.2 FTS5 虚拟表

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS l1_events_fts USING fts5(
    event_id UNINDEXED,
    raw_content,
    tokenize='simple'
);
```

分词工具函数（jieba 预处理）：

```python
import jieba

def tokenize_for_fts(text: str) -> str:
    """将文本用 jieba 分词后以空格拼接，供 FTS5 simple tokenizer 使用。"""
    return " ".join(jieba.cut_for_search(text))
```

写入时先分词再存入 FTS 表：

```sql
INSERT INTO l1_events_fts(event_id, raw_content) VALUES (?, ?);
-- raw_content = tokenize_for_fts(event.raw_content)
```

查询时使用 `bm25()` 排序：

```sql
SELECT event_id, bm25(l1_events_fts) AS score
FROM l1_events_fts
WHERE l1_events_fts MATCH ?
ORDER BY score
LIMIT ?;
```

#### 7.1.3 RRF 融合

使用 Reciprocal Rank Fusion：

$$\text{score}(d) = \sum_{r \in \{bm25, vec, kw\}} \frac{w_r}{k + \text{rank}_r(d)}$$

默认参数：
- $k = 60$
- $w_{bm25} = 1.0$
- $w_{vec} = 1.0$
- $w_{kw} = 0.5$（关键字匹配权重较低，作为精确匹配补充）

#### 7.1.4 time_range 消费

```python
async def _apply_time_filter(self, event_ids: list[str], time_range: TimeRange | None) -> list[str]:
    if time_range is None:
        return event_ids
    # SQL: WHERE timestamp >= ? AND timestamp <= ? AND event_id IN (...)
```

### 7.2 L2Handler：图谱查询

L2 不涉及全文检索，走结构化图谱查询：

```python
async def execute(self, conditions: L2Conditions, time_range: TimeRange | None) -> dict:
    results = {}
    if conditions.include_tom_snapshot and conditions.entities:
        for entity in conditions.entities:
            snapshot = await self._l2_store.get_tom_snapshot(entity_id=entity, entity_type="user")
            if snapshot:
                results.setdefault("entity_cards", []).append(snapshot)

    if conditions.include_relationships:
        rels = await self._l2_store.get_relationships(
            subject_ids=conditions.entities,
            predicates=conditions.predicates,
            limit=conditions.limit,
        )
        results["relationships"] = rels
    return results
```

### 7.3 L3Handler：摘要检索

保持现有 向量+LIKE 双路检索，新增 time_range 消费和 summary_type 过滤：

```python
async def execute(self, conditions: L3Conditions, time_range: TimeRange | None) -> list[dict]:
    return await self._l3_store.search_summaries(
        query=conditions.content_query,
        summary_types=conditions.summary_types,
        time_range=time_range,
        limit=conditions.limit,
    )
```

### 7.4 L4Handler：程序性记忆检索

保持现有 向量+LIKE 双路检索，新增 skill_category 过滤：

```python
async def execute(self, conditions: L4Conditions, time_range: TimeRange | None) -> list[dict]:
    return await self._l4_store.query_strategies(
        query=conditions.content_query,
        skill_categories=conditions.skill_categories,
        limit=conditions.limit,
    )
```

---

## 8. ResultFusion 设计

### 8.1 去重

同一个 `event_id`（L1）或 `summary_id`（L3）出现在多层结果中时只保留一次。优先保留高层结果（L3 > L1）。

### 8.2 跨层排序

各层结果保持层内排序不变，不做跨层 re-rank。原因：各层的评分语义不同（BM25 score vs cosine similarity vs confidence），跨层排序需要归一化，复杂度高且收益不确定。

token 预算内按以下固定优先级截取：

```
1. L0 workbench（全量，通常很小）
2. L2 entity_cards + relationships（全量或 limit 截取）
3. L4 procedures（按原始排序截取）
4. L3 reflections（按原始排序截取）
5. L1 events（按原始排序截取，吃剩余预算）
```

### 8.3 Token 预算裁剪

```python
def apply_token_budget(payload: RetrievalPayload, max_tokens: int) -> RetrievalPayload:
    """按优先级裁剪 payload 到 max_tokens 以内。

    max_tokens 由 RetrievalConfig.default_max_tokens 提供（默认 8192）。
    """
    budget = max_tokens
    # L0: 全量（通常 < 500 tokens）
    budget -= estimate_tokens(payload.l0_workbench)
    # L2: 全量
    budget -= estimate_tokens(payload.l2_entity_cards + payload.l2_relationships)
    # L4: 截取
    payload.l4_procedures = truncate_to_budget(payload.l4_procedures, budget * 0.2)
    budget -= estimate_tokens(payload.l4_procedures)
    # L3: 截取
    payload.l3_reflections = truncate_to_budget(payload.l3_reflections, budget * 0.3)
    budget -= estimate_tokens(payload.l3_reflections)
    # L1: 吃剩余
    payload.l1_events = truncate_to_budget(payload.l1_events, budget)
    return payload
```

`estimate_tokens` 使用简单的字符数 / 3 作为中文 token 估算（或接入 tiktoken）。

---

## 9. HybridRetrievalService 主流程

```python
class HybridRetrievalService:
    async def query(self, request: RetrievalQuery) -> RetrievalPayload:
        payload = RetrievalPayload(trace={"query": request.query})

        # 1. L0 无条件加载
        if request.session_id and self._memory.l0:
            payload.l0_workbench = await self._load_l0(request.session_id)

        # 2. 意图决策
        intent_input = IntentDeciderInput(
            query=request.query,
            user_id=request.user_id,
            session_id=request.session_id,
            raw_time_range=request.time_range,
            source_filters=request.source_filters,
            domain_filters=request.domain_filters,
        )
        decision = await self._intent_decider.decide(intent_input)
        payload.trace["intent_decision"] = asdict(decision)

        # 3. 并发执行非兜底查询
        primary_plans = [p for p in decision.plans if not p.is_fallback]
        primary_results = await asyncio.gather(
            *[self._execute_plan(plan) for plan in primary_plans]
        )

        # 4. 合并主查询结果
        for plan, result in zip(primary_plans, primary_results):
            self._merge_result(payload, plan.layer, result)

        # 5. 判断是否需要兜底（低置信结果已在向量搜索层被 max_distance 过滤，这里纯看条数）
        primary_count = self._count_results(payload)
        if primary_count < self._config.fallback_trigger_threshold:
            fallback_plans = [p for p in decision.plans if p.is_fallback]
            fallback_results = await asyncio.gather(
                *[self._execute_plan(plan) for plan in fallback_plans]
            )
            for plan, result in zip(fallback_plans, fallback_results):
                self._merge_result(payload, plan.layer, result)

        # 6. 结果融合
        payload = self._result_fusion.apply(payload, max_tokens=request.max_tokens)

        return payload
```

---

## 10. 与现有入口的集成

### 10.1 MemoryQueryTool

改造点：
- 增加 `max_tokens` 参数
- `query_mode` 变为可选 hint（传入时作为意图决策的强信号，不传时由 IntentDecider 自动判断）
- 去掉 tool 层的 mode 硬路由，全部交给 HybridRetrievalService

### 10.2 ContextRetrievalService

改造点：
- 当前发 3 次并行查询（detail + summary + experience），改为单次查询
- `task_category` 作为 query text 传入，由 IntentDecider 自动路由
- 不再硬指定 `query_mode`

### 10.3 ContextDecider

改造点：
- `evaluate_memory_need()` 的关键词触发保留（判断是否需要记忆查询）
- 去掉内部的时间/类型推断逻辑（这部分移入 IntentDecider 规则层）
- 只负责判断"要不要查记忆"，不再负责"怎么查"

---

## 11. FTS5 索引管理

### 11.1 FTS5 表创建

在 L1EventStore 初始化时创建：

```python
async def _ensure_fts_index(self):
    async with aiosqlite.connect(self._db_path) as db:
        await db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS l1_events_fts USING fts5(
                event_id UNINDEXED,
                raw_content,
                tokenize='simple'
            )
        """)
```

### 11.2 FTS5 索引写入

`store_event()` 写入 L1 后同步写入 FTS 表：

```python
from magi.memory.hybrid_retrieval.fts_utils import tokenize_for_fts

await db.execute(
    "INSERT INTO l1_events_fts(event_id, raw_content) VALUES (?, ?)",
    (event.event_id, tokenize_for_fts(event.raw_content)),
)
```

### 11.3 FTS5 索引删除

`soft_delete_event()` 时同步删除 FTS 记录：

```python
await db.execute(
    "DELETE FROM l1_events_fts WHERE event_id = ?",
    (event_id,),
)
```

### 11.4 历史数据回填

提供一次性脚本回填已有 L1 事件到 FTS 表：

```python
async def backfill_fts_index(self):
    """回填已有 L1 事件到 FTS 表（需逐条 jieba 分词）。"""
    from magi.memory.hybrid_retrieval.fts_utils import tokenize_for_fts

    async with aiosqlite.connect(self._db_path) as db:
        await db.execute("DELETE FROM l1_events_fts")
        cursor = await db.execute(
            "SELECT event_id, raw_content FROM events WHERE deleted_at IS NULL"
        )
        rows = await cursor.fetchall()
        await db.executemany(
            "INSERT INTO l1_events_fts(event_id, raw_content) VALUES (?, ?)",
            [(eid, tokenize_for_fts(content)) for eid, content in rows],
        )
        await db.commit()
```

---

## 12. 实施计划

### Phase 5A：检索骨架（IntentDecider + 新 Service 流程）

**前置依赖**：Phase 0-4 已完成（L0-L4 存储层已实现）

#### 文件清单

| 动作 | 文件 |
|------|------|
| 新增 | `backend/src/magi/memory/hybrid_retrieval/intent_decider.py` |
| 新增 | `backend/src/magi/memory/hybrid_retrieval/evaluation_store.py` |
| 新增 | `backend/src/magi/memory/hybrid_retrieval/result_fusion.py` |
| 新增 | `backend/src/magi/memory/hybrid_retrieval/handlers.py` |
| 重写 | `backend/src/magi/memory/hybrid_retrieval/models.py` |
| 重写 | `backend/src/magi/memory/hybrid_retrieval/service.py` |
| 修改 | `backend/src/magi/memory/hybrid_retrieval/router.py` |
| 修改 | `backend/src/magi/memory/hybrid_retrieval/__init__.py` |
| 修改 | `backend/src/magi/memory/sqlite_vec_index.py` |
| 新增 | `backend/tests/memory/test_intent_decider.py` |
| 新增 | `backend/tests/memory/test_evaluation_store.py` |
| 新增 | `backend/tests/memory/test_result_fusion.py` |
| 修改 | `backend/tests/memory/test_hybrid_retrieval.py` |

#### Task 5A.1：扩展查询契约

- [ ] 在 `models.py` 中新增 `IntentDeciderInput`、`LayerQueryPlan`、`L1Conditions`、`L2Conditions`、`L3Conditions`、`L4Conditions`、`TimeRange`、`IntentDecision`
- [ ] 测试：数据类构造与序列化
- [ ] commit: `feat: extend retrieval query contracts`

#### Task 5A.1.5：SqliteVecIndex 增加 max_distance 过滤

- [ ] `SqliteVecIndex.search()` 增加可选 `max_distance: float | None` 参数
- [ ] 当 `max_distance` 不为 None 时，在 SQL 层直接过滤：`WHERE embedding MATCH ? AND distance < ?`
- [ ] 测试：验证过滤生效、None 时不过滤
- [ ] commit: `feat: add max_distance filter to sqlite vec search`

#### Task 5A.2：实现 RuleBasedIntentDecider

- [ ] 实现时间范围解析（中英文关键词 + raw_time_range 标准化 + 日历计算）
- [ ] 实现层级路由规则（关键词信号 → 层级映射）
- [ ] 实现 source/domain 过滤推断
- [ ] 测试：覆盖时间解析、层级路由、关键词分类、无信号默认路由
- [ ] 预备验证：`cd backend && pytest tests/memory/test_intent_decider.py -v`
- [ ] commit: `feat: add rule-based intent decider`

#### Task 5A.3：实现 LLMIntentDecider

- [ ] 复用 `LLMScenario.CONTEXT_DECIDER` 调用 LLM
- [ ] 实现 LLM prompt 构造与响应解析
- [ ] 实现超时与降级逻辑（降级到规则层结果）
- [ ] 测试：mock LLM 响应验证解析、超时降级到规则层
- [ ] commit: `feat: add llm intent decider`

#### Task 5A.4：实现组合 IntentDecider + Shadow 评估

- [ ] 实现 `IntentDecider` 双轨并行（LLM 为主 + 规则 shadow）
- [ ] 实现 LLM 路由 + 规则时间范围的合并逻辑
- [ ] 实现 LLM 失败时降级到规则层
- [ ] 创建 `intent_evaluation_log` 表
- [ ] 实现 shadow 比对逻辑与异步入库
- [ ] 实现 service 层检索结果回写（result_count、fallback_triggered）
- [ ] 测试：LLM 成功时用 LLM 路由、LLM 失败降级、比对日志正确写入
- [ ] commit: `feat: add composite intent decider with shadow evaluation`

#### Task 5A.5：实现 LayerHandler

- [ ] 实现 `L1Handler`（暂用现有 search_events，不含 BM25）
- [ ] 实现 `L2Handler`（图谱 + ToM 查询）
- [ ] 实现 `L3Handler`（摘要检索 + time_range）
- [ ] 实现 `L4Handler`（策略检索 + skill_category）
- [ ] 各 handler 统一实现 `time_range` 消费
- [ ] 测试：各 handler 独立可测
- [ ] commit: `feat: add layer query handlers`

#### Task 5A.6：实现 ResultFusion

- [ ] 实现去重逻辑
- [ ] 实现 token 预算裁剪
- [ ] 测试：去重、预算裁剪、空结果处理
- [ ] commit: `feat: add result fusion service`

#### Task 5A.7：重写 HybridRetrievalService 主流程

- [ ] 按第 9 节重写 `service.py` 主流程
- [ ] 集成 IntentDecider + handlers + ResultFusion
- [ ] 保留 L0 无条件加载
- [ ] 保留 trace 输出
- [ ] 集成测试：端到端查询流程
- [ ] commit: `feat: rewrite hybrid retrieval service`

### Phase 5B：L1 BM25 三路检索

#### 文件清单

| 动作 | 文件 |
|------|------|
| 新增 | `backend/src/magi/memory/hybrid_retrieval/fts_utils.py` |
| 修改 | `backend/src/magi/memory/l1_event_store.py` |
| 修改 | `backend/src/magi/memory/hybrid_retrieval/handlers.py` |
| 修改 | `backend/requirements.txt` |
| 新增 | `backend/tests/memory/test_l1_fts5.py` |

#### Task 5B.1：L1 FTS5 索引 + jieba 预处理

- [ ] 新增 `backend/src/magi/memory/hybrid_retrieval/fts_utils.py`，实现 `tokenize_for_fts()`（jieba 预处理）
- [ ] 在 L1EventStore 初始化时创建 FTS5 虚拟表（`tokenize='simple'`）
- [ ] 写入时先 `tokenize_for_fts()` 分词再写入 FTS 表
- [ ] 删除时同步清理 FTS 记录
- [ ] 提供 backfill 方法（逐条 jieba 分词后批量写入）
- [ ] 在 `requirements.txt` 中添加 `jieba` 依赖
- [ ] 测试：FTS5 写入、删除、backfill、jieba 分词正确性
- [ ] commit: `feat: add fts5 index with jieba tokenization for l1 events`

#### Task 5B.2：L1 BM25 查询

- [ ] 实现 `_bm25_search(query, limit)` → `list[(event_id, bm25_score)]`
- [ ] 查询时先 `tokenize_for_fts(query)` 分词再 MATCH
- [ ] 处理 FTS5 查询语法（特殊字符转义）
- [ ] 测试：BM25 查询命中、无结果、特殊字符、中文分词查询
- [ ] commit: `feat: add bm25 search for l1 events`

#### Task 5B.3：三路 RRF 融合

- [ ] 实现 RRF 融合函数
- [ ] 修改 L1Handler 为三路并发查询 + RRF
- [ ] 与 time_range / source / domain 过滤结合
- [ ] 测试：三路融合排序、单路缺失时退化
- [ ] commit: `feat: add rrf fusion for l1 triple-path search`

### Phase 5C：入口集成

#### 文件清单

| 动作 | 文件 |
|------|------|
| 修改 | `backend/src/magi/tools/builtin/memory_query_tool.py` |
| 修改 | `backend/src/magi/context/retrieval.py` |
| 修改 | `backend/src/magi/tools/context_decider.py` |
| 修改 | `backend/src/magi/memory/hybrid_retrieval/router.py` |
| 修改 | `backend/tests/memory/test_hybrid_retrieval.py` |

#### Task 5C.1：改造 MemoryQueryTool

- [ ] `query_mode` 变为可选 hint
- [ ] 去掉 tool 层的 mode 硬路由
- [ ] commit: `refactor: simplify memory query tool`

#### Task 5C.2：改造 ContextRetrievalService

- [ ] 3 次并行查询合并为 1 次
- [ ] `task_category` 作为 query text
- [ ] 去掉硬指定 `query_mode`
- [ ] commit: `refactor: simplify context retrieval service`

#### Task 5C.3：改造 ContextDecider

- [ ] 保留 `evaluate_memory_need()` 的触发判断
- [ ] 去掉内部时间/类型推断（移入 IntentDecider）
- [ ] commit: `refactor: strip intent logic from context decider`

### Phase 5D：L3/L4 BM25 三路检索（低优先级）

**前置依赖**：Phase 5B 已完成（L1 FTS5 + jieba + RRF 已验证）

#### 文件清单

| 动作 | 文件 |
|------|------|
| 修改 | `backend/src/magi/memory/l3_summary_store.py` |
| 修改 | `backend/src/magi/memory/l4_procedural_memory.py` |
| 修改 | `backend/src/magi/memory/hybrid_retrieval/handlers.py` |
| 新增 | `backend/tests/memory/test_l3_fts5.py` |
| 新增 | `backend/tests/memory/test_l4_fts5.py` |

#### Task 5D.1：L3 FTS5 索引

- [ ] 在 L3SummaryStore 初始化时创建 FTS5 虚拟表（`tokenize='simple'`）
- [ ] 写入时先 `tokenize_for_fts()` 分词再写入 FTS 表
- [ ] 删除时同步清理 FTS 记录
- [ ] 提供 backfill 方法
- [ ] 测试：FTS5 写入、删除、backfill
- [ ] commit: `feat: add fts5 index with jieba tokenization for l3 summaries`

#### Task 5D.2：L4 FTS5 索引

- [ ] 在 L4ProceduralMemory 初始化时创建 FTS5 虚拟表（`tokenize='simple'`）
- [ ] 写入时先 `tokenize_for_fts()` 分词再写入 FTS 表
- [ ] 删除时同步清理 FTS 记录
- [ ] 提供 backfill 方法
- [ ] 测试：FTS5 写入、删除、backfill
- [ ] commit: `feat: add fts5 index with jieba tokenization for l4 procedures`

#### Task 5D.3：L3/L4 Handler 升级为三路 RRF

- [ ] 复用 Phase 5B 的 RRF 融合函数
- [ ] 修改 L3Handler / L4Handler 为三路并发查询 + RRF
- [ ] 测试：三路融合排序、单路缺失时退化
- [ ] commit: `feat: add rrf fusion for l3 and l4 search`

---

## 13. 验收标准

### 13.1 功能验收

- [ ] 复合查询（含时间 + 类型 + 实体线索）能被正确路由到多层
- [ ] 兜底查询在主查询无结果时触发
- [ ] BM25 + 向量 + 关键字三路融合在 L1 可跑通
- [ ] time_range 在各层真正被消费
- [ ] token 预算裁剪生效

### 13.2 性能验收

- [ ] 单次检索端到端延迟 < 3s（含 LLM 意图决策，正常路径）
- [ ] LLM 失败降级后延迟 < 500ms（规则路由）
- [ ] FTS5 索引不显著影响 L1 写入性能
- [ ] shadow 评估日志写入不阻塞主检索流程

### 13.3 兼容性验收

- [ ] MemoryQueryTool 向后兼容（显式传 query_mode 仍有效）
- [ ] PromptContextAssembler 无需修改（payload 结构不变）
- [ ] API 接口 `/memory/query` 向后兼容

### 13.4 测试命令

```bash
cd backend && pytest tests/memory/test_intent_decider.py tests/memory/test_evaluation_store.py tests/memory/test_result_fusion.py tests/memory/test_hybrid_retrieval.py tests/memory/test_l1_fts5.py -v
```

---

## 14. 配置项

新增配置项：

```python
@dataclass
class RetrievalConfig:
    # IntentDecider
    intent_decider_llm_enabled: bool = True
    intent_decider_llm_timeout_seconds: float = 3.0
    intent_decider_fallback_on_error: bool = True     # LLM 失败时降级到规则
    intent_shadow_eval_enabled: bool = True           # 是否启用 shadow 比对入库

    # BM25
    fts5_enabled: bool = True
    fts5_tokenizer: str = "simple"          # jieba 预处理 + simple tokenizer

    # RRF
    rrf_k: int = 60
    rrf_weight_bm25: float = 1.0
    rrf_weight_vector: float = 1.0
    rrf_weight_keyword: float = 0.5

    # ResultFusion
    default_max_tokens: int = 8192
    fallback_trigger_threshold: int = 1   # 非兜底结果 < N 条时触发兜底

    # 向量搜索过滤
    vector_max_distance: float = 0.7      # 余弦距离上限（= 1 - cosine_similarity，0.7 ≈ sim 0.3）

    # Token 估算
    token_estimator: Literal["char_ratio", "tiktoken"] = "char_ratio"
    char_per_token_ratio: float = 3.0     # 中文约 1 字 ≈ 1 token, 取保守值
```

---

## 15. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| jieba 分词不完美 | 部分专有名词/新词切分错误 | `jieba.cut_for_search()` 使用搜索引擎模式（细粒度+全模式），容错性好；可通过 `jieba.load_userdict()` 补充领域词典 |
| IntentDecider LLM 调用延迟 | 检索延迟增加 | 3s 超时 + 规则降级；规则层作为 fallback 不会阻塞 |
| LLM 意图决策成本 | 每次查询都调 LLM | 使用轻量模型；shadow 数据积累后可对高置信场景切规则 |
| 三路融合的 RRF 权重需调参 | 排序质量不稳定 | 默认权重保守，提供配置项，后续按实测调优 |
| token 预算估算不准 | prompt 截断或超限 | 预留 10% buffer；char_ratio 可切 tiktoken |
| 意图决策错误路由 | 查不到相关记忆 | 兜底查询兜底；shadow 日志可定位偏差模式 |
| evaluation_log 表膨胀 | 存储增长 | 定期清理旧日志（如保留 30 天） |
