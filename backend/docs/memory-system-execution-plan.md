# Memory System Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current plugin-styled memory stack with the new L0-L4 lifecycle-based memory system defined in `backend/docs/memory-system-design.md`, without preserving old data or schemas.

**Architecture:** The implementation proceeds in four chunks. First, standardize event contracts and land L0/L1 as the new memory backbone. Second, replace the split relation/user-graph model with a unified L2 cognition store and defensive ToM pipeline. Third, rebuild L3/L4 as reflection memory and procedural memory. Finally, replace retrieval, prompt integration, memory API, and housekeeping so the runtime reads from the new memory graph end-to-end.

**Tech Stack:** Python 3.10+, SQLite, aiosqlite, FastAPI, Pydantic v2, asyncio, pytest, current Magi runtime bootstrap and task-agent architecture.

## Document Boundary

To keep docs consistent and avoid duplicate architecture sources:

1. Root `docs/` files are the baseline for project, product, and runtime semantics.
2. This file is an execution-level plan for backend memory implementation only.
3. If any step here conflicts with root `docs/`, align root docs first, then update this plan.

---

## Scope Notes

- No historical data migration.
- No old table compatibility.
- `SelfMemory`, `OtherMemory`, and scenario prompt storage stay in place.
- This plan targets backend runtime and memory modules only.
- Every completed task should be committed immediately with a Conventional Commit message.

## File Map

### New files

- `backend/src/magi/memory/event_contracts.py`
- `backend/src/magi/memory/l0_working_memory.py`
- `backend/src/magi/memory/l1_event_store.py`
- `backend/src/magi/memory/l2_cognition_store.py`
- `backend/src/magi/memory/l2_extractors.py`
- `backend/src/magi/memory/l3_summary_store.py`
- `backend/src/magi/memory/l3_generators.py`
- `backend/src/magi/memory/l4_procedural_memory.py`
- `backend/src/magi/memory/hybrid_retrieval/models.py`
- `backend/src/magi/memory/hybrid_retrieval/router.py`
- `backend/src/magi/memory/hybrid_retrieval/service.py`
- `backend/src/magi/memory/hybrid_retrieval/__init__.py`
- `backend/tests/memory/test_memory_event_contracts.py`
- `backend/tests/memory/test_l0_working_memory.py`
- `backend/tests/memory/test_l1_event_store.py`
- `backend/tests/memory/test_l2_cognition_store.py`
- `backend/tests/memory/test_l3_summary_store.py`
- `backend/tests/memory/test_l4_procedural_memory.py`
- `backend/tests/memory/test_hybrid_retrieval.py`
- `backend/tests/agent/test_chat_prompt_memory_payload.py`

### Replace or heavily rewrite

- `backend/src/magi/memory/__init__.py`
- `backend/src/magi/memory/integration.py`
- `backend/src/magi/memory/prompt_context_assembler.py`
- `backend/src/magi/agent/task_agents/chat/prompt_service.py`
- `backend/src/magi/bootstrap/backend.py`
- `backend/src/magi/tools/memory_query.py`
- `backend/src/magi/api/routers/memory.py`

### Remove after replacement

- `backend/src/magi/memory/raw_event_store.py`
- `backend/src/magi/memory/l2_event_relations.py`
- `backend/src/magi/memory/l2_user_graph.py`
- `backend/src/magi/memory/l3_semantic_embeddings.py`
- `backend/src/magi/memory/l4_summaries.py`
- `backend/src/magi/memory/l5_capabilities.py`
- `backend/src/magi/memory/query/`

---

## Phase Kickoff Checklists

以下清单用于每个阶段正式开工前的准备检查。

原则：

1. 每个阶段开始前先做一次范围确认，避免跨阶段顺手改动。
2. 每个阶段开始前明确本阶段新增文件、替换文件、删除文件。
3. 每个阶段开始前先确认最小验证命令，避免写完才想起怎么验。
4. 每个阶段结束后立即提交，不把下一阶段准备混进同一个 commit。

