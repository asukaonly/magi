# Self-Awareness Spec

## ADDED Requirements

### Requirement: 自感知模块支持框架层和插件层分离

系统SHALL将自感知模块分为两层：框架层定义感知类别，插件层实现具体传感器。

#### Scenario: 框架层定义感知类别
- **WHEN** 系统初始化
- **THEN** 框架定义主要感知类别
- **AND** 类别包括：Audio（音频）、Video（视频）、Text（文本）、Image（图像）、Sensor（传感器数据）、Event（事件）

#### Scenario: 插件层实现具体传感器
- **WHEN** 开发者实现传感器
- **THEN** 传感器继承框架层的Sensor基类
- **AND** 实现具体的感知逻辑（如麦克风、摄像头、邮件监听）

#### Scenario: 插件决定触发模式
- **WHEN** 传感器注册到系统
- **THEN** 插件声明触发模式（POLL/EVENT/HYBRID）
- **AND** 系统根据触发模式调用传感器

---

### Requirement: 自感知模块支持三种触发模式

系统SHALL支持三种传感器触发模式：POLL（轮询）、EVENT（事件）、HYBRID（混合）。

#### Scenario: POLL模式
- **WHEN** 传感器触发模式为POLL
- **THEN** 系统定期调用传感器的`sense()`方法
- **AND** 间隔可配置（如每5秒）
- **AND** 传感器返回Perception或None

#### Scenario: EVENT模式
- **WHEN** 传感器触发模式为EVENT
- **THEN** 传感器调用系统的`listen(callback)`方法注册回调
- **AND** 当事件发生时，传感器主动调用回调
- **AND** 系统被动接收感知数据

#### Scenario: HYBRID模式
- **WHEN** 传感器触发模式为HYBRID
- **THEN** 传感器同时支持POLL和EVENT
- **AND** 系统定期调用`sense()`方法
- **AND** 传感器可主动调用回调

---

### Requirement: 自感知模块支持传感器按需启动

系统SHALL支持传感器按需启动，避免资源浪费。

#### Scenario: 传感器默认禁用
- **WHEN** 传感器注册到系统
- **THEN** 传感器默认处于禁用状态
- **AND** 传感器不消耗系统资源

#### Scenario: 按需启动传感器
- **WHEN** Agent需要特定感知能力
- **THEN** 系统启用对应传感器
- **AND** 传感器初始化并开始工作

#### Scenario: 自动停止传感器
- **WHEN** 传感器长时间未使用（超过5分钟）
- **THEN** 系统自动停止传感器
- **AND** 释放资源

---

### Requirement: 自感知模块支持多模态感知处理

系统SHALL支持传感器处理多模态数据（音频、视频、文本等）。

#### Scenario: 单模态感知
- **WHEN** 传感器只处理单一模态数据（如文本）
- **THEN** 传感器返回单模态Perception
- **AND** Perception包含感知类型、数据、时间戳

#### Scenario: 多模态融合感知
- **WHEN** 传感器处理多模态数据（如视频+音频）
- **THEN** 传感器返回多模态Perception
- **AND** Perception包含多个模态的数据
- **AND** 数据包含时间对齐信息

#### Scenario: 跨模态关联
- **WHEN** 系统接收到多个相关感知
- **THEN** 系统尝试关联不同模态的感知
- **AND** 生成融合感知结果

---

### Requirement: 自感知模块支持五步感知决策系统

系统SHALL实现五步感知决策系统：去重、分类、意图识别、优先级评估、融合。

#### Scenario: Step 1 - 去重
- **WHEN** 传感器产生新感知
- **THEN** 系统检查感知是否重复
- **AND** 基于内容相似度判断（如文本相似度、图像哈希）
- **AND** 重复感知被过滤

#### Scenario: Step 2 - 分类
- **WHEN** 感知去重完成
- **THEN** 系统对感知进行分类
- **AND** 分类维度：类型（通知/命令/查询）、紧急程度、来源
- **AND** 使用规则或LLM进行分类

#### Scenario: Step 3 - 意图识别
- **WHEN** 感知分类完成
- **THEN** 系统识别感知意图
- **AND** 意图包括：任务请求、信息查询、状态报告、错误报告
- **AND** 意图识别使用LLM或规则引擎

#### Scenario: Step 4 - 优先级评估
- **WHEN** 意图识别完成
- **THEN** 系统评估感知优先级
- **AND** 优先级基于：紧急程度、重要性、来源可信度
- **AND** 优先级分为：EMERGENCY、HIGH、MEDIUM、LOW、DEBUG

#### Scenario: Step 5 - 融合
- **WHEN** 优先级评估完成
- **THEN** 系统尝试融合相关感知
- **AND** 融合策略：时间窗口内相似感知合并、多模态感知融合
- **AND** 融合后的感知包含更丰富信息

---

### Requirement: 自感知模块支持优先级队列

系统SHALL使用优先级队列管理感知，高优先级感知优先处理。

#### Scenario: 感知入队
- **WHEN** 感知决策完成
- **THEN** 系统将感知加入优先级队列
- **AND** 队列按优先级排序（EMERGENCY > HIGH > MEDIUM > LOW > DEBUG）

#### Scenario: 感知出队
- **WHEN** Agent需要处理感知
- **THEN** 系统从队列中取出最高优先级感知
- **AND** 同优先级感知按时间顺序处理

#### Scenario: 队列背压
- **WHEN** 队列达到最大长度（默认100）
- **THEN** 系统根据背压策略丢弃感知
- **AND** 策略包括：丢弃最旧、丢弃低优先级、拒绝新感知

---

### Requirement: 自感知模块支持感知持久化

系统SHALL支持重要感知持久化，用于历史查询和事件溯源。

#### Scenario: 高优先级感知自动持久化
- **WHEN** 感知优先级为EMERGENCY或HIGH
- **THEN** 系统自动将感知持久化
- **AND** 存储到记忆存储L1层

#### Scenario: 订阅感知持久化
- **WHEN** 传感器注册时设置`persistent=True`
- **THEN** 该传感器的所有感知都被持久化
- **AND** 感知保留7天（可配置）

#### Scenario: 感知查询
- **WHEN** 用户查询历史感知
- **THEN** 系统从持久化存储检索感知
- **AND** 支持按时间范围、类型、优先级过滤

---

### Requirement: 自感知模块支持感知统计

系统SHALL提供感知统计信息，用于监控和调试。

#### Scenario: 感知统计查询
- **WHEN** 管理员查询感知统计
- **THEN** 系统返回统计信息
- **AND** 统计包括：各类型感知数量、平均处理时间、丢弃感知数

#### Scenario: 传感器状态查询
- **WHEN** 管理员查询传感器状态
- **THEN** 系统返回所有传感器状态
- **AND** 状态包括：启用/禁用、触发模式、最后感知时间

---

## Acceptance Criteria

- [ ] 框架层和插件层分离验证测试通过
- [ ] 三种触发模式功能验证测试通过
- [ ] 传感器按需启动功能验证测试通过
- [ ] 多模态感知处理功能验证测试通过
- [ ] 五步感知决策系统功能验证测试通过
- [ ] 优先级队列功能验证测试通过
- [ ] 感知持久化功能验证测试通过
- [ ] 感知统计功能验证测试通过
