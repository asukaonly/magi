# Agent Loop Spec

## ADDED Requirements

### Requirement: Agent循环支持四阶段流程

系统SHALL实现Sense-Plan-Act-Reflect四阶段循环流程。

#### Scenario: Sense阶段
- **WHEN** Agent循环开始
- **THEN** Agent调用感知模块获取外部输入
- **AND** 感知模块返回Perception列表
- **AND** 感知数据经过去重、分类、意图识别、优先级评估、融合

#### Scenario: Plan阶段
- **WHEN** Sense阶段完成
- **THEN** Agent分析感知数据，制定行动计划
- **AND** Plan阶段包括：任务识别、工具选择、参数生成、执行规划
- **AND** 生成Action对象

#### Scenario: Act阶段
- **WHEN** Plan阶段完成
- **THEN** Agent执行Action
- **AND** Act阶段包括：工具调用、参数传递、结果处理
- **AND** 返回执行结果

#### Scenario: Reflect阶段
- **WHEN** Act阶段完成
- **THEN** Agent反思执行结果
- **AND** Reflect阶段包括：成功经验积累、失败原因分析、能力更新
- **AND** 生成经验存储到记忆

---

### Requirement: Agent循环支持异步执行

系统SHALL以全异步方式执行Agent循环，不阻塞其他操作。

#### Scenario: 异步Sense阶段
- **WHEN** Agent进入Sense阶段
- **THEN** 异步调用感知模块
- **AND** 不阻塞其他Agent或系统操作

#### Scenario: 异步Plan阶段
- **WHEN** Agent进入Plan阶段
- **THEN** 异步调用规划模块
- **AND** LLM推理在后台执行

#### Scenario: 异步Act阶段
- **WHEN** Agent进入Act阶段
- **THEN** 异步执行工具调用
- **AND** 支持并发执行多个工具

#### Scenario: 异步Reflect阶段
- **WHEN** Agent进入Reflect阶段
- **THEN** 异步调用反思模块
- **AND** 经验存储不阻塞下一轮循环

---

### Requirement: Agent循环支持循环控制

系统SHALL支持启动、停止、暂停、恢复循环。

#### Scenario: 启动循环
- **WHEN** 调用`agent.start()`
- **THEN** Agent开始Sense-Plan-Act-Reflect循环
- **AND** 循环持续运行直到收到停止信号

#### Scenario: 停止循环
- **WHEN** 调用`agent.stop()`
- **THEN** Agent完成当前循环后停止
- **AND** 清理资源，保存状态

#### Scenario: 暂停循环
- **WHEN** 调用`agent.pause()`
- **THEN** Agent完成当前循环后暂停
- **AND** 不开始新的循环

#### Scenario: 恢复循环
- **WHEN** 调用`agent.resume()`
- **THEN** Agent从暂停处恢复循环
- **AND** 继续Sense-Plan-Act-Reflect流程

---

### Requirement: Agent循环支持错误处理

系统SHALL在循环的每个阶段处理错误，确保循环持续运行。

#### Scenario: Sense阶段错误处理
- **WHEN** Sense阶段抛出异常
- **THEN** 系统记录错误日志
- **AND** 跳过当前循环，不进入Plan阶段
- **AND** 继续下一轮Sense

#### Scenario: Plan阶段错误处理
- **WHEN** Plan阶段抛出异常
- **THEN** 系统记录错误日志
- **AND** 发布ErrorOccurred事件
- **AND** 跳过当前循环，继续下一轮Sense

#### Scenario: Act阶段错误处理
- **WHEN** Act阶段抛出异常
- **THEN** 系统记录错误日志
- **AND** 发布ErrorOccurred事件
- **AND** 进入Reflect阶段分析失败原因

#### Scenario: Reflect阶段错误处理
- **WHEN** Reflect阶段抛出异常
- **THEN** 系统记录错误日志
- **AND** 不影响下一轮循环
- **AND** 继续Sense阶段

---

### Requirement: Agent循环支持循环间隔控制

系统SHALL支持配置循环间隔，避免过度消耗资源。

#### Scenario: 固定间隔循环
- **WHEN** 配置文件设置`agent.loop_interval = 1.0`
- **THEN** 每轮循环完成后等待1秒
- **AND** 然后开始下一轮循环

#### Scenario: 自适应间隔循环
- **WHEN** 配置文件设置`agent.loop_interval = "adaptive"`
- **THEN** 系统根据感知数量动态调整间隔
- **AND** 感知多时缩短间隔（0.5秒），感知少时延长间隔（5秒）

#### Scenario: 无间隔循环
- **WHEN** 配置文件设置`agent.loop_interval = 0`
- **THEN** 系统无延迟连续执行循环
- **AND** 适用于高响应场景

---

### Requirement: Agent循环支持循环监控

系统SHALL监控循环执行状态，提供统计信息。

#### Scenario: 循环统计查询
- **WHEN** 管理员查询循环统计
- **THEN** 系统返回统计信息
- **AND** 统计包括：总循环次数、各阶段平均耗时、错误率

#### Scenario: 循环性能监控
- **WHEN** 系统监控循环性能
- **THEN** 记录每轮循环的耗时
- **AND** 检测循环延迟或卡住

#### Scenario: 循环健康检查
- **WHEN** 系统检测到循环异常（如连续失败）
- **THEN** 系统发布健康告警事件
- **AND** 尝试恢复循环

---

### Requirement: Agent循环支持单步执行

系统SHALL支持单步执行循环，用于调试和测试。

#### Scenario: 单步Sense
- **WHEN** 调用`agent.step_sense()`
- **THEN** 系统只执行Sense阶段
- **AND** 返回感知结果，不继续Plan阶段

#### Scenario: 单步Plan
- **WHEN** 调用`agent.step_plan(perception)`
- **THEN** 系统只执行Plan阶段
- **AND** 返回计划结果，不继续Act阶段

#### Scenario: 单步Act
- **WHEN** 调用`agent.step_act(action)`
- **THEN** 系统只执行Act阶段
- **AND** 返回执行结果，不继续Reflect阶段

#### Scenario: 单步Reflect
- **WHEN** 调用`agent.step_reflect(result)`
- **THEN** 系统只执行Reflect阶段
- **AND** 返回反思结果

---

### Requirement: Agent循环支持循环事件发布

系统SHALL在循环的关键节点发布事件，用于监控和插件介入。

#### Scenario: 循环开始事件
- **WHEN** Agent循环开始
- **THEN** 发布`LoopStarted`事件
- **AND** 事件包含循环ID、开始时间戳

#### Scenario: 阶段开始事件
- **WHEN** 循环进入某个阶段（Sense/Plan/Act/Reflect）
- **THEN** 发布`LoopPhaseStarted`事件
- **AND** 事件包含阶段名称、阶段输入数据

#### Scenario: 阶段完成事件
- **WHEN** 循环完成某个阶段
- **THEN** 发布`LoopPhaseCompleted`事件
- **AND** 事件包含阶段名称、阶段输出数据、耗时

#### Scenario: 循环完成事件
- **WHEN** Agent循环完成一轮
- **THEN** 发布`LoopCompleted`事件
- **AND** 事件包含循环ID、完成时间戳、总耗时

---

## Acceptance Criteria

- [ ] 四阶段循环流程功能验证测试通过
- [ ] 异步执行功能验证测试通过
- [ ] 循环控制功能验证测试通过
- [ ] 错误处理功能验证测试通过
- [ ] 循环间隔控制功能验证测试通过
- [ ] 循环监控功能验证测试通过
- [ ] 单步执行功能验证测试通过
- [ ] 循环事件发布功能验证测试通过