### Phase 0 开工清单: 事件标准与配置

- [ ] 回读 [memory-system-design.md](/Users/asuka/code/magi/backend/docs/memory-system-design.md) 的第 4、6、15 节，确认 `memory_domain`、`ingest_target`、`retention_class`、LLM 开关字段不再变化。
- [ ] 列出当前所有 memory 写入入口：
  `MemoryIntegrationModule`、timeline 写入入口、直接 `UnifiedMemoryStore.add_event()` 调用点。
- [ ] 盘点当前运行时事件类型来源，至少覆盖：
  `USER_MESSAGE`、`ACTION_EXECUTED`、`TASK_*`、`WORKER_AGENT_*`、`ERROR_OCCURRED`、timeline 事件。
- [ ] 确认本阶段不实现新存储，只落 contract、normalizer、config。
- [ ] 先创建测试文件 `backend/tests/memory/test_memory_event_contracts.py`，把事件分流矩阵写成断言。
- [ ] 预备验证命令：
  `cd backend && pytest tests/memory/test_memory_event_contracts.py -v`

### Phase 1 开工清单: L0 + 新 L1

- [ ] 回读设计文档第 5、6 节，确认 L0 checkpoint 策略与 L1 字段集合。
- [ ] 明确旧 `RawEventStore` 的现有能力清单，标记哪些能力必须保留：
  基础写入、查询、timeline event 支持、计数、删除。
- [ ] 确认 L0 与 task runtime 的交互边界：
  `ChatTaskAgent`、`TaskOrchestrator`、`PromptContextAssembler` 各自负责什么。
- [ ] 决定本阶段是否先做“单库伪分片”再抽象分片路由。
  建议先做分片接口 + 单库实现，避免一开始把复杂度拉满。
- [ ] 先补三类测试：
  L0 session/checkpoint、L1 policy fields、`l0_only` 事件不落 L1。
- [ ] 明确需要更新的 bootstrap 初始化顺序，防止 task agent 启动时拿不到 L0/L1。
- [ ] 预备验证命令：
  `cd backend && pytest tests/memory/test_l0_working_memory.py tests/memory/test_l1_event_store.py tests/memory/test_memory_event_contracts.py -v`

### Phase 2 开工清单: L2 结构化认知

- [ ] 回读设计文档第 7 节，确认 `knowledge_graph`、`tom_trait_assertions`、`tom_snapshots` 三层结构。
- [ ] 先冻结一版最小 ontology：
  支持哪些 `subject_type`、`object_type`、`predicate`，不要在实现过程中边写边发散。
- [ ] 明确不同 source 的 ToM 深度映射规则：
  chat/journal -> `defensive_psychology`
  group/public OCR -> `topology_only`
  runtime telemetry -> `none`
- [ ] 确认“强宣称验证”的最小规则先做哪几个：
  `>=3` 事件、`>24h` 时间跨度、反证降级。
- [ ] 先决定 snapshot 物化策略是同步更新还是后台任务更新。
  建议先同步写 assertion，异步物化 snapshot。
- [ ] 先补测试，覆盖：
  低置信度进入 assertion、跨事件升级、反证降级、群体内容禁止深层诊断。
- [ ] 预备验证命令：
  `cd backend && pytest tests/memory/test_l2_cognition_store.py -v`

### Phase 3 开工清单: L3 反思记忆

- [ ] 回读设计文档第 8 节，确认 `temporal`、`thematic`、`insight` 三类输出。
- [ ] 先确定本阶段最小可交付范围。
  建议顺序：
  `temporal` -> `thematic` -> `insight`
- [ ] 确认摘要输入过滤条件已经在 L1 contract 中可直接判断：
  `cognition_eligible`、`memory_domain`、`retention_class`
- [ ] 确认 permanent 事件的压缩策略：
  可摘要，不删除原文。
- [ ] 决定本阶段是否直接启用 summary 向量化。
  建议可以一起做，因为 schema 已经预留。
- [ ] 先补测试，覆盖：
  runtime telemetry 不进入摘要、summary 可回溯 source events、permanent event 不删。
