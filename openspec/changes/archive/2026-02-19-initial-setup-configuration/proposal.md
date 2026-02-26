# 初次使用引导配置

## Why

用户首次使用 AI 助手时，需要进行基础配置才能正常使用。目前缺乏一个引导式的配置流程，导致新用户不知道如何开始，或者需要手动编辑配置文件。

我们需要一个友好的引导式配置体验，让用户快速完成必要的设置，同时为高级用户提供深度自定义选项。

## What Changes

### 新增功能

- **用户类型选择**：在引导开始时询问用户偏好
  - **快速模式**：仅需 3 步基础配置，适合想要快速开始的用户
  - **专家模式**：5 步完整配置，适合需要深度自定义的用户

- **配置阶段**（按顺序）：
  1. **语言设置**：选择系统交互语言（中文/英文）
  2. **LLM 配置**：设置 API Key、Model、Base URL、Provider 等
  3. **AI 人格设置**：配置 AI 的行为风格和回复方式
  4. **记忆模式**（仅专家模式）：选择 AI 的记忆策略
  5. **工具配置**（仅专家模式）：启用/禁用可用工具

- **配置页面**：完整的配置管理界面，支持随时修改已设置的选项

### 用户体验

- 快速模式：仅显示步骤 1-3 的简化版本，减少认知负担
- 专家模式：展示所有配置项的完整版本
- 引导完成后可随时通过配置页面修改设置

## Capabilities

### New Capabilities

- `onboarding-flow`：初次使用引导流程，包括用户类型选择和分步配置向导
- `settings-page`：完整的配置管理页面，支持查看和修改所有设置项
- `language-settings`：语言设置能力，支持中文/英文切换，切换后实时生效
- `llm-config`：LLM 提供商配置能力（API Key、Model、Base URL、Provider）
- `ai-personality`：AI 人格配置能力
- `memory-mode`：记忆模式配置能力
- `tool-management`：工具启用/禁用管理能力

### Modified Capabilities

无（这是新功能）

## Impact

### 新增文件

- `frontend/src/pages/Onboarding.tsx` - 引导流程页面
- `frontend/src/pages/Settings.tsx` - 配置管理页面
- `frontend/src/components/onboarding/` - 引导流程相关组件
- `frontend/src/components/settings/` - 配置页面相关组件

### 配置存储

- 用户配置需要持久化存储（localStorage 或后端存储）
- 需要定义配置项的数据结构

### 依赖

- 可能需要新建后端 API 用于配置存储（如果需要服务端持久化）
