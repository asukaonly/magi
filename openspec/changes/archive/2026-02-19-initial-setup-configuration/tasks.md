# 实现任务清单

## 1. 后端 API 扩展

- [ ] 1.1 扩展 SystemConfig 模型，新增 `preferences`、`personality`、`tools`、`memory_layers` 字段
- [ ] 1.2 扩展 LLM 配置，新增 GLM 提供商和 Custom 提供商（name/base_url/api_key/api_format）
- [ ] 1.3 实现 `/api/personalities` 端点，从 `backend/personalities/{language}/` 读取人格预设文件
- [ ] 1.4 实现 `/api/skills` 端点，返回可用 Skills 列表
- [ ] 1.5 更新 `/api/config` 端点，支持新增的配置字段读写

## 2. 前端类型定义

- [ ] 2.1 扩展 `SystemConfig` 类型，添加 `UserPreferences` 接口（onboarding_completed, user_mode, language）
- [ ] 2.2 扩展 `LLMConfig` 类型，支持 GLM 和 Custom 提供商（custom_name, api_format）
- [ ] 2.3 定义 `PersonalityConfig` 类型（preset, custom_prompt, tone）
- [ ] 2.4 定义 `ToolsConfig` 类型：
  - weather: enabled, provider, apiKey, apiUrl
  - webSearch: enabled, provider, apiKey
  - webFetch: enabled, usePlaywright
  - skills: string[]
- [ ] 2.5 定义 `MemoryLayersConfig` 类型：
  - L1: enabled（固定 SQLite）
  - L2: enabled, backend, graphRules
  - L3: enabled, deployment, backend(sqlite_vec), model, modelStatus
  - L4: enabled, summaryTypes
  - L5: enabled
- [ ] 2.6 定义 `OnboardingStep` 和 `OnboardingState` 类型

## 3. API 客户端

- [ ] 3.1 新增 `personalitiesApi` 模块，封装人格预设列表获取（支持语言参数）
- [ ] 3.2 新增 `skillsApi` 模块，封装 Skills 列表获取
- [ ] 3.3 更新 `configApi`，支持新增配置字段的读写

## 4. 可复用表单组件

- [ ] 4.1 创建 `LanguageForm` 组件 - 语言选择表单（中文/英文）
- [ ] 4.2 创建 `LLMForm` 组件：
  - 提供商选择（OpenAI/Anthropic/GLM/Custom）
  - Custom 提供商显示额外字段（name/base_url/api_format）
  - 快速模式仅显示必填项
- [ ] 4.3 创建 `PersonalityForm` 组件：
  - 从后端加载预设人格列表
  - 根据当前语言显示对应描述
  - 自定义提示词输入
- [ ] 4.4 创建 `MemoryForm` 组件（最复杂）：
  - L1 开关（其他层依赖提示）
  - L2 backend 选择 + 图关系规则输入
  - L3 部署方式 + 模型选择 + 模型下载功能
  - L4 摘要类型多选
  - L5 开关
- [ ] 4.5 创建 `ToolsForm` 组件：
  - 天气工具：服务商选择 + API Key/URL 配置
  - 网页搜索：服务商选择（DuckDuckGo 不需要 Key）+ API Key
  - 网页获取：Playwright 开关

## 5. 引导流程页面

- [ ] 5.1 创建 `OnboardingPage` 页面容器（独立布局，无 MainLayout）
- [ ] 5.2 创建 `ModeSelection` 组件 - 快速/专家模式选择
- [ ] 5.3 创建 `StepIndicator` 组件 - 步骤指示器（根据模式显示不同步数）
- [ ] 5.4 创建 `OnboardingFlow` 组件 - 引导流程状态机和步骤控制
- [ ] 5.5 创建 `CompletionScreen` 组件 - 引导完成页面
- [ ] 5.6 实现引导状态持久化（中途退出后恢复）

## 6. 配置页面重构

- [ ] 6.1 重构 `SettingsPage`，使用新的 Tab 分类结构
- [ ] 6.2 集成可复用表单组件到配置页面
- [ ] 6.3 新增"偏好设置"Tab（语言、用户模式）
- [ ] 6.4 新增"AI 人格"Tab（加载预设 + 自定义）
- [ ] 6.5 新增"记忆配置"Tab（L1-L5 完整配置）
- [ ] 6.6 新增"工具管理"Tab（三个内置工具 + Skills 开关）

## 7. 路由和守卫

- [ ] 7.1 添加 `/onboarding` 路由（独立布局）
- [ ] 7.2 实现首次使用检测逻辑（检查 onboarding_completed）
- [ ] 7.3 实现路由守卫：未完成引导时自动跳转到 /onboarding
- [ ] 7.4 实现语言切换后的页面刷新逻辑

## 8. 模型下载功能（L3 记忆）

- [ ] 8.1 实现本地 embedding 模型下载 API
- [ ] 8.2 实现模型下载进度显示
- [ ] 8.3 实现已下载模型的检测和状态显示

## 9. 测试和验证

- [ ] 9.1 测试首次用户引导流程（快速模式）
- [ ] 9.2 测试首次用户引导流程（专家模式）
- [ ] 9.3 测试中途退出引导后恢复
- [ ] 9.4 测试配置页面各项配置的保存和读取
- [ ] 9.5 测试语言切换功能
- [ ] 9.6 测试记忆层依赖关系（L1 关闭时其他层不可启用）
- [ ] 9.7 测试各工具配置的正确保存