- [ ] 预备验证命令：
  `cd backend && pytest tests/memory/test_l3_summary_store.py -v`

### Phase 4 开工清单: L4 程序性记忆

- [ ] 回读设计文档第 9 节，确认 L4 的对象是“如何做”，不是普通统计表。
- [ ] 先列出本阶段支持的 skill identity 粒度：
  tool、api、workflow、strategy 哪些本期实现。
- [ ] 冻结熔断器最小状态机：
  `closed -> open -> half_open -> closed`
- [ ] 明确哪些事件会驱动 L4 更新：
  `TASK_COMPLETED`、`TASK_FAILED`、关键 tool 调用结果、策略变更事件。
- [ ] 确认 prompt/执行链路在本阶段还不消费 L4，只负责正确沉淀。
- [ ] 先补测试，覆盖：
  成功率累计、连续失败开熔断、恢复路径、模板回收。
- [ ] 预备验证命令：
  `cd backend && pytest tests/memory/test_l4_procedural_memory.py -v`

### Phase 5 开工清单: 检索与 Prompt 集成

- [ ] 回读设计文档第 10 节，确认五种 query mode：
  `detail`、`summary`、`experience`、`graph`、`strategy`
- [ ] 明确旧 `memory/query` 里哪些行为保留，哪些直接丢弃。
- [ ] 明确 prompt payload 新结构，并确认不会破坏现有 `preference_memory` 读取。
- [ ] 确认 ChatTaskAgent 当前有哪些入口会触发 memory retrieval：
  tool 调用、prompt 组装、memory query tool。
- [ ] 决定本阶段先做 retrieval service，再改 tool，再改 prompt，避免同时改三处导致问题难定位。
- [ ] 先补测试，覆盖：
  detail 命中 L0/L1、summary 命中 L3、experience 命中 L4、prompt 读取新 payload。
- [ ] 预备验证命令：
  `cd backend && pytest tests/memory/test_hybrid_retrieval.py tests/agent/test_chat_prompt_memory_payload.py -v`

### Phase 6 开工清单: API、维护与收尾

- [ ] 回读设计文档第 11、12、14 节，确认 retention policy、maintenance 归属、最终验收项。
- [ ] 列出所有对外暴露的 memory API，确认哪些响应模型要删除、哪些要重命名。
- [ ] 确认 housekeeping 任务归属 `MaintenanceDaemon`，不混入 `SchedulerService`。
- [ ] 明确旧模块删除顺序：
  先替换引用，再删文件，最后删测试。
- [ ] 先补 API 测试，覆盖：
  statistics、ToM assertions/snapshots、procedural skills、清理接口。
- [ ] 决定最终大验证范围：
  focused suite 必跑，`pytest` 全量作为加分验证。
- [ ] 预备验证命令：
  `cd backend && pytest tests/api/test_memory_api.py -v`

### 阶段切换通用检查

- [ ] 当前阶段对应测试已通过
- [ ] 当前阶段文档术语已同步
- [ ] 当前阶段改动已单独 commit
- [ ] 下一阶段不会依赖未提交的临时改动
- [ ] `git status --short` 已确认没有把无关文件带进来

---

## Chunk 1: Foundations, L0, and L1

### Task 1: Standardize memory event contracts and config

**Files:**
- Create: `backend/src/magi/memory/event_contracts.py`
- Modify: `backend/src/magi/config/models.py`
- Modify: `backend/src/magi/memory/integration.py`
- Test: `backend/tests/memory/test_memory_event_contracts.py`

- [ ] **Step 1: Write the failing tests for normalized memory events**

```python
def test_normalized_memory_event_requires_domain_and_ingest_target():
    ...

def test_runtime_progress_event_defaults_to_l0_only():
    ...
```

- [ ] **Step 2: Run the focused test file**

Run: `cd backend && pytest tests/memory/test_memory_event_contracts.py -v`
Expected: FAIL because the new event contract module does not exist yet.

