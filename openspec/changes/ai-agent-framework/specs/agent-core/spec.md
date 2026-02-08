# Agent Core Spec

## ADDED Requirements

### Requirement: Agent核心支持三层架构

系统SHALL实现三层Agent架构：Master Agent、TaskAgent、WorkerAgent。

#### Scenario: Master Agent启动
- **WHEN** 系统启动
- **THEN** 创建单个Master Agent实例
- **AND** Master Agent负责系统管理和任务分发

#### Scenario: TaskAgent固定数量
- **WHEN** 配置文件设置`agent.num_task_agents = 3`
- **THEN** 系统创建3个TaskAgent实例
- **AND** TaskAgent数量固定，运行期间不变

#### Scenario: WorkerAgent动态创建
- **WHEN** TaskAgent需要执行任务
- **THEN** 创建WorkerAgent实例
- **AND** WorkerAgent执行完任务后销毁

---

### Requirement: Master Agent负责系统管理

Master Agent SHALL负责系统管理、任务识别、健康检查、任务分发。

#### Scenario: Master Agent主循环
- **WHEN** Master Agent启动
- **THEN** 进入主循环
- **AND** 循环步骤：获取感知 → 识别任务 → 分发任务 → 健康检查

#### Scenario: 任务识别
- **WHEN** Master Agent接收到感知
- **THEN** 分析感知内容，识别任务
- **AND** 将任务添加到任务数据库
- **AND** 任务包含：类型、优先级、参数、截止时间

#### Scenario: 任务分发
- **WHEN** 任务数据库有待处理任务
- **THEN** Master Agent选择负载最低的TaskAgent
- **AND** 将任务分发给该TaskAgent

#### Scenario: 系统健康检查
- **WHEN** Master Agent完成一轮循环
- **THEN** 检查系统健康状态
- **AND** 检查项：CPU使用率、内存使用量、TaskAgent状态
- **AND** 异常时发布健康告警事件

---

### Requirement: TaskAgent负责任务编排

TaskAgent SHALL负责任务分解、工具匹配、WorkerAgent创建。

#### Scenario: TaskAgent扫描任务数据库
- **WHEN** TaskAgent启动
- **THEN** 定期扫描任务数据库
- **AND** 查找分配给自己的待处理任务

#### Scenario: 任务分解
- **WHEN** TaskAgent获取到任务
- **THEN** 使用LLM分解任务为子任务
- **AND** 生成任务执行DAG
- **AND** 计算任务超时时间（基于任务类型、优先级、交互级别）

#### Scenario: 工具匹配
- **WHEN** 任务分解完成
- **THEN** 查询工具注册表
- **AND** 为每个子任务匹配合适的工具
- **AND** 生成工具执行计划

#### Scenario: 创建WorkerAgent
- **WHEN** 工具执行计划生成
- **THEN** 创建WorkerAgent实例
- **AND** 将子任务和工具计划传递给WorkerAgent
- **AND** WorkerAgent独立执行任务

---

### Requirement: WorkerAgent负责任务执行

WorkerAgent SHALL负责执行具体任务，执行完成后销毁。

#### Scenario: WorkerAgent执行任务
- **WHEN** WorkerAgent接收任务
- **THEN** 根据工具计划执行工具
- **AND** 处理工具执行结果
- **AND** 返回任务执行结果

#### Scenario: WorkerAgent超时处理
- **WHEN** WorkerAgent执行超过超时时间
- **THEN** 系统终止WorkerAgent
- **AND** 记录超时错误
- **AND** TaskAgent决定是否重试

#### Scenario: WorkerAgent重试机制
- **WHEN** WorkerAgent执行失败
- **THEN** TaskAgent根据重试策略决定
- **AND** 如果可重试，创建新的WorkerAgent
- **AND** 最大重试次数为3次

#### Scenario: WorkerAgent销毁
- **WHEN** WorkerAgent完成或失败
- **THEN** 系统销毁WorkerAgent实例
- **AND** 释放资源
- **AND** WorkerAgent不可复用

---

### Requirement: 任务数据库支持持久化

系统SHALL使用SQLite持久化存储任务，支持任务恢复。

#### Scenario: 任务存储
- **WHEN** Master Agent识别任务
- **THEN** 将任务存储到SQLite数据库
- **AND** 任务包含：ID、类型、状态、优先级、参数、创建时间

