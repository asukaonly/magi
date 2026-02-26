# Language Settings

语言设置规范，定义系统支持的语言和切换行为。

## ADDED Requirements

### Requirement: 支持的语言

系统 SHALL 支持中文和英文两种界面语言。

#### Scenario: 可选语言列表
- **WHEN** 用户查看语言设置
- **THEN** 系统 SHALL 展示以下选项：
  - 中文（简体）
  - English

### Requirement: 语言切换

系统 SHALL 允许用户随时切换界面语言。

#### Scenario: 选择中文
- **WHEN** 用户选择"中文（简体）"
- **THEN** 系统 SHALL 设置 `preferences.language` 为 `zh`
- **AND** 系统 SHALL 刷新页面以应用中文界面

#### Scenario: 选择英文
- **WHEN** 用户选择"English"
- **THEN** 系统 SHALL 设置 `preferences.language` 为 `en`
- **AND** 系统 SHALL 刷新页面以应用英文界面

### Requirement: 语言持久化

系统 SHALL 持久化用户的语言偏好。

#### Scenario: 语言偏好保存
- **WHEN** 用户切换语言
- **THEN** 系统 SHALL 将语言设置保存到后端配置
- **AND** 下次访问时系统 SHALL 使用保存的语言设置

### Requirement: 默认语言

系统 SHALL 提供默认语言设置。

#### Scenario: 无语言偏好时
- **WHEN** 用户首次使用且未选择语言
- **THEN** 系统 SHALL 默认使用中文（简体）
