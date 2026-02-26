# 技术设计文档

## Context

### 背景

项目是一个 AI 助手应用，当前已有基础的配置管理功能：
- 后端 API：`/config` 提供 CRUD 操作
- 前端页面：Settings 页面展示和编辑配置

### 当前状态

- **路由**：使用 react-router-dom，所有页面在 MainLayout 下
- **配置结构**：`SystemConfig` 包含 agent、llm、loop、message_bus、memory、websocket、log
- **缺失**：无首次使用检测、无引导流程、无语言/i18n 支持

### 约束

- 不依赖特定 UI 库（UI 库后续可能更换）
- 需要支持中英文切换
- 配置需要持久化

## Goals / Non-Goals

**Goals:**

1. 实现首次使用检测和引导流程
2. 扩展配置结构，支持语言、AI 人格、工具管理
3. 引导流程支持快速模式（3 步）和专家模式（5 步）
4. 配置页面支持随时修改所有设置

**Non-Goals:**

1. 不做国际化框架迁移（假设已有或后续单独处理）
2. 不做配置版本管理和迁移
3. 不做多用户/多配置 profile

## Decisions

### D1: 首次使用检测

**方案**: 在配置中增加 `onboarding_completed` 字段

```typescript
interface UserPreferences {
  onboarding_completed: boolean;
  user_mode: 'quick' | 'expert' | null;  // 用户选择的模式
  language: 'zh' | 'en';
}
```

**流程**:
1. 应用启动时检查 `onboarding_completed`
2. 若为 `false` 或不存在，跳转 `/onboarding`
3. 引导完成后设置为 `true`

**备选方案**:
- A: 使用 localStorage（纯前端）→ 不考虑，配置应统一管理
- B: 后端维护用户状态表 → 过度设计，当前单用户场景不需要

### D2: 引导流程状态机

**方案**: 使用步骤索引 + 模式控制

```typescript
type OnboardingStep =
  | 'mode-selection'   // 0: 选择快速/专家模式
  | 'language'         // 1: 语言设置
  | 'llm'              // 2: LLM 配置
  | 'personality'      // 3: AI 人格
  | 'memory'           // 4: 记忆模式（仅专家）
  | 'tools'            // 5: 工具配置（仅专家）
  | 'complete';        // 完成

interface OnboardingState {
  currentStep: OnboardingStep;
  mode: 'quick' | 'expert' | null;
  completedSteps: Set<OnboardingStep>;
}
```

**步骤序列**:
- 快速模式: `mode-selection` → `language` → `llm` → `personality` → `complete`
- 专家模式: `mode-selection` → `language` → `llm` → `personality` → `memory` → `tools` → `complete`

### D3: 配置结构扩展

**方案**: 扩展现有 `SystemConfig`，新增模块

