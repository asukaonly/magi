# Settings.tsx 拆分设计

## 文件分析

**当前状态**: 1476 行，复杂度高

### 结构概览

```
Lines 1-50:    Imports
Lines 52-96:   Types and constants (NavItem, MemoryToggleFieldId)
Lines 97-184:  Helper functions (serialize, buildPluginDraft*, mergeDraftMaps, etc.)
Lines 186-295: Small components (LabeledSelectField, NumberField, ExpandableMemoryLayerCard)
Lines 297-304: Interfaces (SettingsPageHandle, SettingsPageProps)
Lines 306-706: SettingsPage component - state and handlers
Lines 720-1247: renderSectionContent() - 10 sections
Lines 1249-1474: Main render - nav sidebar, header, content area, footer
```

### 10 个导航区块

| ID | 名称 | 当前状态 | 复杂度 |
|---|---|---|---|
| `preferences` | 偏好设置 | 内联 JSX (~45 行) | 低 |
| `llm` (group) | LLM 配置 | 使用 LLMForm 组件 | - |
| ├─ `llmProviders` | 提供商 | 使用 LLMForm (~15 行) | 低 |
| └─ `llmModels` | 模型 | 使用 LLMForm (~15 行) | 低 |
| `usage` | 使用量 | 使用 LLMUsageSection | 低 |
| `personality` | 人格 | 内联 JSX (~25 行) | 低 |
| `memory` | 内存 | 内联 JSX (~270 行) | **高** |
| `timeline` | 时间线 | 使用 TimelineSourcesSection | 低 |
| `extensions` | 扩展 | 使用 ExtensionsSection | 低 |
| `tools` | 工具 | 使用 DynamicToolsConfig | 低 |
| `actions` | 动作 | 使用 ActionsSection | 低 |
| `system` | 系统 | 内联 JSX (~70 行) | 中 |

### 状态结构

```typescript
// 主配置状态 (saved/draft 模式)
const [savedConfig, setSavedConfig] = useState<SystemConfig>(...);
const [draftConfig, setDraftConfig] = useState<SystemConfig>(...);

// 主题状态 (saved/draft 模式)
const [savedThemeMode, setSavedThemeMode] = useState<ThemeMode>(...);
const [draftThemeMode, setDraftThemeMode] = useState<ThemeMode>(...);

// 插件草稿状态 (saved/draft 模式)
const [savedPluginDrafts, setSavedPluginDrafts] = useState<Record<string, Record<string, any>>>({});
const [draftPluginDrafts, setDraftPluginDrafts] = useState<Record<string, Record<string, any>>>({});

// 工具草稿状态 (saved/draft 模式)
const [savedToolDrafts, setSavedToolDrafts] = useState<Record<string, { enabled: boolean; values: Record<string, any> }>>({});
const [draftToolDrafts, setDraftToolDrafts] = useState<Record<string, { enabled: boolean; values: Record<string, any> }>>({});

// UI 状态
const [loading, setLoading] = useState(true);
const [saving, setSaving] = useState(false);
const [activeSection, setActiveSection] = useState('preferences');
const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({ llm: false });
const [expandedMemoryLayers, setExpandedMemoryLayers] = useState<Set<string>>(new Set(['l0', 'l1']));

// 数据状态
const [timelineStatuses, setTimelineStatuses] = useState<TimelineSourceStatusItem[]>([]);
const [timelineStatusesLoading, setTimelineStatusesLoading] = useState(false);
const [timelineSelection, setTimelineSelection] = useState<string | null>(null);
const [plugins, setPlugins] = useState<PluginPackageState[]>([]);
const [pluginsLoading, setPluginsLoading] = useState(false);
const [pluginProcessingIds, setPluginProcessingIds] = useState<Record<string, string>>({});
const [tools, setTools] = useState<ToolConfig[]>([]);
const [toolsLoading, setToolsLoading] = useState(false);
const [toolsError, setToolsError] = useState<string | null>(null);
const [reloadingActionPlugins, setReloadingActionPlugins] = useState<Record<string, boolean>>({});
```

---

## 拆分策略

### Phase 1: 提取 useSettings Hook

**目标**: 将所有状态和逻辑移入 hook，组件只负责渲染

**文件**: `src/hooks/useSettings.ts`