- [ ] **Step 3: Implement `MemoryEvent` and normalization helpers**

Required behavior:

1. Define `memory_domain`, `ingest_target`, `cognition_eligible`, `tom_depth`, `retention_class`.
2. Add helper constructors or normalization functions for:
   - user-authored content
   - external activity
   - runtime telemetry
3. Encode the routing defaults from `memory-system-design.md`.

- [ ] **Step 4: Add config fields**

Add config support in `backend/src/magi/config/models.py` for:

1. layer enable flags
2. L0 checkpoint settings
3. LLM extraction toggles
4. retention policy toggles
5. runtime replay override for `l0_only` events

- [ ] **Step 5: Re-run tests**

Run: `cd backend && pytest tests/memory/test_memory_event_contracts.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/memory/event_contracts.py backend/src/magi/config/models.py backend/src/magi/memory/integration.py backend/tests/memory/test_memory_event_contracts.py
git commit -m "feat: add memory event contracts"
```

### Task 2: Implement L0 working memory with checkpoint support

**Files:**
- Create: `backend/src/magi/memory/l0_working_memory.py`
- Modify: `backend/src/magi/bootstrap/backend.py`
- Modify: `backend/src/magi/memory/__init__.py`
- Test: `backend/tests/memory/test_l0_working_memory.py`

- [ ] **Step 1: Write failing tests for session, goal stack, and checkpoint restore**

```python
async def test_l0_restores_session_from_checkpoint():
    ...

async def test_l0_can_store_temporary_tactics():
    ...
```

- [ ] **Step 2: Run the focused test file**

Run: `cd backend && pytest tests/memory/test_l0_working_memory.py -v`
Expected: FAIL because the store does not exist.

- [ ] **Step 3: Implement the L0 store**

Required capabilities:

1. in-memory primary state
2. SQLite checkpoint tables
3. session lifecycle
4. goal stack CRUD
5. active entity upsert/read
6. temporary tactic upsert/read/expiry
7. restore on restart

- [ ] **Step 4: Wire L0 into runtime bootstrap and unified memory entrypoint**

Required wiring:

1. initialize L0 before task agents
2. expose L0 through the unified memory facade
3. register shutdown checkpoint flush

- [ ] **Step 5: Re-run tests**

Run: `cd backend && pytest tests/memory/test_l0_working_memory.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/memory/l0_working_memory.py backend/src/magi/bootstrap/backend.py backend/src/magi/memory/__init__.py backend/tests/memory/test_l0_working_memory.py
git commit -m "feat: add l0 working memory"
```

### Task 3: Replace raw event store with the new L1 event store

**Files:**
- Create: `backend/src/magi/memory/l1_event_store.py`
- Modify: `backend/src/magi/memory/integration.py`
- Modify: `backend/src/magi/memory/__init__.py`
- Remove: `backend/src/magi/memory/raw_event_store.py`
- Test: `backend/tests/memory/test_l1_event_store.py`

- [ ] **Step 1: Write failing tests for L1 insert/query behavior**

```python
async def test_l1_persists_memory_event_with_policy_fields():
    ...

async def test_l1_filters_by_domain_and_ingest_target():
    ...
```

- [ ] **Step 2: Run the focused test file**

Run: `cd backend && pytest tests/memory/test_l1_event_store.py -v`
Expected: FAIL

- [ ] **Step 3: Implement L1 schema and repository**

Required capabilities:

1. normalized event insert
2. domain/source/session/user/task filtering
3. `l0_only` event suppression from L1
4. soft delete support
5. vector columns and retry status fields
6. time-slice path routing abstraction

- [ ] **Step 4: Rewrite integration entry flow**

Required behavior:

1. runtime events enter normalizer first
2. `l0_only` events update L0 but do not write L1
3. `l0_and_l1` events update both
4. async fan-out starts only after L1 write succeeds

- [ ] **Step 5: Re-run tests**

