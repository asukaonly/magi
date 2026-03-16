# 分层架构对齐改造清单

> 范围: `backend/src/magi/`
> 对照基线: [Layered Agent Architecture](/Users/asuka/code/magi/docs/layered-agent-architecture.md)
> 分析日期: 2026-03-16
> 当前目标: 先收敛架构问题、影响面、优先级、决策状态与改造顺序，不展开具体实现细节

---

## 1. 结论摘要

当前代码已经开始向目标分层靠拢，但还存在几类明显的架构不一致：

- 运行时装配仍然高度集中，`runtime/runtime_modules.py` 仍是跨层总控中心
- 调度器虽然已有 contributor 机制，但注册动作仍由中心模块统一编排
- API 层和连接层仍有若干直接拿领域对象、全局对象、runtime service 的旁路
- `tools / skills / actions / context / timeline` 的边界已经在概念上明确，但在代码里仍有多处旧路径并存
- 仓库中仍保留一整套旧 runtime 心智模型，持续制造认知噪音和实现分叉

本清单的目标不是列所有代码问题，而是只聚焦“和目标分层设计不一致”的改造项。

---

## 2. 已确认决策

以下架构决策已经明确，不再重复讨论：

- `runtime/runtime_modules.py` 继续做大拆分，不保留为长期中心装配枢纽
- `L13 External Services` 与 `L14 Connection and Transport` 现在就做真实目录与归属迁移
- 旧 runtime / loop / processing 路径直接删除，不保留兼容逻辑
- `action` 相关命名向 `action emitter` / action-oriented terminology 收敛，不再沿用含糊的 executor 语义
- 不增加兼容代码路径；改造以当前目标架构为准

当前没有新的架构级阻塞决策必须先拍板。

---

## 3. 优先级定义

- `P0`
  不改会持续阻碍其他架构改造，或会导致新代码继续沿错误边界扩散
- `P1`
  核心分层不一致，应该在主干改造阶段完成
- `P2`
  非主阻塞项，但不处理会长期造成认知噪音、命名歧义或多套路径并存

---

## 4. 改造项清单

### A1. 拆解 `runtime/runtime_modules.py` 中心装配枢纽

- 优先级: `P0`
- 决策状态: `已确认，必须改`
- 当前问题:
  - [runtime_modules.py](/Users/asuka/code/magi/backend/src/magi/runtime/runtime_modules.py) 仍直接 import 几乎所有核心层
  - `RuntimeBootstrapState` 仍是跨层实例总表
  - 各模块虽有分层命名，但真实装配关系仍依赖一个中心文件知道全部细节
- 与设计冲突:
  - 违反“不要再次塌成单一 runtime module”的目标
  - 使层边界停留在命名层，而不是结构层
- 影响面:
  - `runtime/`
  - `agent/`
  - `scheduler/`
  - `timeline/`
  - `context/`
  - `personality/`
  - `core/container.py`
- 不改的后果:
  - 新增层能力仍会优先塞回中心装配文件
  - 后续的调度、连接层迁移、DI 清理都会被这个中心状态对象反复牵制
- 依赖关系:
  - 应作为第一批主改造项之一启动
  - 会影响 A2、A3、A4、A8

### A2. 让调度器退化为纯引擎，移除中心注册编排

