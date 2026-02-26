# AI Personality

AI 人格配置规范，定义 AI 助手的行为风格和回复方式。

## ADDED Requirements

### Requirement: 预设人格选择

系统 SHALL 从后端获取预设的人格风格列表，支持多语言。

#### Scenario: 加载预设人格列表
- **WHEN** 用户进入人格配置页面
- **THEN** 系统 SHALL 调用 `/api/personalities` 端点获取预设人格列表
- **AND** 系统 SHALL 根据当前语言设置获取对应语言的人格描述

#### Scenario: 人格多语言支持
- **WHEN** 后端返回人格列表
- **THEN** 后端 SHALL 从 `backend/personalities/{language}/` 目录读取人格文件
- **AND** 系统 SHALL 展示与用户语言匹配的人格名称和描述

#### Scenario: 选择预设人格
- **WHEN** 用户选择某个预设人格
- **THEN** 系统 SHALL 保存所选人格的 ID 到 `personality.preset`

### Requirement: 人格 API

后端 SHALL 提供人格预设列表 API。

#### Scenario: API 请求格式
- **WHEN** 前端请求 `/api/personalities?lang=zh-CN`
- **THEN** 后端 SHALL 返回对应语言的人格列表，包含：
  - 人格 ID
  - 名称（当前语言）
  - 描述（当前语言）
  - 系统提示词模板

### Requirement: 自定义人格

系统 SHALL 允许用户通过提示词自定义 AI 人格。

#### Scenario: 选择自定义人格
- **WHEN** 用户选择"自定义"人格
- **THEN** 系统 SHALL 显示自定义提示词输入框

#### Scenario: 输入自定义提示词
- **WHEN** 用户输入自定义人格提示词
- **THEN** 系统 SHALL 保存到 `personality.custom_prompt`
- **AND** 系统 SHALL 使用该提示词作为 AI 的行为指导

### Requirement: 语调设置

系统 SHALL 允许用户配置 AI 的语调风格。

#### Scenario: 选择语调
- **WHEN** 用户配置语调
- **THEN** 系统 SHALL 展示以下选项：
  - 随意（Casual）
  - 正式（Formal）

### Requirement: 快速模式简化配置

在快速模式下，系统 SHALL 提供简化的人格配置。

#### Scenario: 快速模式人格配置
- **WHEN** 用户处于快速模式引导
- **THEN** 系统 SHALL 仅展示预设人格选择

#### Scenario: 专家模式人格配置
- **WHEN** 用户处于专家模式引导或配置页面
- **THEN** 系统 SHALL 展示完整配置：预设选择、自定义提示词、语调
