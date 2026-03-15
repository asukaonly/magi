# Magi Frontend 重构方案

> 文档版本: 1.0
> 创建日期: 2026-03-15
> 状态: 待评审

---

## 目录

1. [背景与目标](#1-背景与目标)
2. [当前问题清单](#2-当前问题清单)
3. [改进方案](#3-改进方案)
4. [实施计划](#4-实施计划)
5. [风险与应对](#5-风险与应对)
6. [验收标准](#6-验收标准)
7. [附录](#7-附录)

---

## 1. 背景与目标

### 1.1 现状描述

Magi Frontend 是一个基于 React 18 + TypeScript + Vite 的 AI Agent 框架前端应用，同时支持 Web 和 Tauri 桌面端。当前代码库约 **18,820 行** TypeScript/TSX 代码，包含 **23 个测试文件**。

### 1.2 触发原因

- **开发效率下降**: 新功能开发时需要在多个巨型组件中定位逻辑
- **代码复用困难**: 缺少 hooks 抽象层，相似逻辑在多处重复
- **维护成本增加**: 组件职责不清，修改一处容易引入 bug
- **类型安全隐患**: 大量 `any` 类型导致运行时错误风险
- **新人上手困难**: 缺乏清晰的架构分层和文档

### 1.3 目标

| 指标 | 当前值 | 目标值 |
|------|--------|--------|
| 最大单文件行数 | 1,476 行 (Settings.tsx) | ≤ 400 行 |
| `any` 类型使用 | 约 15 处 | 0 处 |
| 自定义 Hooks 数量 | 1 个 | ≥ 8 个 |
| 组件与 Store 耦合度 | 高（直接 import） | 低（通过 hooks） |
| 测试覆盖率 | 未统计 | ≥ 70% 核心逻辑 |

### 1.4 不做的事

- ❌ 不更换技术栈（React, Zustand, Axios 等保持不变）
- ❌ 不重写现有功能，仅做结构优化
- ❌ 不改变用户界面和交互逻辑
- ❌ 不修改后端 API 契约

---

## 2. 当前问题清单

### 2.1 🔴 阻塞型问题（必须修复）

#### P0-1: 巨型组件难以维护

**影响文件:**
- `src/pages/Settings.tsx` (1,476 行)
- `src/pages/PersonalityModern.tsx` (816 行)
- `src/pages/Events.tsx` (772 行)

**具体表现:**
```tsx
// Settings.tsx 包含了多个不相关的职责:
// 1. LLM 配置管理
// 2. 插件管理
// 3. 主题切换
// 4. 语言切换
// 5. 工具配置
// 6. 时间线源配置
// 全部混在一个组件中
```

**当前影响:** 修改任一配置项需要阅读全部代码，极易引入回归 bug

---

#### P0-2: 缺少 Custom Hooks 抽象层

**影响范围:** 全局

**具体表现:**
```tsx
// Chat.tsx 中直接包含大量业务逻辑
const handleWSMessage = useCallback((data: WSMessage) => {
  // 70+ 行的消息处理逻辑
  // 8 种消息类型的 switch-case
  // 直接操作多个 store
}, [/* 10+ dependencies */]);
```

**当前影响:**
- 逻辑无法复用
- 难以单独测试
- 组件渲染与业务逻辑混杂

---

#### P0-3: 类型安全隐患

**影响文件:**
- `src/api/client.ts`
- `src/pages/Chat.tsx`
- `src/stores/conversation-store.ts`

**具体表现:**
```typescript
// api/client.ts - 泛型默认为 any
export const api = {
  get: <T = any>(url: string, paramsOrConfig?: any) => ...
  post: <T = any>(url: string, data?: any, config?: any) => ...
};

// Chat.tsx - 动态访问未知属性
if (data.data?.session_id) {
  const nextSession = String(data.data.session_id);
}
```

**当前影响:** 失去 TypeScript 静态检查能力，运行时错误风险高

---

### 2.2 🟡 改进型问题（应该修复）

#### P1-1: 模块级可变状态

**影响文件:** `src/api/client.ts`

**具体表现:**
```typescript
// 模块级可变变量
let desktopSessionToken: string | undefined;

export const configureApiClient = (options) => {
  desktopSessionToken = options.sessionToken; // 直接修改
};
```

**当前影响:** 状态变更难以追踪，测试时需要手动重置

---

#### P1-2: 业务逻辑位置不当

**影响文件:** `src/pages/chat-state.ts`

**具体表现:**
```
pages/
  Chat.tsx
  chat-state.ts    <-- 应该在 domain/ 或 lib/ 中
  chat-route-helpers.ts
```

`chat-state.ts` 包含数据规范化、状态转换等通用逻辑，但放在 `pages/` 下，暗示它只服务于 Chat 页面。

**当前影响:** 其他模块复用这些逻辑时会产生不当的 import 依赖

---

#### P1-3: 组件与 Store 紧耦合

**影响文件:** `src/pages/Chat.tsx`, `src/pages/Settings.tsx`

**具体表现:**
```tsx
// Chat.tsx 直接导入 8 个 store selectors
const connected = useRealtimeStore((state) => state.connected);
const currentSessionId = useConversationStore((state) => state.currentSessionId);
const setCurrentSessionId = useConversationStore((state) => state.setCurrentSessionId);
const messages = useConversationStore((state) => ...);
const appendPendingTurn = useConversationStore((state) => state.appendPendingTurn);
// ...更多
```

**当前影响:** 组件难以在隔离环境中测试，难以复用到其他上下文

---

#### P1-4: 硬编码常量分散

**影响文件:** 多处

**具体表现:**
```typescript
// Chat.tsx
const USER_ID = 'web_user';
const MEMORY_CLEARED_EVENT = 'magi-memory-cleared';

// realtime/client.ts
const MAX_RECONNECT_ATTEMPTS = 10;
const BASE_RECONNECT_DELAY = 1000;

// api/client.ts
timeout: 30000, // 硬编码
```

**当前影响:** 修改配置需要搜索多个文件，容易遗漏

---

#### P1-5: 不一致的错误处理

**影响范围:** 全局

**具体表现:**
```typescript
// 方式 1: 显示 toast
catch { toast.error(t('personality.loadFailed')); }

// 方式 2: 静默失败
catch { /* Ignore malformed payloads */ }

// 方式 3: 设置默认值继续
catch { setList([{ name: 'default', displayName: 'default' }]); }
```

**当前影响:** 用户无法得知某些操作失败的原因，调试困难

---

### 2.3 🟢 优化型问题（可以修复）

#### P2-1: Store 中业务逻辑过重

**影响文件:** `src/stores/conversation-store.ts`

**具体表现:**
```typescript
// 200+ 行的 store 定义中包含复杂的状态派生逻辑
const upsertSessionSummary = (sessionsById, orderedSessionIds, session) => {
  const nextOrder = orderedSessionIds.filter(...);
  // ...复杂的业务逻辑
};
```

**当前影响:** Store 文件本身变得臃肿，难以理解状态结构

---

#### P2-2: 缺少统一的 Service 层

**影响范围:** API 调用相关

**具体表现:**
```typescript
// 组件直接调用 API
const result = await personalityApi.list();
const detail = await personalityApi.get(name);
```

**当前影响:**
- 无法统一处理缓存
- 无法统一处理重试逻辑
- 错误处理分散在各组件

---

## 3. 改进方案

### 3.1 引入 Custom Hooks 层

**目标:** 将组件中的业务逻辑抽取为可复用的 hooks

**新增目录结构:**
```
src/
  hooks/
    useChat.ts           # 聊天消息处理
    useWebSocket.ts      # WebSocket 连接管理
    usePersonality.ts    # 人格配置管理
    useSettings.ts       # 设置页面状态管理
    useTheme.ts          # 主题切换（已存在部分）
    useApi.ts            # 通用 API 请求状态
    useLocalStorage.ts   # 本地存储抽象
    index.ts             # 统一导出
```

**示例改造 - useChat:**
```typescript
// src/hooks/useChat.ts
import { useCallback, useRef } from 'react';
import { useConversationStore, useRealtimeStore } from '@/stores';
import { useRealtime } from '@/realtime/provider';
import type { WSMessage } from '@/types';

export interface UseChatOptions {
  userId?: string;
}

export interface UseChatReturn {
  messages: ChatTimelineMessage[];
  connected: boolean;
  sendMessage: (content: string) => void;
  loadHistory: (sessionId: string) => void;
}

export function useChat(options: UseChatOptions = {}): UseChatReturn {
  const { userId = 'web_user' } = options;

  // 从 store 获取状态
  const currentSessionId = useConversationStore(s => s.currentSessionId);
  const messages = useConversationStore(s =>
    currentSessionId ? s.messagesBySession[currentSessionId] ?? [] : []
  );
  const connected = useRealtimeStore(s => s.connected);

  // 获取 actions
  const setCurrentSessionId = useConversationStore(s => s.setCurrentSessionId);
  const appendPendingTurn = useConversationStore(s => s.appendPendingTurn);
  const receiveAgentResponse = useConversationStore(s => s.receiveAgentResponse);

  const { send, subscribe } = useRealtime();
  const lastHistoryRequestRef = useRef<string | null>(null);

  // 消息处理逻辑
  const handleWSMessage = useCallback((data: WSMessage) => {
    // ... 抽取后的消息处理逻辑
  }, [/* 精简的依赖 */]);

  // 发送消息
  const sendMessage = useCallback((content: string) => {
    if (!content.trim() || !connected) return;

    const turnId = createClientTurnId();
    appendPendingTurn({ sessionId: currentSessionId, input: content, turnId, ... });
    send({ type: 'send_message', message: content, client_turn_id: turnId });
  }, [connected, currentSessionId, appendPendingTurn, send]);

  return {
    messages,
    connected,
    sendMessage,
    loadHistory,
  };
}
```

**改造后的 Chat.tsx:**
```typescript
// src/pages/Chat.tsx
import { useChat } from '@/hooks';

export const ChatPage: React.FC = () => {
  const { messages, connected, sendMessage } = useChat();
  const [inputValue, setInputValue] = useState('');

  // 组件现在只负责渲染
  return (
    <div>
      {messages.map(msg => <MessageCard key={msg.id} message={msg} />)}
      <ChatInput
        value={inputValue}
        onChange={setInputValue}
        onSubmit={sendMessage}
        disabled={!connected}
      />
    </div>
  );
};
```

**预期收益:**
- Chat.tsx 从 531 行减少到约 150 行
- 消息处理逻辑可独立测试
- 其他页面可复用聊天功能

---

### 3.2 拆分巨型组件

**目标:** 将 Settings.tsx (1,476 行) 拆分为独立的功能模块

**当前结构:**
```
pages/
  Settings.tsx (1,476 行，包含所有配置)
```

**目标结构:**
```
pages/
  Settings.tsx (约 100 行，仅作为路由容器和布局)

components/settings/
  SettingsLayout.tsx       # 布局和导航
  sections/
    GeneralSection.tsx     # 通用设置（主题、语言）
    LLMSection.tsx         # LLM 配置
    PluginsSection.tsx     # 插件管理
    ToolsSection.tsx       # 工具配置
    MemorySection.tsx      # 内存配置
    TimelineSection.tsx    # 时间线源配置
    AboutSection.tsx       # 关于页面
  index.ts
```

**示例 - Settings.tsx 改造后:**
```typescript
// src/pages/Settings.tsx
import { SettingsLayout } from '@/components/settings';

const SETTINGS_SECTIONS = [
  { id: 'general', label: 'General', component: GeneralSection },
  { id: 'llm', label: 'LLM', component: LLMSection },
  { id: 'plugins', label: 'Plugins', component: PluginsSection },
  { id: 'tools', label: 'Tools', component: ToolsSection },
  { id: 'memory', label: 'Memory', component: MemorySection },
  { id: 'timeline', label: 'Timeline', component: TimelineSection },
  { id: 'about', label: 'About', component: AboutSection },
] as const;

export const SettingsPage: React.FC = () => {
  const [activeSection, setActiveSection] = useState('general');

  return (
    <SettingsLayout
      sections={SETTINGS_SECTIONS}
      activeSection={activeSection}
      onSectionChange={setActiveSection}
    />
  );
};
```

**预期收益:**
- 每个配置模块独立维护
- 可按需加载（lazy loading）
- 各 section 可独立测试

---

### 3.3 建立类型安全层

**目标:** 消除所有 `any` 类型，建立完整的类型定义

**新增目录结构:**
```
src/
  types/
    api.ts              # API 响应类型
    chat.ts             # 聊天相关类型
    personality.ts      # 人格配置类型
    settings.ts         # 设置相关类型
    websocket.ts        # WebSocket 消息类型
    index.ts            # 统一导出
```

**示例 - websocket.ts:**
```typescript
// src/types/websocket.ts

export type WSMessageType =
  | 'subscribed'
  | 'current_session'
  | 'history'
  | 'personality_info'
  | 'message_sent'
  | 'execution_trace_update'
  | 'agent_response'
  | 'error';

export interface WSMessageBase<T extends WSMessageType, D = unknown> {
  type: T;
  data?: D;
  message?: string;
}

export interface WSSubscribedData {
  channel: string;
}

export interface WSCurrentSessionData {
  session_id: string;
}

export interface WSHistoryData {
  session_id: string;
  messages: ChatHistoryMessage[];
}

// ... 为每种消息类型定义 data 结构

export type WSMessage =
  | WSMessageBase<'subscribed', WSSubscribedData>
  | WSMessageBase<'current_session', WSCurrentSessionData>
  | WSMessageBase<'history', WSHistoryData>
  | WSMessageBase<'error', { code: string }>
  // ... 其他类型
```

**改造后的消息处理:**
```typescript
// 之前
const handleWSMessage = useCallback((data: WSMessage) => {
  if (data.data?.session_id) { ... }  // any，无类型提示
}, []);

// 之后
const handleWSMessage = useCallback((message: WSMessage) => {
  switch (message.type) {
    case 'current_session':
      // TypeScript 知道 message.data 是 WSCurrentSessionData
      const sessionId = message.data?.session_id;
      break;
    case 'error':
      // TypeScript 知道 message.message 存在
      toast.error(message.message);
      break;
  }
}, []);
```

**预期收益:**
- 编译时捕获类型错误
- 更好的 IDE 自动补全
- 重构时自动更新所有引用

---

### 3.4 集中管理常量

**目标:** 将分散的常量集中到统一位置

**新增文件:**
```
src/
  constants/
    app.ts              # 应用级常量
    api.ts              # API 相关常量
    websocket.ts        # WebSocket 常量
    events.ts           # 自定义事件名称
    index.ts
```

**示例 - constants/websocket.ts:**
```typescript
// src/constants/websocket.ts

export const WS_CONFIG = {
  MAX_RECONNECT_ATTEMPTS: 10,
  BASE_RECONNECT_DELAY_MS: 1000,
  MAX_RECONNECT_DELAY_MS: 30000,
  CONNECTION_TIMEOUT_MS: 5000,
} as const;

export const WS_EVENTS = {
  SUBSCRIBED: 'subscribed',
  CURRENT_SESSION: 'current_session',
  HISTORY: 'history',
  // ...
} as const;
```

**示例 - constants/events.ts:**
```typescript
// src/constants/events.ts

export const APP_EVENTS = {
  MEMORY_CLEARED: 'magi-memory-cleared',
  SESSION_SYNC: 'magi-session-sync',
  THEME_CHANGED: 'magi-theme-changed',
  LANGUAGE_CHANGED: 'magi-language-changed',
} as const;
```

---

### 3.5 引入 Service 层

**目标:** 封装 API 调用，统一处理缓存、错误、重试

**新增目录结构:**
```
src/
  services/
    chat.service.ts     # 聊天相关 API 封装
    config.service.ts   # 配置相关 API 封装
    base.service.ts     # 基础服务类
    index.ts
```

**示例 - base.service.ts:**
```typescript
// src/services/base.service.ts

export interface ServiceOptions {
  useCache?: boolean;
  cacheTTL?: number;
  retryCount?: number;
  retryDelay?: number;
}

export abstract class BaseService {
  protected cache = new Map<string, { data: unknown; expiry: number }>();

  protected async withCache<T>(
    key: string,
    fetcher: () => Promise<T>,
    ttl: number = 60000
  ): Promise<T> {
    const cached = this.cache.get(key);
    if (cached && cached.expiry > Date.now()) {
      return cached.data as T;
    }

    const data = await fetcher();
    this.cache.set(key, { data, expiry: Date.now() + ttl });
    return data;
  }

  protected async withRetry<T>(
    fetcher: () => Promise<T>,
    retries: number = 3,
    delay: number = 1000
  ): Promise<T> {
    let lastError: Error | undefined;
    for (let i = 0; i < retries; i++) {
      try {
        return await fetcher();
      } catch (error) {
        lastError = error as Error;
        if (i < retries - 1) {
          await new Promise(resolve => setTimeout(resolve, delay * Math.pow(2, i)));
        }
      }
    }
    throw lastError;
  }
}
```

**示例 - chat.service.ts:**
```typescript
// src/services/chat.service.ts
import { BaseService, ServiceOptions } from './base.service';
import { messagesApi } from '@/api';
import type { ChatHistoryMessage, ExecutionTraceSnapshot } from '@/types';

class ChatService extends BaseService {
  private readonly CACHE_TTL = 30000; // 30 seconds

  async getHistory(
    userId: string,
    sessionId: string,
    options?: ServiceOptions
  ): Promise<ChatHistoryMessage[]> {
    const cacheKey = `history:${userId}:${sessionId}`;

    if (options?.useCache !== false) {
      return this.withCache(cacheKey, () =>
        messagesApi.getHistory(userId, sessionId).then(r => r.data ?? []),
      this.CACHE_TTL);
    }

    return messagesApi.getHistory(userId, sessionId).then(r => r.data ?? []);
  }

  async getTrace(
    userId: string,
    sessionId: string,
    turnId: string,
    options?: ServiceOptions
  ): Promise<ExecutionTraceSnapshot | null> {
    return this.withRetry(
      () => messagesApi.getTrace(userId, sessionId, turnId).then(r => r.trace ?? null),
      options?.retryCount ?? 2
    );
  }

  invalidateHistoryCache(userId: string, sessionId: string): void {
    this.cache.delete(`history:${userId}:${sessionId}`);
  }
}

export const chatService = new ChatService();
```

---

### 3.6 移动业务逻辑到领域层

**目标:** 将 `pages/chat-state.ts` 移动到更合适的位置

**变更:**
```
# 之前
src/pages/chat-state.ts

# 之后
src/domain/chat/
  types.ts              # 聊天相关类型
  normalizers.ts        # 数据规范化函数
  transformers.ts       # 状态转换函数
  index.ts
```

**示例结构:**
```typescript
// src/domain/chat/types.ts
export type ChatMessageKind = 'user' | 'assistant' | 'status';

export interface ChatTimelineMessage {
  id: string;
  role: 'user' | 'assistant';
  kind: ChatMessageKind;
  content: string;
  timestamp: number;
  turnId?: string;
  traceSummary?: NormalizedExecutionTraceSummary | null;
  traceAvailable?: boolean;
}

// ... 其他类型

// src/domain/chat/normalizers.ts
export const normalizeTraceSummary = (raw: unknown): NormalizedExecutionTraceSummary | null => {
  // ... 现有逻辑
};

export const normalizeHistoryMessages = (messages: ChatHistoryMessage[]): ChatTimelineMessage[] => {
  // ... 现有逻辑
};

// src/domain/chat/index.ts
export * from './types';
export * from './normalizers';
export * from './transformers';
```

---

### 3.7 统一错误处理策略

**目标:** 建立一致的错误处理模式

**新增文件:**
```
src/
  utils/
    error-handler.ts    # 统一错误处理
```

**示例:**
```typescript
// src/utils/error-handler.ts

export type ErrorSeverity = 'info' | 'warning' | 'error' | 'critical';

export interface AppError {
  message: string;
  code: string;
  severity: ErrorSeverity;
  details?: unknown;
}

export function handleApiError(error: unknown, context?: string): AppError {
  // 网络错误
  if (!navigator.onLine) {
    return {
      message: 'Network unavailable. Please check your connection.',
      code: 'NETWORK_OFFLINE',
      severity: 'warning',
    };
  }

  // API 返回的错误
  if (isApiErrorResponse(error)) {
    const severity = error.status === 401 ? 'critical' : 'error';
    return {
      message: error.message,
      code: error.code,
      severity,
      details: error.details,
    };
  }

  // 未知错误
  return {
    message: context ? `${context} failed` : 'An unexpected error occurred',
    code: 'UNKNOWN_ERROR',
    severity: 'error',
    details: error,
  };
}

export function showError(error: AppError): void {
  switch (error.severity) {
    case 'info':
      toast.info(error.message);
      break;
    case 'warning':
      toast.warning(error.message);
      break;
    case 'error':
    case 'critical':
      toast.error(error.message);
      break;
  }

  // 开发环境打印详细信息
  if (import.meta.env.DEV && error.details) {
    console.error(`[${error.code}]`, error.details);
  }
}
```

**使用示例:**
```typescript
// 之前
try {
  await personalityApi.switch(selectedName);
} catch {
  toast.error(t('personality.switchFailed'));  // 静默忽略错误详情
}

// 之后
try {
  await personalityApi.switch(selectedName);
} catch (error) {
  const appError = handleApiError(error, 'Personality switch');
  showError(appError);
}
```

---

## 4. 实施计划

### 4.1 阶段划分

```
Phase 1: 基础设施 (Week 1-2)
├── 建立类型定义层
├── 集中管理常量
└── 统一错误处理

Phase 2: Hooks 抽取 (Week 3-4)
├── useChat
├── usePersonality
├── useSettings
└── 其他 hooks

Phase 3: 组件拆分 (Week 5-7)
├── Settings.tsx 拆分
├── PersonalityModern.tsx 拆分
└── Events.tsx 拆分

Phase 4: Service 层 (Week 8)
├── BaseService 实现
├── ChatService
└── ConfigService

Phase 5: 清理与优化 (Week 9-10)
├── 移动 domain 层
├── 消除遗留 any
└── 补充测试
```

### 4.2 详细任务清单

#### Phase 1: 基础设施

| 任务 | 预估时间 | 优先级 | 依赖 |
|------|----------|--------|------|
| 创建 `src/types/` 目录结构 | 2h | P0 | - |
| 定义 WebSocket 消息类型 | 4h | P0 | types 目录 |
| 定义 API 响应类型 | 4h | P0 | types 目录 |
| 创建 `src/constants/` 目录 | 2h | P1 | - |
| 迁移 WebSocket 常量 | 1h | P1 | constants 目录 |
| 迁移应用事件常量 | 1h | P1 | constants 目录 |
| 创建 `error-handler.ts` | 4h | P1 | - |
| 更新 API client 使用新类型 | 4h | P0 | types |

#### Phase 2: Hooks 抽取

| 任务 | 预估时间 | 优先级 | 依赖 |
|------|----------|--------|------|
| 创建 `src/hooks/` 目录 | 0.5h | P0 | - |
| 实现 `useChat` hook | 6h | P0 | Phase 1 完成 |
| 重构 Chat.tsx 使用 useChat | 4h | P0 | useChat |
| 实现 `usePersonality` hook | 4h | P1 | - |
| 重构 PersonalityModern.tsx | 4h | P1 | usePersonality |
| 实现 `useSettings` hook | 4h | P1 | - |
| 实现 `useLocalStorage` hook | 2h | P2 | - |
| 实现 `useApi` hook | 4h | P2 | - |

#### Phase 3: 组件拆分

| 任务 | 预估时间 | 优先级 | 依赖 |
|------|----------|--------|------|
| 创建 `components/settings/sections/` | 1h | P1 | - |
| 拆分 GeneralSection | 4h | P1 | - |
| 拆分 LLMSection | 6h | P1 | - |
| 拆分 PluginsSection | 4h | P1 | - |
| 拆分 ToolsSection | 4h | P1 | - |
| 拆分 MemorySection | 3h | P1 | - |
| 拆分 TimelineSection | 3h | P1 | - |
| 重构 Settings.tsx 为容器 | 2h | P1 | 所有 sections |
| 拆分 PersonalityModern.tsx | 8h | P2 | - |
| 拆分 Events.tsx | 6h | P2 | - |

#### Phase 4: Service 层

| 任务 | 预估时间 | 优先级 | 依赖 |
|------|----------|--------|------|
| 创建 `src/services/` 目录 | 0.5h | P2 | - |
| 实现 `BaseService` | 4h | P2 | - |
| 实现 `ChatService` | 6h | P2 | BaseService |
| 实现 `ConfigService` | 4h | P2 | BaseService |
| 迁移 API 调用到 Services | 6h | P2 | Services 完成 |

#### Phase 5: 清理与优化

| 任务 | 预估时间 | 优先级 | 依赖 |
|------|----------|--------|------|
| 创建 `src/domain/` 目录 | 0.5h | P2 | - |
| 移动 chat-state.ts 到 domain | 2h | P2 | - |
| 消除所有 any 类型 | 4h | P1 | Phase 1-3 |
| 添加 hooks 单元测试 | 8h | P1 | Phase 2 |
| 添加 domain 层测试 | 4h | P2 | domain 层 |
| 更新文档 | 4h | P2 | 所有阶段 |

### 4.3 依赖关系图

```
Phase 1 (基础设施)
    │
    ├─────────────────┐
    ▼                 ▼
Phase 2 (Hooks)   Phase 4 (Service)
    │                 │
    ├─────────────────┤
    ▼                 ▼
Phase 3 (拆分)     Phase 5 (清理)
    │                 │
    └────────┬────────┘
             ▼
         完成
```

---

## 5. 风险与应对

### 5.1 功能回归风险

**风险描述:** 重构过程中可能破坏现有功能

**应对策略:**
1. 每个阶段完成后运行完整测试套件
2. 关键路径添加 E2E 测试（Playwright）
3. 采用渐进式重构，每个 PR 只做一件事
4. 重构前后进行手动回归测试

**回滚策略:**
- 每个阶段创建独立分支
- 发现重大问题可直接 revert 整个阶段
- 保持 main 分支始终可发布

### 5.2 开发周期风险

**风险描述:** 实际工作量可能超出预估

**应对策略:**
1. 优先完成 P0 任务
2. P2 任务可视情况延后或取消
3. 每周进行进度评估和调整

### 5.3 团队协作风险

**风险描述:** 重构期间其他开发工作可能产生冲突

**应对策略:**
1. 重构期间减少大规模功能开发
2. 新功能开发基于重构后的结构
3. 保持频繁沟通，及时 rebase

### 5.4 性能风险

**风险描述:** 新增抽象层可能影响运行时性能

**应对策略:**
1. 使用 React DevTools Profiler 对比重构前后
2. 关键路径添加性能测试
3. 必要时使用 useMemo/useCallback 优化

---

## 6. 验收标准

### 6.1 定量指标

| 指标 | 验收标准 | 验证方式 |
|------|----------|----------|
| 最大文件行数 | ≤ 400 行 | `wc -l src/**/*.tsx \| sort -rn \| head -5` |
| any 类型数量 | 0 | `grep -r "any" src/ --include="*.ts" --include="*.tsx"` |
| 自定义 Hooks | ≥ 8 个 | `ls src/hooks/*.ts \| wc -l` |
| 测试覆盖率 | ≥ 70% | `npm run test -- --coverage` |
| TypeScript 编译 | 0 errors | `npm run type-check` |
| ESLint 警告 | 0 warnings | `npm run lint` |

### 6.2 定性指标

- [ ] 新功能开发时无需修改多个巨型文件
- [ ] 业务逻辑可通过 hooks 独立测试
- [ ] 新人能在 30 分钟内理解代码结构
- [ ] 组件 props 和 store 访问有完整类型提示
- [ ] 错误信息对用户友好且可追踪

### 6.3 验收流程

1. **代码审查:** 每个 Phase 完成后进行团队 Code Review
2. **自动化检查:** CI 通过所有测试和 lint
3. **功能验证:** 手动测试核心用户流程
4. **文档更新:** README 和架构图已更新

---

## 7. 附录

### 7.1 改造前后目录结构对比

**改造前:**
```
src/
├── api/
│   ├── client.ts
│   └── modules/
├── components/
│   ├── chat/
│   ├── config-forms/
│   ├── layout/
│   ├── onboarding/
│   ├── settings/
│   ├── timeline/
│   └── ui/
├── i18n/
├── lib/
├── pages/
│   ├── Chat.tsx          (531 行)
│   ├── Settings.tsx      (1,476 行)
│   ├── PersonalityModern.tsx (816 行)
│   ├── chat-state.ts     (业务逻辑混在 pages)
│   └── ...
├── realtime/
├── router/
├── runtime/
├── stores/
└── types/                (现有类型定义)
```

**改造后:**
```
src/
├── api/
│   ├── client.ts         (类型安全)
│   └── modules/
├── components/
│   ├── chat/
│   ├── config-forms/
│   ├── layout/
│   ├── onboarding/
│   ├── settings/
│   │   ├── sections/     (新增: 拆分的设置模块)
│   │   ├── SettingsLayout.tsx
│   │   └── index.ts
│   ├── timeline/
│   └── ui/
├── constants/            (新增: 集中管理常量)
│   ├── api.ts
│   ├── app.ts
│   ├── events.ts
│   ├── websocket.ts
│   └── index.ts
├── domain/               (新增: 领域逻辑)
│   ├── chat/
│   │   ├── types.ts
│   │   ├── normalizers.ts
│   │   └── index.ts
│   └── personality/
├── hooks/                (新增: 自定义 Hooks)
│   ├── useApi.ts
│   ├── useChat.ts
│   ├── useLocalStorage.ts
│   ├── usePersonality.ts
│   ├── useSettings.ts
│   ├── useTheme.ts
│   ├── useWebSocket.ts
│   └── index.ts
├── i18n/
├── lib/
├── pages/
│   ├── Chat.tsx          (约 150 行)
│   ├── Settings.tsx      (约 100 行)
│   ├── Personality.tsx   (约 200 行)
│   └── ...
├── realtime/
├── router/
├── runtime/
├── services/             (新增: Service 层)
│   ├── base.service.ts
│   ├── chat.service.ts
│   ├── config.service.ts
│   └── index.ts
├── stores/
├── types/                (扩充: 完整类型定义)
│   ├── api.ts
│   ├── chat.ts
│   ├── personality.ts
│   ├── settings.ts
│   ├── websocket.ts
│   └── index.ts
└── utils/
    ├── error-handler.ts  (新增)
    └── ...
```

### 7.2 关键文件改造对照表

| 原文件 | 改造后 | 主要变化 |
|--------|--------|----------|
| `pages/Chat.tsx` | `pages/Chat.tsx` + `hooks/useChat.ts` | 逻辑抽取到 hook |
| `pages/chat-state.ts` | `domain/chat/` | 移动到领域层 |
| `pages/Settings.tsx` | `pages/Settings.tsx` + `components/settings/sections/` | 拆分为多个 section |
| `pages/PersonalityModern.tsx` | `pages/Personality.tsx` + `hooks/usePersonality.ts` | 逻辑抽取 + 拆分 |
| `api/client.ts` | `api/client.ts` + `types/api.ts` | 添加类型定义 |
| `realtime/client.ts` | `realtime/client.ts` + `constants/websocket.ts` | 常量外提 |

### 7.3 参考资料

- [React Hooks 最佳实践](https://react.dev/learn/reusing-logic-with-custom-hooks)
- [TypeScript 类型体操](https://www.typescriptlang.org/docs/handbook/2/types-from-types.html)
- [Zustand 最佳实践](https://docs.pmnd.rs/zustand/guides/practice-with-no-store-actions)
- [Vitest 测试指南](https://vitest.dev/guide/)

---

> **文档维护:** 本文档应随着重构进度持续更新。每个 Phase 完成后，更新实际耗时和遇到的问题。