#### Scenario: 任务状态更新
- **WHEN** TaskAgent开始或完成任务
- **THEN** 更新任务状态
- **AND** 状态包括：PENDING、PROCESSING、COMPLETED、FAILED

#### Scenario: 任务恢复
- **WHEN** 系统重启后
- **THEN** 从SQLite恢复未完成的任务
- **AND** TaskAgent继续处理这些任务

---

### Requirement: 负载均衡基于pending数量

系统SHALL根据TaskAgent的pending任务数量选择负载最低的Agent。

#### Scenario: 记录pending数量
- **WHEN** TaskAgent开始处理任务
- **THEN** pending计数加1
- **AND** 任务完成后pending计数减1

#### Scenario: 选择负载最低的TaskAgent
- **WHEN** Master Agent需要分发任务
- **THEN** 查询所有TaskAgent的pending数量
- **AND** 选择pending数量最少的TaskAgent
- **AND** 如果有多个，随机选择一个

---

### Requirement: 系统监控支持CPU和内存

系统SHALL监控系统CPU和内存使用率，用于健康检查。

#### Scenario: CPU使用率监控
- **WHEN** Master Agent执行健康检查
- **THEN** 读取当前CPU使用率
- **AND** 如果CPU使用率 > 90%，发布告警事件

#### Scenario: 内存使用量监控
- **WHEN** Master Agent执行健康检查
- **THEN** 读取当前内存使用量
- **AND** 如果内存使用率 > 90%，发布告警事件

#### Scenario: 告警触发降级
- **WHEN** 系统资源告警
- **THEN** Master Agent降低任务处理速率
- **AND** 或暂停接收新任务

---

### Requirement: 超时计算基于多维度

系统SHALL根据任务类型、优先级、交互级别计算超时时间。

#### Scenario: 交互式任务超时
- **WHEN** 任务需要用户交互
- **THEN** 超时时间 = 基础超时（60秒） × 交互因子（2.0）
- **AND** 最终超时为120秒

#### Scenario: 高优先级任务超时
- **WHEN** 任务优先级为EMERGENCY
- **THEN** 超时时间 = 基础超时 × 0.5
- **AND** 高优先级任务快速失败

#### Scenario: 计算密集型任务超时
- **WHEN** 任务类型为计算密集型
- **THEN** 超时时间 = 基础超时 × 3.0
- **AND** 允许更长执行时间

---

### Requirement: 三层Agent支持独立监控

系统SHALL独立监控每层Agent的状态和性能。

#### Scenario: Master Agent监控
- **WHEN** 系统监控Master Agent
- **THEN** 记录主循环次数、任务识别数量、健康检查结果
- **AND** 发布MasterAgentHeartbeat事件

#### Scenario: TaskAgent监控
- **WHEN** 系统监控TaskAgent
- **THEN** 记录处理的任务数量、pending数量、平均执行时间
- **AND** 发布TaskAgentHeartbeat事件

#### Scenario: WorkerAgent监控
- **WHEN** 系统监控WorkerAgent
- **THEN** 记录创建数量、销毁数量、成功率、失败原因
- **AND** 发布WorkerAgentStatistics事件

---

### Requirement: 三层Agent支持优雅启停

系统SHALL支持三层Agent的优雅启动和停止。

#### Scenario: 顺序启动
- **WHEN** 系统启动
- **THEN** 先启动Master Agent
- **AND** 再启动所有TaskAgent
- **AND** 最后等待任务创建WorkerAgent

#### Scenario: 逆序停止
- **WHEN** 系统停止
- **THEN** 先停止Master Agent（不再接收新任务）
- **AND** 等待所有TaskAgent完成任务
- **AND** TaskAgent等待所有WorkerAgent完成
- **AND** 最后停止所有TaskAgent

#### Scenario: 停止超时处理
- **WHEN** 停止过程中有Agent超过超时时间（30秒）
- **THEN** 强制停止该Agent
- **AND** 记录警告日志
- **AND** 继续停止其他Agent

---

## Acceptance Criteria

- [ ] 三层架构功能验证测试通过
- [ ] Master Agent系统管理功能验证测试通过
- [ ] TaskAgent任务编排功能验证测试通过
- [ ] WorkerAgent任务执行功能验证测试通过
- [ ] 任务数据库持久化功能验证测试通过
- [ ] 负载均衡功能验证测试通过
- [ ] 系统监控功能验证测试通过
- [ ] 超时计算功能验证测试通过
- [ ] 独立监控功能验证测试通过
- [ ] 优雅启停功能验证测试通过