Run: `cd backend && pytest tests/memory/test_l1_event_store.py tests/memory/test_memory_event_contracts.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/memory/l1_event_store.py backend/src/magi/memory/integration.py backend/src/magi/memory/__init__.py backend/tests/memory/test_l1_event_store.py
git rm backend/src/magi/memory/raw_event_store.py
git commit -m "feat: replace raw store with l1 event store"
```

---

## Chunk 2: L2 Cognition and Defensive ToM

### Task 4: Implement unified L2 cognition store

**Files:**
- Create: `backend/src/magi/memory/l2_cognition_store.py`
- Remove: `backend/src/magi/memory/l2_event_relations.py`
- Remove: `backend/src/magi/memory/l2_user_graph.py`
- Modify: `backend/src/magi/memory/__init__.py`
- Test: `backend/tests/memory/test_l2_cognition_store.py`

- [ ] **Step 1: Write failing tests for graph triples and ToM assertions**

```python
def test_l2_upserts_knowledge_graph_triple_with_evidence():
    ...

def test_l2_tom_assertion_starts_low_confidence():
    ...
```

- [ ] **Step 2: Run the focused test file**

Run: `cd backend && pytest tests/memory/test_l2_cognition_store.py -v`
Expected: FAIL

- [ ] **Step 3: Implement the L2 schema**

Required tables and behaviors:

1. `knowledge_graph`
2. `tom_trait_assertions`
3. `tom_snapshots`
4. conflict and deprecation helpers
5. validation-state updates
6. evidence backtrace storage

- [ ] **Step 4: Replace unified memory references**

Update the unified memory facade so callers use the new cognition store instead of the old relation/user graph split.

- [ ] **Step 5: Re-run tests**

Run: `cd backend && pytest tests/memory/test_l2_cognition_store.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/memory/l2_cognition_store.py backend/src/magi/memory/__init__.py backend/tests/memory/test_l2_cognition_store.py
git rm backend/src/magi/memory/l2_event_relations.py backend/src/magi/memory/l2_user_graph.py
git commit -m "feat: add l2 cognition store"
```

### Task 5: Add L2 extraction pipeline and strong-claim validation

**Files:**
- Create: `backend/src/magi/memory/l2_extractors.py`
- Modify: `backend/src/magi/memory/integration.py`
- Test: `backend/tests/memory/test_l2_cognition_store.py`

- [ ] **Step 1: Add failing tests for source-specific ToM depth**

```python
async def test_chat_event_can_generate_defensive_psychology_assertion():
    ...

async def test_group_chat_event_only_generates_topology_assertions():
    ...
```

- [ ] **Step 2: Run the targeted tests**

Run: `cd backend && pytest tests/memory/test_l2_cognition_store.py -k \"psychology or topology\" -v`
Expected: FAIL

- [ ] **Step 3: Implement extractor pipeline**

Required behavior:

1. map events to `tom_depth`
2. call LLM extractors for graph and ToM separately
3. seed all subjective assertions at low confidence
4. upgrade to stable only after evidence thresholds are met
5. downgrade on contradictory evidence

- [ ] **Step 4: Re-run tests**

Run: `cd backend && pytest tests/memory/test_l2_cognition_store.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l2_extractors.py backend/src/magi/memory/integration.py backend/tests/memory/test_l2_cognition_store.py
git commit -m "feat: add defensive tom extraction"
```

---

## Chunk 3: L3 Reflection Memory and L4 Procedural Memory

### Task 6: Rebuild summaries as L3 reflection memory

**Files:**
- Create: `backend/src/magi/memory/l3_summary_store.py`
- Create: `backend/src/magi/memory/l3_generators.py`
- Remove: `backend/src/magi/memory/l4_summaries.py`
- Modify: `backend/src/magi/memory/integration.py`
- Modify: `backend/src/magi/memory/__init__.py`
- Test: `backend/tests/memory/test_l3_summary_store.py`

- [ ] **Step 1: Write failing tests for temporal/thematic summary generation**

```python
def test_temporal_summary_excludes_runtime_telemetry():
    ...

def test_thematic_summary_keeps_source_event_backtrace():
    ...
```

