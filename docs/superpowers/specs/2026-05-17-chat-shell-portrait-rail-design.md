# Chat Shell — Persona Portrait Rail (P1.C)

Status: Design — pending user review
Author: brainstorming session 2026-05-17
Supersedes: section P1.1 "MemoryCompanionRail" in
`docs/dev/chat-shell-redesign-p1-plan.md` (the rail content is replaced; the
column-layout and responsive policy are inherited)

## 1. 背景

P0 + P1.A/B 之后 chat shell 已有：

- 顶部今日带 (P0.1) — sensor today 聚合数字
- 头像生命周期 (P0.2) — chat-avatar-shell idle/streaming/...
- 气泡内召回行 (P0.3 + 5月改造) — 这一句话用了什么记忆 (kind chips)
- 左侧 PersonaHeader (P1.A) — 持续在场的 persona 身份
- 召回 echo 过滤修复 — 用户当前 message 不再被当作记忆回灌

仍然没解决的：**主页面缺一个"AI 关于你的视角"的常驻面板**。`/memory`
路由是全局原始浏览；气泡 chip 是这一句话的局部；都没有"AI 现在怎么看你"
这个语义层面的展示。

原 P1.C 方案（本会话累积召回 + 相关时间线 + 此刻传感器）评审被否：

- 段 1 与气泡 chip 重复 + L1 事件流水账价值低
- 段 2 与 `/timeline` 路由重复，用户比 AI 更清楚自己做了什么
- 段 3 与顶部今日带重复

## 2. 设计主张

把 rail 重新定位为 **"AI 对你的画像板"** —— 不展示原始记忆流水，而是
**戴着当前 persona 的眼镜，对 L2/L3/L4 记忆做主题相关的人格化解读**。

核心区别：

| 维度 | L3 反思（已有） | Portrait（本设计） |
|------|----------------|--------------------|
| 视角 | 客观、事实级 | 戴着当前 persona 的眼镜 |
| 内容例 | 「用户对失败者表现出同理心」 | "七号"视角："你最近老聊罗永浩这种'落寞英雄'——是不是又开始想自己那些没做成的事了？" |
| 生成时机 | 离线批量，persona-agnostic | 在线触发，绑定 active persona |
| 切 persona 重算 | 不需要 | **强制刷新**（视角变了） |

价值：

- 这是**只有 AI 才知道、用户希望看见**的内容（个性画像 + 当前对话相关）
- 切换 persona 时整个 rail 内容**质感变化** = 让人格选择有了对话之外的实在意义
- 不与 `/memory`、`/timeline`、气泡 chip 重复，语义正交

## 3. 范围

### IN

- 新增 backend endpoint：`GET /api/memory/portrait?session_id={id}`
- 新增 topic 提取服务：从 session 最近 message 提炼当前主题
- 跨层检索投影：L3 reflection + L2 assertion + L2 relationship + L4 procedure
  按 topic 过滤后聚合
- Persona-lens 渲染 LLM 调用：用 active persona 的 `identity_core` + `idiolect`
  把 raw 片段渲染为 3-5 条"persona 视角观察"
- 后端结果缓存：`(session_id, topic_hash, persona_id)` 为 key，TTL 5 分钟
- Persona JSON 加 `interim_lines.portrait_cold_start: List[str]` 字段（cold-start 文案）
- 前端新组件 `MemoryPortraitRail` + 数据 hook
- MainLayout 新增第三栏（320px 常驻 / < 1280px 浮层）
- Empty state 走 persona-个性化文案
- 单测：topic 提取、cross-layer 聚合、persona-lens 渲染、empty state 分支

### OUT（推迟到 P2 或更晚）

- "持久化 session topic + 实时跟随对话主题"——本期改成"每 N 轮/切换时拉一次"，
  不做 streaming
- 卡片点击跳转到 raw memory 详情页（先做卡片本身，跳转留 P2）
- Portrait 写回 L3 或独立持久化——本期只做 on-demand 渲染 + in-memory 缓存
- LLM 渲染失败时的 fallback portrait 模板——本期失败就回 empty state

## 4. 用户视角的产品行为

### 4.1 卡片视觉（每条）

```
┌────────────────────────────────────────┐
│ 💭 反思                                  │  ← kind 徽标 (反思/事实/关系/经验)
│                                          │
│ 你最近老聊"落寞英雄"——是不是又开始想       │
│ 自己那些没做成的事了？                      │  ← persona 视角文本
│                                          │
│ 基于 5 条反思 · 上周以来                   │  ← 元信息（点击展开 raw 来源）
└────────────────────────────────────────┘
```

- 一屏放 3-5 条卡片，不分页不滚动
- 卡片不可独立排序——后端按"相关性 + 新近度"排好序

### 4.2 刷新触发

| 事件 | 行为 |
|------|------|
| 进入 chat 页 | 拉一次 |
| 切换 session | 拉一次 |
| 切换 active persona | **强制刷新**（绕过缓存） |
| 距离上次 ≥ 5 分钟且新发了 user message | 拉一次 |
| 每条新 message | **不刷**（成本+噪音） |
| Tab 切到后台 | 暂停 polling |

