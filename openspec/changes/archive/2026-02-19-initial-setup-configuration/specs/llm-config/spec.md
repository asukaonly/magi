# LLM Config

LLM 配置规范，定义大语言模型提供商的配置能力。

## ADDED Requirements

### Requirement: 提供商选择

系统 SHALL 支持多个 LLM 提供商。

#### Scenario: 可选提供商列表
- **WHEN** 用户配置 LLM
- **THEN** 系统 SHALL 展示以下提供商选项：
  - OpenAI
  - Anthropic
  - 智谱（GLM）
  - 自定义（Custom）

### Requirement: 自定义提供商配置

系统 SHALL 允许用户配置自定义 LLM 提供商。

#### Scenario: 选择自定义提供商
- **WHEN** 用户选择"自定义"提供商
- **THEN** 系统 SHALL 展示以下配置项：
  - 名称（name）
  - Base URL
  - API Key
  - API Format（API 格式类型）

#### Scenario: 配置 API Format
- **WHEN** 用户配置自定义提供商的 API Format
- **THEN** 系统 SHALL 支持选择不同的 API 格式（如 OpenAI 兼容格式等）

### Requirement: 模型配置

系统 SHALL 允许用户配置模型名称。

#### Scenario: 设置模型名称
- **WHEN** 用户输入模型名称（如 `gpt-4`、`claude-3-opus`）
- **THEN** 系统 SHALL 保存模型名称到 `llm.model`

### Requirement: API 密钥配置

系统 SHALL 允许用户配置 API 密钥，并以安全方式存储。

#### Scenario: 输入 API 密钥
- **WHEN** 用户输入 API 密钥
- **THEN** 系统 SHALL 以掩码方式显示（如 `sk-***...***`）
- **AND** 系统 SHALL 加密存储 API 密钥

#### Scenario: 更新 API 密钥
- **WHEN** 用户修改 API 密钥
- **THEN** 系统 SHALL 用新密钥替换旧密钥
- **AND** 系统 SHALL 不在界面显示完整密钥

### Requirement: Base URL 配置

系统 SHALL 允许用户配置自定义 API 端点。

#### Scenario: 设置自定义 Base URL
- **WHEN** 用户输入 Base URL（如 `https://api.custom.com/v1`）
- **THEN** 系统 SHALL 保存到 `llm.base_url`
- **AND** 系统 SHALL 使用该 URL 作为 API 端点

#### Scenario: 使用默认 Base URL
- **WHEN** 用户不输入 Base URL
- **THEN** 系统 SHALL 使用提供商的默认 API 端点

### Requirement: 快速模式简化配置

在快速模式下，系统 SHALL 提供简化的 LLM 配置界面。

#### Scenario: 快速模式配置项
- **WHEN** 用户处于快速模式引导
- **THEN** 系统 SHALL 仅展示必填项：提供商、模型、API 密钥

#### Scenario: 专家模式配置项
- **WHEN** 用户处于专家模式引导或配置页面
- **THEN** 系统 SHALL 展示所有配置项：提供商、模型、API 密钥、Base URL

### Requirement: 配置验证

系统 SHALL 验证 LLM 配置的有效性。

#### Scenario: 验证必填项
- **WHEN** 用户提交 LLM 配置
- **THEN** 系统 SHALL 验证提供商和模型名称已填写
- **AND** 若验证失败 SHALL 显示错误提示