- [ ] **Step 2: Run the focused test file**

Run: `cd backend && pytest tests/memory/test_l3_summary_store.py -v`
Expected: FAIL

- [ ] **Step 3: Implement the L3 store and generators**

Required capabilities:

1. temporal summary generation
2. thematic summary generation
3. insight storage
4. source-event backtrace
5. vector support on summary rows
6. permanent-event no-delete guarantee

- [ ] **Step 4: Update integration hooks**

Make summary generation consume only `cognition_eligible=true` and non-disposable events.

- [ ] **Step 5: Re-run tests**

Run: `cd backend && pytest tests/memory/test_l3_summary_store.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/memory/l3_summary_store.py backend/src/magi/memory/l3_generators.py backend/src/magi/memory/integration.py backend/src/magi/memory/__init__.py backend/tests/memory/test_l3_summary_store.py
git rm backend/src/magi/memory/l4_summaries.py
git commit -m "feat: add l3 reflection memory"
```

### Task 7: Replace capability memory with L4 procedural memory

**Files:**
- Create: `backend/src/magi/memory/l4_procedural_memory.py`
- Remove: `backend/src/magi/memory/l5_capabilities.py`
- Modify: `backend/src/magi/memory/integration.py`
- Modify: `backend/src/magi/memory/__init__.py`
- Test: `backend/tests/memory/test_l4_procedural_memory.py`

- [ ] **Step 1: Write failing tests for procedural skill learning**

```python
def test_repeated_failures_open_circuit_breaker():
    ...

def test_success_history_updates_proficiency_and_template():
    ...
```

- [ ] **Step 2: Run the focused test file**

Run: `cd backend && pytest tests/memory/test_l4_procedural_memory.py -v`
Expected: FAIL

- [ ] **Step 3: Implement the L4 store**

Required capabilities:

1. skill upsert by tool/workflow/strategy identity
2. proficiency and success-rate tracking
3. circuit breaker state transitions
4. context-affinity storage
5. optimized prompt/params storage
6. event evidence trace

- [ ] **Step 4: Re-run tests**

Run: `cd backend && pytest tests/memory/test_l4_procedural_memory.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l4_procedural_memory.py backend/src/magi/memory/integration.py backend/src/magi/memory/__init__.py backend/tests/memory/test_l4_procedural_memory.py
git rm backend/src/magi/memory/l5_capabilities.py
git commit -m "feat: add l4 procedural memory"
```

---

## Chunk 4: Retrieval, Prompt Wiring, API, and Cleanup

### Task 8: Replace legacy query service with hybrid retrieval

**Files:**
- Create: `backend/src/magi/memory/hybrid_retrieval/models.py`
- Create: `backend/src/magi/memory/hybrid_retrieval/router.py`
- Create: `backend/src/magi/memory/hybrid_retrieval/service.py`
- Create: `backend/src/magi/memory/hybrid_retrieval/__init__.py`
- Remove: `backend/src/magi/memory/query/`
- Modify: `backend/src/magi/tools/memory_query.py`
- Test: `backend/tests/memory/test_hybrid_retrieval.py`

- [ ] **Step 1: Write failing tests for detail/summary/experience routing**

```python
async def test_detail_query_prefers_l1_and_l0():
    ...

async def test_experience_query_prefers_l4():
    ...
```

- [ ] **Step 2: Run the focused test file**

Run: `cd backend && pytest tests/memory/test_hybrid_retrieval.py -v`
Expected: FAIL

- [ ] **Step 3: Implement hybrid retrieval contracts and service**

Required behavior:

1. detail mode -> L0/L1 first
2. summary mode -> L3 first
3. experience/strategy mode -> L4 first
4. graph mode -> L2 first
5. raw evidence backtrace in response metadata

- [ ] **Step 4: Update `memory_query` tool**

Make the tool consume the new service and return layer-aware payloads.

- [ ] **Step 5: Re-run tests**