### 4.3 Empty / Cold-start

cold-start 触发条件：portrait endpoint 返回空（无 L2/L3/L4 命中 topic）。

显示：

```
┌──────────────────────────────────┐
│ 🪞 七号还在认识你                  │
│ 跟我多聊聊，我会慢慢记下你是怎样的人 │
└──────────────────────────────────┘
```

文案来源：active persona 的 `interim_lines.portrait_cold_start` 列表里随机选一条。
列表为空时使用通用 fallback：`{persona.name} 还在认识你 · 跟我多聊聊，我会慢慢记下你是怎样的人`。

不显示骨架屏空卡片——避免"看上去像坏了"。

### 4.4 响应式

| 视口宽 | rail 形态 |
|--------|-----------|
| ≥ 1280px | 常驻第三栏 320px 宽 |
| < 1280px | 收起为浮层，由活动栏右下一个新按钮触发弹出（layered on top） |
| ≥ 1920px | 仍然 320px，不拉宽 |

### 4.5 与其他元素的关系（重申，避免实施时迷失）

| 元素 | 它做什么 | 与 portrait 区别 |
|------|----------|-------------------|
| 顶部今日带 | sensor today 聚合数字 | portrait 是语义层面，不是数字 |
| 气泡内召回行 | 这一句话用了什么记忆 | portrait 是整段对话的 persona 视角观察 |
| `/memory` 路由 | 全局 raw 浏览 | portrait 是 topic-filtered + persona-rendered |
| `/timeline` 路由 | 时间线事件流 | portrait 不展示事件流 |

## 5. 数据流

```
chat shell 触发器 (进入 / 切 session / 切 persona / 5 分钟后新 message)
    ↓
useMemoryPortrait hook
    ↓
GET /api/memory/portrait?session_id=X
    ↓
PortraitService (新模块):
    ① 取 session 最近 N=10 条 message (复用 messagesApi)
    ② 命中缓存？ → 直接返回
    ③ TopicExtractor 服务（新）：
       - input: 最近 N 条 message + 当前时间
       - LLM scenario: MEMORY_SUMMARIZER (fallback CORE)
       - output: { topic: str, entities: [str] }
    ④ 跨层 raw 检索（复用现有投影函数）：
       - L3: reflection_store.query_by_topics(topic + entities)
       - L2 assertions: assertion_store.query_by_subject_or_entities(self, entities)
       - L2 relationships: relationship_store.query_by_entities(entities)
       - L4: procedure_store.query_by_keywords(entities + topic)
       - 上限：合计 ≤ 15 条 raw 片段送入下一步
    ⑤ PersonaLensRenderer 服务（新）：
       - input: { active persona config, raw 片段 list, recent message excerpt }
       - LLM scenario: MEMORY_SUMMARIZER
       - prompt: 系统提示用 persona.identity_core + idiolect; 用户区列出 raw 片段
       - output: { observations: [{kind, text, basis: [raw_id...]}] }
       - target: 3-5 条 observation
    ⑥ 写缓存 (session_id, topic_hash, persona_id) → 5 分钟
    ⑦ 返回 PortraitPayload
    ↓
frontend rail 渲染
```

## 6. 数据契约

### 请求

```http
GET /api/memory/portrait?session_id={uuid}&force=false
```

`force=true` 用于 persona 切换时绕过缓存。

### 响应

```ts
type PortraitPayload = {
  session_id: string;
  persona_id: string;
  topic: string;            // 提取出的主题，便于前端展示/调试
  generated_at: number;     // unix seconds
  observations: PortraitObservation[];
  is_cold_start: boolean;   // 后端给前端的明确信号
  cold_start_line?: string; // is_cold_start=true 时由后端选好一条
};

type PortraitObservation = {
  kind: 'reflection' | 'assertion' | 'relationship' | 'procedure';
  text: string;             // persona 视角语句
  basis_count: number;      // "基于 N 条" 元信息
  basis_summary: string;    // 例 "5 条反思 · 上周以来"
  basis_refs?: string[];    // raw memory ids (供 P2 跳转用，本期可空)
};
```

### Persona JSON 字段增量

只在 `interim_lines` dict 里加一个 key，不动 schema：

```json
{
  "interim_lines": {
    "portrait_cold_start": [
      "我还在认识你呢，跟我多聊聊。",
      "你这边的轮廓还没浮出来。再多说说。"
    ]
  }
}
```

为内置 persona（如"七号"）补充 2-3 条。

## 7. 后端文件清单

### 新增

| 路径 | 职责 |
|------|------|
| `backend/src/magi/memory/portrait/service.py` | `PortraitService` 主流程 |
| `backend/src/magi/memory/portrait/topic_extractor.py` | `TopicExtractor` LLM 调用 + parsing |
| `backend/src/magi/memory/portrait/persona_lens_renderer.py` | `PersonaLensRenderer` LLM 调用 + prompt |
| `backend/src/magi/memory/portrait/cache.py` | in-memory LRU 缓存 + TTL |
| `backend/src/magi/memory/portrait/contracts.py` | dataclass: `PortraitPayload`, `PortraitObservation`, `PortraitRequest` |
| `backend/src/magi/api/memory_portrait_routes.py` | FastAPI 路由 `/api/memory/portrait` |
| `backend/tests/memory/portrait/test_topic_extractor.py` | 单测 |
| `backend/tests/memory/portrait/test_persona_lens_renderer.py` | 单测 |
| `backend/tests/memory/portrait/test_service.py` | 集成测试，含 cold-start |

