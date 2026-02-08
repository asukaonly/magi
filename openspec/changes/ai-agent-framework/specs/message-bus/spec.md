# Message Bus Spec

## ADDED Requirements

### Requirement: 消息总线支持三种后端存储

系统SHALL支持消息总线的三种后端存储实现：
1. 内存后端（默认，零依赖）
2. SQLite后端（轻量级持久化）
3. Redis后端（可选，分布式支持）

#### Scenario: 配置为内存后端
- **WHEN** 管理员在配置文件中设置`message_bus.backend = "memory"`
- **THEN** 系统使用`asyncio.PriorityQueue`作为消息队列
- **AND** 消息仅在内存中传递，Agent重启后未处理消息丢失

#### Scenario: 配置为SQLite后端
- **WHEN** 管理员在配置文件中设置`message_bus.backend = "sqlite"`
- **THEN** 系统使用`SQLiteMessageBackend`作为消息队列
- **AND** 消息持久化到SQLite数据库
- **AND** Agent重启后未处理消息可恢复

#### Scenario: 配置为Redis后端
- **WHEN** 管理员在配置文件中设置`message_bus.backend = "redis"`
- **THEN** 系统使用`RedisMessageBackend`作为消息队列
- **AND** 消息持久化到Redis Streams
- **AND** 支持多机器分布式部署

---

### Requirement: 消息总线支持全异步事件处理

系统SHALL以全异步方式处理所有事件，不阻塞发布者。

#### Scenario: 发布事件不阻塞
- **WHEN** Agent调用`message_bus.publish(event)`
- **THEN** 方法立即返回，不等待订阅者处理完成
- **AND** 订阅者在后台异步处理事件

#### Scenario: 高并发事件处理
- **WHEN** 系统在短时间内收到100个事件
- **THEN** 系统通过worker池并发处理事件
- **AND** 不会因为单个订阅器阻塞而影响其他订阅者

---

### Requirement: 消息总线支持优先级队列

系统SHALL根据事件等级（EventLevel）实现优先级队列，高优先级事件优先处理。

#### Scenario: 事件优先级排序
- **WHEN** 同时发布一个EMERGENCY级别事件和一个DEBUG级别事件
- **THEN** EMERGENCY事件先于DEBUG事件被处理
- **AND** 优先级基于`EventLevel`枚举值（0-5）

#### Scenario: 背压机制
- **WHEN** 事件队列达到最大长度（默认1000条）
- **THEN** 系统根据`drop_policy`配置丢弃事件
- **AND** 支持`oldest`（丢弃最旧）、`lowest_priority`（丢弃低优先级）、`reject`（拒绝新事件）策略

---

### Requirement: 消息总线支持双传播模式

系统SHALL支持两种事件传播模式：
1. **广播模式（BROADCAST）**：所有订阅者都收到事件
2. **竞争模式（COMPETING）**：只有一个订阅者收到事件

#### Scenario: 广播模式
- **WHEN** 事件使用广播模式传播
- **THEN** 所有订阅该事件的订阅者都会收到事件
- **AND** 订阅者数量不影响事件分发速度

#### Scenario: 竞争模式
- **WHEN** 事件使用竞争模式传播
- **THEN** 只有一个订阅者收到事件
- **AND** 没有收到事件的订阅者不影响其他订阅者

---

### Requirement: 消息总线支持事件过滤

系统SHALL支持订阅者自定义过滤条件，只接收满足条件的事件。

#### Scenario: 基于优先级过滤
- **WHEN** 订阅者注册时设置`filter_func=lambda e: e.data.get("priority", 0) >= 2`
- **THEN** 只接收优先级>=2的事件
- **AND** 低优先级事件不会触发该订阅者

#### Scenario: 基于事件类型过滤
- **WHEN** 订阅者设置`filter_func=lambda e: e.data.get("error_type") == "TimeoutError"`
- **THEN** 只接收错误类型为TimeoutError的事件
- AND 其他错误类型不会触发该订阅者

---

### Requirement: 消息总线支持错误隔离

系统SHALL确保单个订阅者处理事件失败不影响其他订阅者。

#### Scenario: 订阅者异常不传播
- **WHEN** 订阅者A处理事件时抛出异常
- **THEN** 系统记录错误日志
- **AND** 继续通知订阅者B
- **AND** 订阅者B正常收到事件

