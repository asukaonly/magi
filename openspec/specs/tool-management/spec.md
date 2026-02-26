# Tool Management

工具管理规范，定义内置工具和外部 Skills 的配置能力。

## ADDED Requirements

### Requirement: 内置工具列表

系统 SHALL 展示固定的内置工具列表供用户启用/禁用。

#### Scenario: 内置工具展示
- **WHEN** 用户查看工具配置
- **THEN** 系统 SHALL 展示以下内置工具及其当前启用状态：
  - 天气工具
  - 网页搜索
  - 网页获取

#### Scenario: 启用内置工具
- **WHEN** 用户启用某个内置工具
- **THEN** 系统 SHALL 设置 `tools.builtIn[toolId].enabled` 为 `true`

#### Scenario: 禁用内置工具
- **WHEN** 用户禁用某个内置工具
- **THEN** 系统 SHALL 设置 `tools.builtIn[toolId].enabled` 为 `false`

### Requirement: 天气工具配置

系统 SHALL 允许用户配置天气工具的服务商和认证信息。

#### Scenario: 天气服务商选择
- **WHEN** 用户配置天气工具
- **THEN** 系统 SHALL 展示以下服务商选项：
  - OpenWeather
  - 和风天气

#### Scenario: OpenWeather 配置
- **WHEN** 用户选择 OpenWeather 服务商
- **THEN** 系统 SHALL 要求用户输入 API Key

#### Scenario: 和风天气配置
- **WHEN** 用户选择和风天气服务商
- **THEN** 系统 SHALL 要求用户输入：
  - API Key
  - API URL

### Requirement: 网页搜索工具配置

系统 SHALL 允许用户配置网页搜索工具的服务商和认证信息。

#### Scenario: 网页搜索服务商选择
- **WHEN** 用户配置网页搜索工具
- **THEN** 系统 SHALL 展示以下服务商选项：
  - DuckDuckGo
  - Brave
  - Perplexity
  - Tavily
  - Google

#### Scenario: DuckDuckGo 配置
- **WHEN** 用户选择 DuckDuckGo 服务商
- **THEN** 系统 SHALL 不要求输入 API Key
- **AND** 系统 SHALL 直接启用服务

#### Scenario: 需要 API Key 的服务商配置
- **WHEN** 用户选择 Brave/Perplexity/Tavily/Google 服务商
- **THEN** 系统 SHALL 要求用户输入 API Key

### Requirement: 网页获取工具配置

系统 SHALL 允许用户配置网页获取工具的渲染方式。

#### Scenario: Playwright 浏览器渲染选项
- **WHEN** 用户配置网页获取工具
- **THEN** 系统 SHALL 展示以下选项：
  - 是否启用 Playwright 浏览器渲染

#### Scenario: 启用 Playwright
- **WHEN** 用户启用 Playwright 选项
- **THEN** 系统 SHALL 使用浏览器方式获取网页内容
- **AND** 系统 SHALL 检测 Playwright 是否已安装

#### Scenario: 禁用 Playwright
- **WHEN** 用户禁用 Playwright 选项
- **THEN** 系统 SHALL 使用简单的 HTTP 请求获取网页内容

### Requirement: 外部 Skills 列表

系统 SHALL 从后端获取可用的外部 Skills 列表。

#### Scenario: 加载 Skills 列表
- **WHEN** 用户进入工具配置页面
- **THEN** 系统 SHALL 调用后端 API 获取可用 Skills 列表
- **AND** 系统 SHALL 展示每个 Skill 的名称和描述

#### Scenario: 启用 Skill
- **WHEN** 用户启用某个 Skill
- **THEN** 系统 SHALL 将 Skill ID 添加到 `tools.skills` 数组

#### Scenario: 禁用 Skill
- **WHEN** 用户禁用某个 Skill
- **THEN** 系统 SHALL 从 `tools.skills` 数组中移除该 Skill ID

### Requirement: 仅专家模式可用

工具配置 SHALL 仅在专家模式下展示。

#### Scenario: 快速模式跳过工具配置
- **WHEN** 用户处于快速模式引导
- **THEN** 系统 SHALL 不展示工具配置步骤

#### Scenario: 专家模式展示工具配置
- **WHEN** 用户处于专家模式引导
- **THEN** 系统 SHALL 展示完整的工具配置界面

### Requirement: Skills 列表 API

后端 SHALL 提供 Skills 列表 API。

#### Scenario: API 响应格式
- **WHEN** 前端请求 `/api/skills` 端点
- **THEN** 后端 SHALL 返回 Skills 列表，包含：
  - Skill ID
  - 名称
  - 描述
  - 是否已启用
