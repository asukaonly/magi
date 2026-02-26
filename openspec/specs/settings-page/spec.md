# Settings Page

配置管理页面规范，定义用户随时修改配置的能力。

## ADDED Requirements

### Requirement: 配置页面访问

系统 SHALL 提供独立的配置管理页面，允许用户随时修改所有设置。

#### Scenario: 访问配置页面
- **WHEN** 用户导航到 `/settings` 路由
- **THEN** 系统 SHALL 显示配置管理页面
- **AND** 系统 SHALL 展示所有配置分类

### Requirement: 配置分类展示

系统 SHALL 按分类组织配置项，便于用户查找和修改。

#### Scenario: 配置分类列表
- **WHEN** 用户查看配置页面
- **THEN** 系统 SHALL 展示以下配置分类：
  - 偏好设置（语言、用户模式）
  - LLM 配置
  - AI 人格
  - 记忆配置
  - 工具管理
  - 系统配置（循环、消息总线、WebSocket、日志）

### Requirement: 配置实时保存

系统 SHALL 在用户修改配置后提供保存功能。

#### Scenario: 保存单个分类配置
- **WHEN** 用户修改某个分类的配置并点击保存
- **THEN** 系统 SHALL 验证配置项的有效性
- **AND** 系统 SHALL 调用后端 API 更新配置
- **AND** 系统 SHALL 显示保存成功提示

#### Scenario: 配置验证失败
- **WHEN** 用户提交的配置包含无效值
- **THEN** 系统 SHALL 显示具体错误信息
- **AND** 系统 SHALL 不提交到后端

### Requirement: 语言切换入口

配置页面 SHALL 提供语言切换功能。

#### Scenario: 切换语言
- **WHEN** 用户在配置页面切换语言选项
- **THEN** 系统 SHALL 保存语言偏好
- **AND** 系统 SHALL 刷新页面以应用新语言