### 修改

| 路径 | 改动 |
|------|------|
| `backend/src/magi/api/__init__.py` 或 server bootstrap | 注册 portrait routes |
| `backend/src/magi/personality/loader.py` | 兼容性：`interim_lines.portrait_cold_start` 是可选 key，无需 schema 改动；只需在 builtin persona seed JSON 补默认值 |
| builtin persona seed 文件（七号等） | 补 `interim_lines.portrait_cold_start: [...]` |

## 8. 前端文件清单

### 新增

| 路径 | 职责 |
|------|------|
| `frontend/src/components/chat/MemoryPortraitRail.tsx` | rail 容器（3rd column） |
| `frontend/src/components/chat/portrait/PortraitCard.tsx` | 单卡片组件 |
| `frontend/src/components/chat/portrait/PortraitColdStart.tsx` | cold-start 空态 |
| `frontend/src/components/chat/portrait/PortraitFloater.tsx` | < 1280px 浮层版 |
| `frontend/src/hooks/useMemoryPortrait.ts` | 拉数据 + 缓存 + 刷新触发 |
| `frontend/src/api/modules/memoryPortrait.ts` | api wrapper |

### 修改

| 路径 | 改动 |
|------|------|
| `frontend/src/components/layout/MainLayout.tsx:93` | grid 改为 `grid-cols-[auto_minmax(0,1fr)_auto]`，第三栏宽度由 store 控制 |
| `frontend/src/stores/chat-shell.ts` | 加 `portraitRailOpen: boolean` + `togglePortraitRail()`；窗口宽度 < 1280 时自动改为浮层 |
| `frontend/src/components/layout/Sidebar.tsx` | 活动栏右下加一个折叠 rail 的图标按钮（与 P1.A 的 Plus 一样 `app-region: no-drag`） |
| `frontend/src/i18n/locales/{zh-CN,en}/app.json` | `chat.portrait.*` 多 key |

## 9. 实施验收（acceptance）

- [ ] 默认进入 chat 页 < 1.5s 内 rail 出现内容（或 cold-start）
- [ ] 切换 persona 后 rail 内容**质感明显不同**（不只是名字换了）
- [ ] 切换 session 时 rail 内容刷新
- [ ] 5 分钟内连续发 5 条 message，rail 只刷新 1 次（缓存命中）
- [ ] 距上次 ≥ 5 分钟且发新 message，rail 刷新
- [ ] 新用户首次 cold-start 走 persona 的 `portrait_cold_start` 文案
- [ ] LLM 调用失败 (topic / lens 任何一步) → 走 cold-start，**不报错卡死 UI**
- [ ] 窗口缩到 1280px 以下 → rail 变浮层，主聊天区不被挤压
- [ ] 整体新增 LLM 调用频率 ≤ 12 次/小时（5 分钟 cache + 单次最多 2 个 LLM call = topic + lens）

## 10. 取舍 / 风险

- **风险 1**：新用户头几天 L2/L3 数据稀疏，rail 长时间 cold-start。
  对策：cold-start 文案设计要轻松（不显得空），并且**用户首次见到 portrait
  本来就是冷启动**，不算 bug
- **风险 2**：topic 提取错误，导致 portrait 跑偏。
  对策：response 里返回 `topic` 字段，前端调试可见；rail 卡片元信息里
  显式标 topic（开发模式）以便定位
- **风险 3**：LLM 渲染产出过于"人格化"，看起来像 AI 在自说自话而非"关于你"。
  对策：prompt 强约束 `observations` 必须**以"你"为主语，引用 raw 片段
  作为依据**；写 prompt 时给反面示例
- **风险 4**：两次 LLM 调用累积延迟。
  对策：MEMORY_SUMMARIZER 走小模型；并且 rail 不阻塞主聊天 UI（独立加载）
- **风险 5**：缓存命中错配——同 session 不同 persona 切换时缓存 key 必须含
  persona_id，否则会看到旧 persona 的视角

## 11. 不会做的事（明确写下，避免反复纠结）

- 不做 streaming 跟随每条 message 的 portrait 更新
- 不做 portrait 写回 L3 或独立持久化
- 不做卡片"赞/踩"反馈回 RLHF
- 不做 portrait 编辑（用户改 AI 对自己的看法）

## 12. 完成后

- 把 portrait endpoint 数据契约写入 `docs/memory-system-design.md` 的"对外暴露"小节
- 把 persona JSON 的 `interim_lines.portrait_cold_start` 写入 `docs/persona-runtime-architecture.md`
- 删除原 `docs/dev/chat-shell-redesign-p1-plan.md` P1.1 段（已被本文取代）
- 删除本文（spec 是临时的，落地后入正式 docs）