Run: `cd backend && pytest tests/memory/test_hybrid_retrieval.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/memory/hybrid_retrieval backend/src/magi/tools/memory_query.py backend/tests/memory/test_hybrid_retrieval.py
git rm -r backend/src/magi/memory/query
git commit -m "feat: add hybrid memory retrieval"
```

### Task 9: Wire new memory payloads into prompt assembly

**Files:**
- Modify: `backend/src/magi/memory/prompt_context_assembler.py`
- Modify: `backend/src/magi/agent/task_agents/chat/prompt_service.py`
- Test: `backend/tests/agent/test_chat_prompt_memory_payload.py`

- [ ] **Step 1: Write failing tests for prompt payload composition**

```python
async def test_prompt_context_includes_l0_l2_l3_l4_payloads():
    ...
```

- [ ] **Step 2: Run the focused test file**

Run: `cd backend && pytest tests/agent/test_chat_prompt_memory_payload.py -v`
Expected: FAIL

- [ ] **Step 3: Implement new prompt payload mapping**

Required behavior:

1. L0 workbench enters prompt
2. L2 entity cards and relationship cards enter prompt
3. L3 reflections enter prompt
4. L4 procedural guidance enters prompt
5. legacy `preference_memory` keeps working

- [ ] **Step 4: Re-run tests**

Run: `cd backend && pytest tests/agent/test_chat_prompt_memory_payload.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/prompt_context_assembler.py backend/src/magi/agent/task_agents/chat/prompt_service.py backend/tests/agent/test_chat_prompt_memory_payload.py
git commit -m "feat: wire memory payload into prompts"
```

### Task 10: Replace memory API and housekeeping hooks

**Files:**
- Modify: `backend/src/magi/api/routers/memory.py`
- Modify: `backend/src/magi/bootstrap/backend.py`
- Modify: maintenance daemon related runtime files
- Test: `backend/tests/api/test_memory_api.py`

- [ ] **Step 1: Add failing tests for new memory API responses**

```python
def test_memory_statistics_api_returns_l0_l4_sections():
    ...
```

- [ ] **Step 2: Run the focused API tests**

Run: `cd backend && pytest tests/api/test_memory_api.py -v`
Expected: FAIL

- [ ] **Step 3: Update API and daemon wiring**

Required behavior:

1. expose new layer statistics
2. expose ToM assertions / snapshots
3. expose procedural skills
4. schedule compression and cleanup in maintenance daemon
5. keep scheduler reserved for business jobs

- [ ] **Step 4: Run verification suite for the new memory stack**

Run:

```bash
cd backend
pytest tests/memory/test_memory_event_contracts.py \
       tests/memory/test_l0_working_memory.py \
       tests/memory/test_l1_event_store.py \
       tests/memory/test_l2_cognition_store.py \
       tests/memory/test_l3_summary_store.py \
       tests/memory/test_l4_procedural_memory.py \
       tests/memory/test_hybrid_retrieval.py \
       tests/agent/test_chat_prompt_memory_payload.py \
       tests/api/test_memory_api.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/api/routers/memory.py backend/src/magi/bootstrap/backend.py backend/tests/api/test_memory_api.py
git commit -m "feat: finish memory runtime integration"
```

---

## Final Cleanup Checklist

- [ ] Remove dead imports from `backend/src/magi/memory/__init__.py`
- [ ] Remove old memory layer references from bootstrap logs and API labels
- [ ] Re-read `backend/docs/memory-system-design.md` and update any terminology drift
- [ ] Run `cd backend && pytest` if the focused suite passes and time allows
- [ ] Commit any remaining doc-sync changes separately

## Definition of Done

The memory system rewrite is complete when all of the following are true:

1. All runtime memory writes go through the new event contract.
2. `l0_only` runtime events no longer flood L1.
3. L2 graph and ToM run through one unified cognition store.
4. L3 summaries are reflection-oriented and evidence-traceable.
5. L4 procedural memory can influence future execution choices.
6. Prompt assembly reads L0/L2/L3/L4 payloads.
7. The legacy query layer is removed.
8. Memory API reflects the new architecture.
9. Focused test suite passes.