```typescript
export interface UseSettingsReturn {
  // Loading states
  loading: boolean;
  saving: boolean;

  // Navigation
  activeSection: string;
  setActiveSection: (section: string) => void;
  expandedGroups: Record<string, boolean>;
  setGroupExpanded: (groupId: string, expanded: boolean) => void;

  // Config state (saved/draft)
  draftConfig: SystemConfig;
  patchDraftConfig: (updater: (draft: SystemConfig) => void) => void;

  // Theme state (saved/draft)
  draftThemeMode: ThemeMode;
  handleThemePreviewChange: (mode: ThemeMode) => void;

  // Language
  handleLanguagePreviewChange: (value: string) => void;

  // Memory
  expandedMemoryLayers: Set<string>;
  toggleMemoryLayerExpand: (layerKey: string, expanded: boolean) => void;
  updateMemoryToggle: (field: MemoryToggleFieldId, checked: boolean) => void;

  // Plugins
  plugins: PluginPackageState[];
  pluginsLoading: boolean;
  pluginProcessingIds: Record<string, string>;
  draftPluginDrafts: Record<string, Record<string, any>>;
  handlePluginDraftChange: (pluginId: string, key: string, value: any) => void;
  handlePluginDraftChanges: (pluginId: string, updates: Record<string, any>) => void;
  handlePluginAction: (pluginId: string, action: 'enable' | 'disable' | 'reload') => Promise<void>;
  handleReloadActionPlugin: (pluginId: string) => Promise<void>;

  // Tools
  tools: ToolConfig[];
  toolsLoading: boolean;
  toolsError: string | null;
  draftToolDrafts: Record<string, { enabled: boolean; values: Record<string, any> }>;
  handleToolDraftChange: (toolName: string, path: string, value: any) => void;
  handleToolEnabledChange: (toolName: string, enabled: boolean) => void;

  // Timeline
  timelineStatuses: TimelineSourceStatusItem[];
  timelineStatusesLoading: boolean;
  timelineSelection: string | null;
  setTimelineSelection: (selection: string | null) => void;

  // Dirty tracking
  dirty: boolean;

  // Actions
  handleSaveChanges: () => Promise<void>;
  handleDiscardChanges: () => Promise<void>;

  // Ref handle
  getHandle: () => SettingsPageHandle;
}
```

**复杂度**: 约 400-500 行

### Phase 2: 提取共享组件

#### 2.1 表单字段组件
**文件**: `src/components/settings/form-fields.tsx`

```typescript
// LabeledSelectField - 带标签的选择框
export const LabeledSelectField: React.FC<...>

// NumberField - 带标签的数字输入
export const NumberField: React.FC<...>
```

#### 2.2 可展开内存层卡片
**文件**: `src/components/settings/ExpandableMemoryLayerCard.tsx`

```typescript
export interface ExpandableMemoryLayerCardProps {
  layerKey: string;
  label: string;
  description: string;
  checked: boolean;
  disabled?: boolean;
  expanded: boolean;
  onToggle: (checked: boolean) => void;
  onExpand: (expanded: boolean) => void;
  children?: React.ReactNode;
}

export const ExpandableMemoryLayerCard: React.FC<ExpandableMemoryLayerCardProps>
```

### Phase 3: 提取 Section 组件

只提取内联 JSX 较复杂的区块:

#### 3.1 PreferencesSection
**文件**: `src/components/settings/PreferencesSection.tsx`
**复杂度**: ~60 行

```typescript
export interface PreferencesSectionProps {
  language: LanguageCode;
  themeMode: ThemeMode;
  onLanguageChange: (value: string) => void;
  onThemeChange: (mode: ThemeMode) => void;
}
```

#### 3.2 PersonalitySection
**文件**: `src/components/settings/PersonalitySection.tsx`
**复杂度**: ~40 行

```typescript
export interface PersonalitySectionProps {
  personality: SystemConfig['personality'];
  onConfigure: () => void;
}
```

#### 3.3 MemorySection (重点)
**文件**: `src/components/settings/MemorySection.tsx`
**复杂度**: ~280 行

这是最复杂的 section，建议进一步拆分为子组件：

```typescript
// src/components/settings/memory/LayerCard.tsx (L0-L4 各一层)
// 或使用通用 ExpandableMemoryLayerCard + 配置
```

**Props**:
```typescript
export interface MemorySectionProps {
  config: SystemConfig['memory'];
  expandedLayers: Set<string>;
  hasEmbeddingModel: boolean;
  onToggleLayer: (field: MemoryToggleFieldId, checked: boolean) => void;
  onExpandLayer: (layerKey: string, expanded: boolean) => void;
  onUpdateField: (updater: (draft: SystemConfig['memory']) => void) => void;
}
```

#### 3.4 SystemSection
**文件**: `src/components/settings/SystemSection.tsx`
**复杂度**: ~80 行

```typescript
export interface SystemSectionProps {
  loop: SystemConfig['loop'];
  messageBus: SystemConfig['message_bus'];
  websocket: SystemConfig['websocket'];
  log: SystemConfig['log'];
  onUpdate: (updater: (draft: SystemConfig) => void) => void;
}
```