```typescript
interface SystemConfig {
  // 现有字段...
  agent: AgentConfig;
  llm: LLMConfig;
  loop: LoopConfig;
  message_bus: MessageBusConfig;
  memory: MemoryConfig;
  websocket: WebSocketConfig;
  log: LogConfig;

  // 新增字段
  preferences: UserPreferences;      // 用户偏好（语言、模式等）
  personality: PersonalityConfig;    // AI 人格
  tools: ToolsConfig;                // 工具配置
}

interface LLMConfig {
  provider: 'openai' | 'anthropic' | 'glm' | 'custom';
  model: string;
  api_key?: string;
  base_url?: string;
  // custom provider 专用
  custom_name?: string;
  api_format?: 'openai' | 'anthropic' | 'custom';
}

interface PersonalityConfig {
  preset?: string;                   // 预设人格 ID（从后端获取）
  custom_prompt?: string;            // 自定义人格提示词
  tone?: 'casual' | 'formal';
}

interface ToolsConfig {
  builtIn: {
    weather: {
      enabled: boolean;
      provider: 'openweather' | 'qweather';
      apiKey?: string;
      apiUrl?: string;              // 和风天气专用
    };
    webSearch: {
      enabled: boolean;
      provider: 'duckduckgo' | 'brave' | 'perplexity' | 'tavily' | 'google';
      apiKey?: string;              // DuckDuckGo 不需要
    };
    webFetch: {
      enabled: boolean;
      usePlaywright: boolean;       // 是否使用 Playwright 浏览器渲染
    };
  };
  skills: string[];                  // 启用的外部 skill ID 列表（从后端获取）
}

// 记忆层配置（替换原有 memory 配置）
interface MemoryLayersConfig {
  L1: {
    enabled: boolean;
    // 固定使用本地 SQLite，无需配置 backend
  };
  L2: {
    enabled: boolean;
    backend: 'sqlite_networkx' | 'kuzu';
    graphRules?: string;           // 自定义图关系生成规则
  };
  L3: {
    enabled: boolean;
    deployment: 'local' | 'remote';
    backend: 'sqlite_vec';         // 向量数据库实现固定为 sqlite-vec
    model?: string;                // 模型名称
    // 本地部署时的模型下载状态
    modelStatus?: 'not_downloaded' | 'downloading' | 'ready';
  };
  L4: {
    enabled: boolean;
    // 固定 SQLite
    summaryTypes: ('user_events' | 'ai_tool_execution' | 'external_perception')[];
  };
  L5: {
    enabled: boolean;
    // 暂时只有开关
  };
}
```

### D4: 组件架构

**方案**: 引导步骤与配置页面共用表单组件

```
components/
├── config-forms/           # 可复用的配置表单组件
│   ├── LanguageForm.tsx    # 语言选择
│   ├── LLMForm.tsx         # LLM 配置
│   ├── PersonalityForm.tsx # 人格配置
│   ├── MemoryForm.tsx      # 记忆配置
│   └── ToolsForm.tsx       # 工具配置
├── onboarding/
│   ├── OnboardingFlow.tsx  # 引导流程容器
│   ├── ModeSelection.tsx   # 模式选择
│   ├── StepIndicator.tsx   # 步骤指示器
│   └── CompletionScreen.tsx # 完成页面
└── settings/
    └── SettingsPage.tsx    # 配置页面（重构）
```

**关键点**:
- `config-forms/` 中的组件是纯表单，不包含布局
- `onboarding/` 负责引导流程的布局和步骤控制
- `settings/` 负责配置页面的布局，复用 `config-forms/`

### D5: 路由设计

**方案**: 添加独立引导路由，不经过 MainLayout

```typescript
const routes = [
  {
    path: '/onboarding',
    element: <OnboardingPage />,  // 独立布局，无侧边栏
  },
  {
    path: '/',
    element: <MainLayout />,
    children: [
      // 现有路由...
    ],
  },
];
```

**守卫逻辑**:
```typescript
// 在 App 或路由层
if (!preferences.onboarding_completed && location.pathname !== '/onboarding') {
  return <Navigate to="/onboarding" replace />;
}
```

## Risks / Trade-offs

| 风险 | 缓解措施 |
|------|----------|
| 配置结构变更导致后端兼容性问题 | 后端忽略未知字段，前端处理缺失字段的默认值 |
| 用户中途退出引导 | 保存已完成的步骤，下次继续 |
| UI 库更换导致组件重写 | 表单组件只负责数据，不依赖 UI 库特定 API |

## Open Questions

~~1. **工具列表从哪里获取？**~~ ✅ 已确认：
- 内置工具：前端固定配置项，只需开关
- 外部 Skills：需要后端 API 返回列表，目前只做开关

~~2. **记忆模式具体有哪些选项？**~~ ✅ 已确认：
- L2-L5 四层记忆，各层独立开关
- 各层有不同的 backend 选项（memory/sqlite/chromadb/redis）

~~3. **语言切换是否需要刷新页面？**~~ ✅ 已确认：
- 需要刷新页面
