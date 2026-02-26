# Memory Mode

记忆模式配置规范，定义 L1-L5 各层记忆的配置能力。

## ADDED Requirements

### Requirement: 记忆层级概览

系统 SHALL 展示五层记忆架构及其状态。

#### Scenario: 记忆层级展示
- **WHEN** 用户查看记忆配置
- **THEN** 系统 SHALL 展示以下记忆层级：
  - L1 - 原始事件（用户输入/AI反馈/工具调用/外部事件/定时事件）
  - L2 - 事件关系（图结构，维护事件相关性）
  - L3 - 语义事件（向量存储，语义搜索）
  - L4 - 摘要事件（按时间维度的摘要）
  - L5 - 能力记忆（历史总结归纳，优化决策和画像）

### Requirement: L1 原始事件配置

系统 SHALL 允许用户控制 L1 记忆的启用状态，其他层依赖 L1。

#### Scenario: 启用 L1 记忆
- **WHEN** 用户启用 L1 记忆
- **THEN** 系统 SHALL 使用本地 SQLite 存储原始事件
- **AND** 系统 SHALL 不提供其他 backend 选项

#### Scenario: 禁用 L1 记忆
- **WHEN** 用户禁用 L1 记忆
- **THEN** 系统 SHALL 禁用所有其他记忆层
- **AND** 系统 SHALL 提示用户其他层依赖 L1

#### Scenario: L1 作为其他层的前置
- **WHEN** 用户尝试启用 L2-L5 中的任意一层
- **AND** L1 当前为禁用状态
- **THEN** 系统 SHALL 提示必须先启用 L1
- **AND** 系统 SHALL 提供一键启用 L1 的选项

### Requirement: L2 事件关系配置

系统 SHALL 允许用户配置图存储的 backend 和关系生成规则。

#### Scenario: L2 backend 选择
- **WHEN** 用户配置 L2 记忆
- **THEN** 系统 SHALL 展示以下 backend 选项：
  - SQLite + NetworkX
  - Kùzu

#### Scenario: 自定义图关系生成
- **WHEN** 用户配置 L2 记忆
- **THEN** 系统 SHALL 允许用户修改图生成关系的规则

### Requirement: L3 语义事件配置

系统 SHALL 允许用户配置向量存储的服务类型和模型。

#### Scenario: 向量服务选型
- **WHEN** 用户配置 L3 记忆
- **THEN** 系统 SHALL 展示以下部署选项：
  - 本地部署
  - 远程服务

#### Scenario: 本地部署模型选择
- **WHEN** 用户选择"本地部署"
- **THEN** 系统 SHALL 根据当前语言设置推荐模型：
  - 英文：nomic-embed-text、snowflake-arctic-embed 等
  - 中文：bge、Qwen 等
- **AND** 系统 SHALL 提供模型下载功能

#### Scenario: 本地模型下载
- **WHEN** 用户点击下载模型
- **THEN** 系统 SHALL 下载所选模型到本地
- **AND** 系统 SHALL 显示下载进度

#### Scenario: 远程服务模型选择
- **WHEN** 用户选择"远程服务"
- **THEN** 系统 SHALL 提示将使用 LLM 配置的 API Key
- **AND** 系统 SHALL 根据 LLM provider 推荐模型：
  - OpenAI：text-embedding-3
  - GLM：Embedding-3
  - Anthropic：对应的 embedding 模型

### Requirement: L4 摘要事件配置

系统 SHALL 允许用户配置摘要类型。

#### Scenario: L4 backend 固定
- **WHEN** 用户启用 L4 记忆
- **THEN** 系统 SHALL 固定使用 SQLite 存储

#### Scenario: 摘要类型选择
- **WHEN** 用户配置 L4 记忆
- **THEN** 系统 SHALL 展示以下摘要类型选项：
  - 用户事件摘要
  - AI 工具执行摘要
  - 外部感知摘要
- **AND** 系统 SHALL 允许多选

### Requirement: L5 能力记忆配置

系统 SHALL 允许用户控制 L5 记忆的启用状态。

#### Scenario: L5 开关配置
- **WHEN** 用户配置 L5 记忆
- **THEN** 系统 SHALL 仅提供启用/禁用开关
- **AND** 系统 SHALL 不提供其他高级配置（后续扩展）

### Requirement: 仅专家模式可用

记忆配置 SHALL 仅在专家模式下展示。

#### Scenario: 快速模式跳过记忆配置
- **WHEN** 用户处于快速模式引导
- **THEN** 系统 SHALL 不展示记忆配置步骤

#### Scenario: 专家模式展示记忆配置
- **WHEN** 用户处于专家模式引导
- **THEN** 系统 SHALL 展示完整的记忆配置界面