### Phase 4: 提取常量和工具函数

#### 4.1 常量
**文件**: `src/constants/settings.ts`

```typescript
export const NAV_ITEMS: NavItem[];
export const LANGUAGE_STORAGE_KEY = 'magi_language';
```

#### 4.2 工具函数
**文件**: `src/utils/settings-helpers.ts`

```typescript
export const serialize = (value: unknown) => JSON.stringify(value);
export const toI18nLanguage = (language: LanguageCode) => ...;
export const persistLanguageSelection = (language: LanguageCode) => ...;
export const previewLanguageSelection = async (language: LanguageCode) => ...;
export const buildPluginDraftSnapshotFromPackages = ...;
export const buildPluginDraftSnapshotFromTimeline = ...;
export const mergeDraftMaps = ...;
export const buildToolDraftSnapshot = ...;
export const diffFlatMaps = ...;
```

#### 4.3 类型定义
**文件**: `src/types/settings.ts`

```typescript
export type NavLeaf = { id: string; icon: React.ElementType; children?: never };
export type NavGroup = { id: string; icon: React.ElementType; children: Array<{ id: string }> };
export type NavItem = NavLeaf | NavGroup;
export type MemoryToggleFieldId = 'enable_l0' | 'enable_l1' | ...;
export interface SettingsPageHandle { ... }
export interface SettingsPageProps { ... }
```

---

## 重构后文件结构

```
src/
├── constants/
│   └── settings.ts              # NAV_ITEMS, LANGUAGE_STORAGE_KEY
├── types/
│   └── settings.ts              # NavItem, MemoryToggleFieldId, SettingsPageHandle
├── utils/
│   └── settings-helpers.ts      # serialize, buildPluginDraft*, mergeDraftMaps, etc.
├── hooks/
│   └── useSettings.ts           # 主 hook (~400-500 行)
├── components/
│   └── settings/
│       ├── index.ts             # 统一导出
│       ├── form-fields.tsx      # LabeledSelectField, NumberField
│       ├── ExpandableMemoryLayerCard.tsx
│       ├── PreferencesSection.tsx
│       ├── PersonalitySection.tsx
│       ├── MemorySection.tsx    # (~280 行，或进一步拆分)
│       ├── SystemSection.tsx
│       ├── LLMUsageSection.tsx  # 已存在
│       ├── TimelineSourcesSection.tsx  # 已存在
│       ├── ExtensionsSection.tsx  # 已存在
│       └── ActionsSection.tsx   # 已存在
└── pages/
    └── Settings.tsx             # 主组件 (~300 行)
```

---

## 预期行数变化

| 文件 | 当前行数 | 重构后行数 |
|---|---|---|
| `Settings.tsx` | 1476 | ~300 |
| `useSettings.ts` | - | ~450 |
| `settings-helpers.ts` | - | ~100 |
| `settings.ts` (types) | - | ~30 |
| `settings.ts` (constants) | - | ~20 |
| `form-fields.tsx` | - | ~60 |
| `ExpandableMemoryLayerCard.tsx` | - | ~80 |
| `PreferencesSection.tsx` | - | ~60 |
| `PersonalitySection.tsx` | - | ~40 |
| `MemorySection.tsx` | - | ~280 |
| `SystemSection.tsx` | - | ~80 |

**总计**: ~1500 行 (与原来相当，但模块化程度大幅提升)

---

## 实施顺序

1. **Phase 1**: 创建 `useSettings.ts` hook
   - 提取所有状态声明
   - 提取所有 handler 函数
   - 提取数据加载逻辑
   - 保持 Settings.tsx 编译通过

2. **Phase 2**: 创建辅助文件
   - `src/types/settings.ts`
   - `src/constants/settings.ts`
   - `src/utils/settings-helpers.ts`

3. **Phase 3**: 提取共享组件
   - `form-fields.tsx`
   - `ExpandableMemoryLayerCard.tsx`

4. **Phase 4**: 提取 Section 组件
   - `PreferencesSection.tsx`
   - `PersonalitySection.tsx`
   - `MemorySection.tsx`
   - `SystemSection.tsx`

5. **Phase 5**: 更新测试
   - 更新 `settingsPage.test.tsx` 以适配新结构

---

## 风险和注意事项

1. **saved/draft 模式复杂**: 需要确保所有状态同步正确
2. **useImperativeHandle**: hook 需要提供 `getHandle()` 方法给 forwardRef
3. **Timeline 轮询**: `useEffect` 中的轮询逻辑需要正确清理
4. **测试覆盖**: 现有测试需要更新 import 路径

---

## 是否继续？

请确认此设计方案是否符合预期，我可以开始实施。