#### Scenario: 错误日志记录
- **WHEN** 订阅者处理事件失败
- **THEN** 系统记录错误日志，包含订阅者名称和事件ID
- **AND** 日志级别为ERROR

---

### Requirement: 消息总线支持可选事件持久化

系统SHALL支持重要事件持久化存储，用于事件溯源。

#### Scenario: ERROR级别以上事件自动持久化
- **WHEN** 事件等级为ERROR或以上
- **THEN** 系统自动将事件持久化到存储后端
- **AND** 事件可被查询和回放

#### Scenario: 订阅者要求持久化
- **WHEN** 订阅者注册时设置`persistent=True`
- **THEN** 该订阅者订阅的所有事件都会被持久化
- **AND** 事件保留7天（可配置）

---

### Requirement: 消息总线提供事件类型定义

系统SHALL定义以下核心事件类型：
- `AgentStarted`: Agent启动
- `AgentStopped`: Agent停止
- `PerceptionReceived`: 接收到感知输入
- `PerceptionProcessed`: 感知处理完成
- `ActionExecuted`: 动作执行
- `CapabilityCreated`: 能力创建
- `ExperienceStored`: 经验存储
- `ErrorOccurred`: 错误发生

#### Scenario: Agent启动事件
- **WHEN** Agent调用`start()`方法成功
- **THEN** 系统发布`AgentStarted`事件
- **AND** 事件包含Agent ID和启动时间戳

#### Scenario: 错误事件发布
- **WHEN** 系统发生错误
- **THEN** 系统发布`ErrorOccurred`事件
- **AND** 事件包含错误类型、错误信息和上下文

---

### Requirement: 消息总线支持负载均衡的竞争消费

在竞争模式下，系统SHALL根据订阅者pending数量选择负载最低的订阅者处理事件。

#### Scenario: 选择负载最低的订阅者
- **WHEN** 事件使用竞争模式传播
- **THEN** 系统选择pending任务数量最少的订阅者
- **AND** 该订阅者处理事件后pending计数减1
- **AND** 处理完成后pending计数恢复

#### Scenario: 订阅者负载跟踪
- **WHEN** WorkerAgent开始处理事件
- **THEN** 该订阅者的pending计数加1
- **WHEN** WorkerAgent完成事件处理
- **THEN** 该订阅者的pending计数减1

---

### Requirement: 消息总线提供统计信息查询

系统SHALL提供API查询消息总线统计信息，用于监控和调试。

#### Scenario: 查询队列统计
- **WHEN** 管理员查询消息总线状态
- **THEN** 系统返回队列长度、最大队列大小、丢弃事件数、拒绝事件数
- **AND** 返回各事件类型的订阅者数量

#### Scenario: 查询性能指标
- **WHEN** 运维人员查询性能指标
- **THEN** 系统返回事件处理速率、平均延迟等指标

---

### Requirement: 消息总线支持优雅启停

系统SHALL支持优雅启动和停止，确保不丢失事件。

#### Scenario: 优雅停止
- **WHEN** 系统收到停止信号
- **THEN** 系统停止接收新事件
- **AND** 等待所有已接收事件处理完成
- **AND** 关闭所有worker线程
- **AND** 清理资源

#### Scenario: Worker停止超时
- **WHEN** 某个worker在停止时处理时间超过阈值（30秒）
- **THEN** 系统强制停止该worker
- **AND** 记录警告日志
- **AND** 继续停止其他worker

---

### Requirement: 消息总线支持配置化

系统SHALL通过配置文件控制消息总线行为。

#### Scenario: 基本配置
- **WHEN** 配置文件定义`message_bus.backend`
- **THEN** 系统使用指定的后端实现
- **AND** 加载该后端的特定配置（如SQLite路径、Redis URL）

#### Scenario: 高级配置
- **WHEN** 配置文件定义`message_bus.max_queue_size`
- **THEN** 队列最大长度为指定值
- **AND** 队列满时使用配置的drop_policy

#### Scenario: Worker配置
- **WHEN** 配置文件定义`message_bus.num_workers`
- **THEN** 启动指定数量的worker线程
- **AND** worker并发处理事件

---

## Acceptance Criteria

- [ ] 所有8个后端需求都有对应测试用例
- [ ] 优先级队列功能验证测试通过
- [ ] 错误隔离机制验证测试通过
- [ ] 事件持久化功能验证测试通过
- [ ] 优雅启停功能验证测试通过
- [ ] 配置化功能验证测试通过