- 优先级: `P0`
- 决策状态: `已确认，必须改`
- 当前问题:
  - [runtime_modules.py](/Users/asuka/code/magi/backend/src/magi/runtime/runtime_modules.py#L467) 中的 `SchedulerModule` 仍负责组装 timeline、agent、action 三类 contributor
  - 仍通过 `get_sensor_registry()`、`get_plugin_manager()`、`get_action_registry()` 等全局 getter 抓依赖
  - [scheduler/bootstrap.py](/Users/asuka/code/magi/backend/src/magi/scheduler/bootstrap.py) 仍保留 legacy bootstrap
- 与设计冲突:
  - 调度引擎属于 `L1`
  - 具体注册和调度策略应归属于 timeline / agent / action 各自层
- 影响面:
  - `scheduler/`
  - `timeline/`
  - `agent/`
  - `core/runtime/` 中 action scheduling 相关逻辑
  - `runtime/`
- 不改的后果:
  - scheduler 继续成为业务编排中心
  - contributor 机制名义存在，实质仍由中心模块驱动
- 依赖关系:
  - 与 A1 强耦合
  - 在删除 legacy runtime 之前应完成主路径切换

### A3. 真实拆分 `L13 API` 与 `L14 Connection / Transport`

- 优先级: `P0`
- 决策状态: `已确认，必须改`
- 当前问题:
  - WebSocket router、connection manager、bridge 仍主要挂在 `api/` 下
  - API 层仍承担部分连接态逻辑和 runtime bridge 访问
- 与设计冲突:
  - `L13` 应是应用服务与接口语义层
  - `L14` 应是 HTTP / WebSocket 连接与传输层
- 影响面:
  - `api/websocket/`
  - `api/connection_manager.py`
  - `api/websocket_bridge_lifecycle.py`
  - `websocket/`
  - `backend_app.py`
  - `api/app.py`
- 不改的后果:
  - 目录结构继续误导实现者把“连接管理”和“应用服务”写进同一层
  - 后续消息推送、连接态鉴权、transport abstraction 都会继续打结
- 依赖关系:
  - 可与 A1 并行设计
  - 真正迁移时会受 A4、A8 的影响

### A4. 移除 API 层直接 new 领域对象 / 传感器 / runtime globals 的旁路

- 优先级: `P0`
- 决策状态: `已确认，必须改`
- 当前问题:
  - [others.py](/Users/asuka/code/magi/backend/src/magi/api/routers/others.py) 自己持有 `_other_memory`
  - [messages.py](/Users/asuka/code/magi/backend/src/magi/api/routers/messages.py) 自己持有 `_user_message_sensor`
  - 多处 API / bridge 通过 `runtime.services.*` 全局 accessor 取 message bus 或 skills
- 与设计冲突:
  - API 层不应自己拥有领域对象生命周期
  - 连接层和服务层应通过稳定 service contract 或 DI 获取依赖
- 影响面:
  - `api/routers/messages.py`
  - `api/routers/others.py`
  - `api/services/__init__.py`
  - `api/websocket_bridge_lifecycle.py`
  - `runtime/services/`
  - `core/container.py`
- 不改的后果:
  - 同一个能力会同时存在“runtime 创建”和“API 自建”两条来源
  - 生命周期、状态、缓存、测试替换都容易漂移
- 依赖关系:
  - 和 A3 一起推进收益最高
  - 也依赖 A8 对 runtime globals 的清理

### A5. 统一 skills 生命周期，移除重复初始化路径

- 优先级: `P1`
- 决策状态: `已确认，必须改`
- 当前问题:
  - runtime 已有共享 skills lifecycle
  - `ChatTaskAgent` 内又自行 new 一套 `SkillIndexer/SkillLoader/SkillExecutor`
- 与设计冲突:
  - `L7 Tools and Skills` 应有明确单一能力入口
  - agent runtime 应消费能力层，不应私自复制一套能力生命周期
- 影响面:
  - `runtime/services/skills.py`
  - `runtime/runtime_modules.py`
  - `agent/task_agents/chat_task_agent.py`
  - 可能波及 `tools/registry.py` 与 `skills/`
- 不改的后果:
  - skill 配置、索引、执行环境可能出现双份状态
  - 后续权限与缓存策略难以统一
- 依赖关系:
  - 应在 A1 之后尽快处理
  - 对 A7 上下文与工具边界收敛也有帮助

### A6. 把 `action` 语义从旧 executor 命名中抽离，收敛到 action emitter / action layer

- 优先级: `P1`
- 决策状态: `已确认，必须改`
- 当前问题:
  - `ActionExecutor` 这个名字容易与 worker executor、tool executor 混淆
  - action scheduling 逻辑也还留在 `core/runtime/`
- 与设计冲突:
  - 新文档已明确 `actions` 是 `L9` 的 outbound capability
  - 命名应反映“对外动作/副作用能力”，而不是泛化执行器
- 影响面:
  - `core/runtime/action_executor.py`
  - `core/runtime/action_scheduler_contrib.py`
  - `scheduler/handlers.py`
  - `runtime/runtime_modules.py`
  - 相关调用方、事件 source 命名、日志命名
- 不改的后果:
  - 概念边界虽在文档里明确，但代码里仍持续误导
- 依赖关系:
  - 可与 A2、A3 同期做
  - 若伴随目录迁移，建议一起完成

### A7. 把 context layer 真正收敛为 prompt/context 的唯一主出口

- 优先级: `P1`
- 决策状态: `已确认，必须改`
- 当前问题:
  - `ChatPromptService` 虽使用 `PromptContextAssembler`
  - 但仍自行直接拿 `UnifiedMemoryStore` 并构造 `HybridRetrievalService`
  - 说明“上下文召回策略”和“上下文组装”仍未完全放回 `L10`
- 与设计冲突:
  - `L10 Context Layer` 应是 prompt-context assembly 和 recall shaping 的主边界
- 影响面:
  - `agent/task_agents/chat/prompt_service.py`
  - `context/assembler.py`
  - `context/`
  - `memory/hybrid_retrieval/`
  - 可能波及 `Explore` 相关 prompt path
- 不改的后果:
  - agent 层会继续生长 prompt 拼装与 recall 逻辑
  - “上下文层”很容易再次沦为半成品中间层
- 依赖关系:
  - 与 A5 不是强依赖，但都属于能力层边界收敛

### A8. 删除 runtime globals / fallback accessor 路径，统一 DI 与显式依赖

- 优先级: `P1`
- 决策状态: `已确认，必须改`
- 当前问题:
  - `runtime/bootstrap.py` 仍有 `_runtime_state`、`_runtime_orchestrator`
  - `runtime/services/message_bus.py` 等模块仍保留全局 fallback
  - 多个调用方先查 container，再 fallback 到 global
- 与设计冲突:
  - 分层架构要求明确依赖边界
  - 全局 fallback 会制造隐式耦合和隐藏生命周期来源
- 影响面:
  - `runtime/bootstrap.py`
  - `runtime/services/`
  - `api/`
  - `agent/`
  - `core/container.py`
- 不改的后果:
  - 后续迁移即使表面完成，底层仍会通过 global service 反向耦合
- 依赖关系:
  - 与 A1、A4、A3 紧密相关
  - 应在主架构迁移阶段完成，不宜拖到最后

### A9. 删除旧 `core/loop + complete_agent + processing` 运行时路径

- 优先级: `P1`
- 决策状态: `已确认，必须删`
- 当前问题:
  - 仓库里仍保留旧的 `LoopEngine`、`CompleteAgent`、`processing/` 体系
  - 与当前 task-agent runtime 是两套不同心智模型
- 与设计冲突:
  - 旧路径不属于当前 target layered architecture
  - 会持续误导新实现和新贡献者
- 影响面:
  - `core/loop.py`
  - `core/complete_agent.py`
  - `processing/`
  - 相关 import/export
- 不改的后果:
  - 架构文档与代码叙事继续双轨并存
  - 重构中会反复出现“要不要兼容旧路径”的干扰
- 依赖关系:
  - 应在确认主路径已完全替代后尽快删除
  - 不应长时间并存

### A10. 清理未接入或旧语义的上下文路径

- 优先级: `P2`
- 决策状态: `建议清理`
- 当前问题:
  - `context/builder.py` 仍保留旧的 context builder 语义
  - 与当前 `PromptContextAssembler / PromptContextRenderer` 并存
- 与设计冲突:
  - 同一层不应长期保留两套不同范式的上下文构造逻辑
- 影响面:
  - `context/builder.py`
  - 可能波及引用其 `Scenario` 常量的代码
- 不改的后果:
  - 后续重构时会出现“新旧上下文体系”并存
- 依赖关系:
  - 可在 A7 之后统一处理

### A11. 收敛 timeline 相关依赖获取方式，避免领域代码继续依赖 plugin globals

- 优先级: `P2`
- 决策状态: `建议处理`
- 当前问题:
  - [timeline/handler.py](/Users/asuka/code/magi/backend/src/magi/timeline/handler.py) 仍通过 `get_plugin_manager()`、`get_sensor_registry()` 取依赖
  - timeline 领域逻辑虽已回到 `timeline/`，但依赖注入方式仍偏全局
- 与设计冲突:
  - 领域层应依赖显式 contract，而不是 runtime-global registry getter
- 影响面:
  - `timeline/handler.py`
  - `timeline/scheduler_contrib.py`
  - `plugins/runtime.py`
- 不改的后果:
  - timeline 虽已分层归位，但仍保留隐藏耦合
- 依赖关系:
  - 可在 A2、A8 之后处理

### A12. 统一目录与模块命名，消除旧术语残留

- 优先级: `P2`
- 决策状态: `建议处理`
- 当前问题:
  - 目录和模块名里仍残留 `executor`、`websocket under api`、旧 runtime 术语
  - 文档与代码术语已经部分分叉
- 与设计冲突:
  - 新文档已经收敛到 `actions`、`connection/transport`、`tools and skills`
- 影响面:
  - 目录名
  - import 路径
  - 文档引用
  - 测试路径
- 不改的后果:
  - 长期认知成本偏高
  - 后续 review 时会不断出现“这个名字其实不是这个意思”
- 依赖关系:
  - 最适合在主结构迁移基本完成后统一做

---

## 5. 建议改造顺序

推荐按以下顺序推进，原因是这样能先收掉“错误扩散源”，再处理概念清理：

1. `A1 runtime 总装拆解`
2. `A2 调度器纯引擎化`
3. `A3 L13/L14 真实迁移`
4. `A4 API 旁路依赖清理`
5. `A8 runtime globals / fallback 清理`
6. `A5 skills 生命周期统一`
7. `A7 context 主出口收敛`
8. `A6 action emitter 命名与归属迁移`
9. `A9 删除旧 runtime / loop / processing`
10. `A10` `A11` `A12` 作为收尾清理

这个顺序的核心原则是：

- 先拆中心枢纽
- 再拆跨层旁路
- 再统一能力边界
- 最后删除旧路径和做命名收尾

---

## 6. 风险提示

以下改造项虽然必要，但改动面较大，执行时需要单独拆任务：

- `A1` 会影响启动、依赖注入、模块初始化顺序
- `A3` 会影响 API、WebSocket、应用启动 wiring、导入路径
- `A8` 会影响大量当前依赖 runtime global accessor 的调用方
- `A9` 删除旧路径前必须确认没有隐性使用者

这些都适合拆成多个独立可验证任务，避免一次性大爆炸式提交。

---

## 7. 完成标准

当以下条件满足时，可以认为代码架构基本与分层设计对齐：

- 不再存在一个中心 runtime 文件同时知道所有层的构造细节
- scheduler 只提供调度引擎，不再负责具体业务注册编排
- API 层与连接层目录和职责明确分离
- API 层不再自行 new 领域对象或依赖 runtime global fallback
- skills、actions、context 都只有一套主路径
- 旧 `loop / complete_agent / processing` 路径已删除
- 代码术语与 [Layered Agent Architecture](/Users/asuka/code/magi/docs/layered-agent-architecture.md) 中的术语保持一致
