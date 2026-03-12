# Panel Layout Redesign Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 改造右侧区域布局，使聊天/人格/记忆页面直接显示，不再以 Sheet 覆盖形式打开；添加折叠功能。

**Architecture:**
- MainLayout 控制整体布局和折叠状态
- Chat.tsx 移除人格/记忆的 Sheet，改为根据路由条件渲染
- 人格页面重新设计为顶部头像选择器 + 下方详情布局

**Tech Stack:** React, TypeScript, Zustand, Tailwind CSS, Framer Motion, React Router

---

## Chunk 1: 折叠功能实现

### Task 1: 在 MainLayout 添加折叠按钮和折叠逻辑

**Files:**
- Modify: `frontend/src/components/layout/MainLayout.tsx`
- Modify: `frontend/src/stores/chat-shell.ts` (已有 sidebarCollapsed 状态)

**说明：** Store 已有 `sidebarCollapsed` 和 `toggleSidebarCollapsed`，只需在 MainLayout 中添加折叠按钮和应用折叠样式。

- [ ] **Step 1: 修改 MainLayout，添加折叠按钮到标题栏区域**

在 MainLayout.tsx 中：
1. 导入 useChatShellStore 获取折叠状态和切换函数
2. 在标题栏区域（现有 drag strip 旁边）添加折叠按钮
3. 根据 sidebarCollapsed 状态切换 grid 布局

```tsx
// MainLayout.tsx
import { useChatShellStore } from '@/stores';
import { PanelLeftClose, PanelLeft } from 'lucide-react';

const MainLayout: React.FC = () => {
  const sidebarCollapsed = useChatShellStore((state) => state.sidebarCollapsed);
  const toggleSidebarCollapsed = useChatShellStore((state) => state.toggleSidebarCollapsed);

  return (
    <div className="h-screen w-screen overflow-hidden">
      <div
        className={cn(
          "desktop-surface relative grid h-full w-full overflow-hidden grid-rows-[minmax(0,1fr)] transition-all duration-300",
          sidebarCollapsed
            ? "grid-cols-[0px_minmax(0,1fr)]"
            : "grid-cols-[320px_minmax(0,1fr)]"
        )}
      >
        {/* 折叠按钮 */}
        <button
          type="button"
          onClick={toggleSidebarCollapsed}
          className="absolute left-3 top-3 z-50 flex h-9 w-9 items-center justify-center rounded-xl border border-border/40 bg-card/80 text-muted-foreground shadow-sm transition-colors hover:bg-muted hover:text-foreground"
          aria-label={sidebarCollapsed ? '展开侧边栏' : '折叠侧边栏'}
        >
          {sidebarCollapsed ? (
            <PanelLeft className="h-4 w-4" />
          ) : (
            <PanelLeftClose className="h-4 w-4" />
          )}
        </button>

        {/* 原有的 drag strip */}
        <div
          className="absolute right-0 top-0 z-40 h-16"
          style={{ left: sidebarCollapsed ? '48px' : '78px', WebkitAppRegion: 'drag' } as React.CSSProperties}
          data-tauri-drag-region
        />

        {/* Sidebar - 折叠时隐藏 */}
        <div className={cn(
          "min-h-0 transition-opacity duration-300",
          sidebarCollapsed ? "pointer-events-none opacity-0" : "opacity-100"
        )}>
          <Sidebar />
        </div>

        {/* 右侧内容区域 */}
        <div className="min-h-0 min-w-0">
          <main className="h-full overflow-hidden">
            <div className="page-enter h-full overflow-hidden">
              <Outlet />
            </div>
          </main>
        </div>
      </div>
    </div>
  );
};
```

- [ ] **Step 2: 验证折叠功能**

手动测试：
1. 启动前端开发服务器
2. 点击折叠按钮，确认左侧区域隐藏
3. 再次点击，确认左侧区域恢复显示
4. 刷新页面，确认折叠状态持久化

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/layout/MainLayout.tsx
git commit -m "feat(layout): add sidebar collapse toggle button

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Chunk 2: 移除 Sheet 覆盖，改为直接渲染

### Task 2: 重构 Chat.tsx，移除人格/记忆 Sheet

**Files:**
- Modify: `frontend/src/pages/Chat.tsx`
- Modify: `frontend/src/router/index.tsx`

**说明：** 当路由是 `/personality` 或 `/events` 时，直接渲染对应组件，而不是通过 Sheet 覆盖。

- [ ] **Step 1: 修改 Chat.tsx，根据路由直接渲染内容**

```tsx
// Chat.tsx - 修改 return 部分
const isChatRoute = location.pathname === '/' || location.pathname === '/chat';
const isPersonalityRoute = location.pathname === '/personality';
const isMemoryRoute = location.pathname === '/events';

return (
  <div className="relative flex h-full min-h-0 flex-col px-3 pb-3 pt-2">
    {/* 只在聊天路由显示聊天内容 */}
    {isChatRoute && (
      <>
        {/* 原有的聊天消息列表 */}
        <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent">
          {/* ... 聊天消息渲染 ... */}
        </div>

        {/* 输入框 */}
        <div className="mt-2 shrink-0">
          {/* ... 输入框 ... */}
        </div>
      </>
    )}

    {/* 人格路由 - 直接渲染 PersonalityModern */}
    {isPersonalityRoute && (
      <div className="h-full overflow-y-auto">
        <PersonalityModern />
      </div>
    )}

    {/* 记忆路由 - 直接渲染 EventsPage */}
    {isMemoryRoute && (
      <div className="h-full overflow-y-auto p-5">
        <EventsPage />
      </div>
    )}

    {/* ToolchainDrawer 保留 */}
    <ToolchainDrawer
      open={drawerOpen}
      onOpenChange={(open) => !open && closeDrawer()}
      loading={loadingTrace}
      snapshot={normalizeTraceSnapshot(snapshots[activeTurnId || ''] || null)}
      title={t('chat.trace.title')}
      subtitle={t('chat.trace.subtitle')}
    />

    {/* 设置保持弹窗形式 */}
    <SettingsCenterDialog open={activePanel === 'settings'} onOpenChange={(open) => !open && closePanel()} />

    {/* 移除人格和记忆的 Sheet */}
  </div>
);
```

- [ ] **Step 2: 清理不再需要的 Sheet 导入**

移除不再使用的 Sheet 相关导入：
```tsx
// 移除这些导入（如果不再需要）
// import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
```

- [ ] **Step 3: 验证路由切换**

手动测试：
1. 访问 `/chat` - 确认显示聊天界面
2. 点击侧边栏"人格" - 确认直接显示人格页面，无 Sheet 覆盖
3. 点击侧边栏"记忆" - 确认直接显示记忆页面，无 Sheet 覆盖
4. 点击侧边栏"设置" - 确认仍为弹窗形式

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Chat.tsx
git commit -m "refactor(chat): render personality and memory pages directly instead of Sheet overlay

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Chunk 3: 人格页面重新设计

### Task 3: 重新设计人格页面 - 头像选择器布局

**Files:**
- Modify: `frontend/src/pages/PersonalityModern.tsx`

**说明：** 将现有的左侧边栏布局改为顶部横向头像选择器 + 下方详情的布局。

- [ ] **Step 1: 创建新的 PersonalityPage 组件结构**

在 PersonalityModern.tsx 中重构布局：

```tsx
// 顶部区域：横向人格头像选择器
<div className="border-b border-border/40 bg-muted/20 px-6 py-5">
  <div className="mb-4 flex items-center justify-between">
    <h2 className="text-xl font-semibold tracking-tight text-foreground">
      {t('settings.tabs.personality')}
    </h2>
    <Button
      variant="outline"
      onClick={createPersonality}
      className="rounded-xl"
    >
      <Plus className="mr-2 h-4 w-4" />
      {t('personality.create')}
    </Button>
  </div>

  {/* 人格头像横向列表 */}
  <div className="flex gap-4 overflow-x-auto pb-2">
    {/* 添加按钮 */}
    <button
      type="button"
      onClick={createPersonality}
      className="group flex h-20 w-20 shrink-0 flex-col items-center justify-center gap-1 rounded-2xl border-2 border-dashed border-border/50 bg-muted/30 transition-colors hover:border-primary/50 hover:bg-primary/5"
    >
      <Plus className="h-6 w-6 text-muted-foreground group-hover:text-primary" />
      <span className="text-[10px] text-muted-foreground">{t('personality.create')}</span>
    </button>

    {/* 人格列表 */}
    {list.map((item) => {
      const isActive = selectedName === item.name;
      const isCurrent = currentName === item.name;
      return (
        <button
          key={item.name}
          type="button"
          onClick={() => {
            setSelectedName(item.name);
            setDiffs([]);
            void loadOne(item.name);
          }}
          className={cn(
            "group relative flex h-20 w-20 shrink-0 flex-col items-center justify-center gap-1 rounded-2xl border-2 transition-all",
            isActive
              ? "border-primary bg-primary/10"
              : "border-border/40 bg-muted/30 hover:border-border/60 hover:bg-muted/50"
          )}
        >
          {/* 头像 */}
          <div className={cn(
            "flex h-10 w-10 items-center justify-center rounded-full text-sm font-semibold",
            isActive ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"
          )}>
            {item.displayName?.charAt(0)?.toUpperCase() || '?'}
          </div>
          {/* 名称 */}
          <span className={cn(
            "max-w-[72px] truncate text-[11px]",
            isActive ? "text-primary font-medium" : "text-muted-foreground"
          )}>
            {item.displayName}
          </span>
          {/* 当前使用标记 */}
          {isCurrent && (
            <div className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full bg-primary text-[10px] text-primary-foreground">
              ✓
            </div>
          )}
        </button>
      );
    })}
  </div>
</div>

{/* 下方详情区域 */}
<div className="flex-1 overflow-y-auto">
  {/* 原有的配置表单内容 */}
</div>
```

- [ ] **Step 2: 简化详情区域布局**

移除原有的 GuidedConfigFrame 左侧边栏，保留右侧配置表单内容：

```tsx
<div className="flex-1 overflow-y-auto p-6">
  {/* 顶部操作栏 */}
  <div className="mb-6 flex items-center justify-between">
    <div>
      <h3 className="text-lg font-semibold text-foreground">
        {selectedInfo?.displayName || selectedName}
      </h3>
      <p className="text-sm text-muted-foreground">
        {selectedInfo?.subtitle || t('settings.personalityDesc')}
      </p>
    </div>
    <div className="flex gap-2">
      {selectedName !== currentName && (
        <Button onClick={switchPersonality} disabled={switching}>
          <Check className="mr-2 h-4 w-4" />
          {switching ? t('personality.switching') : t('personality.switch')}
        </Button>
      )}
      <Button variant="outline" onClick={save} disabled={saving || loading}>
        <Check className="mr-2 h-4 w-4" />
        {saving ? t('personality.saving') : t('personality.save')}
      </Button>
      <Button
        variant="outline"
        onClick={deletePersonality}
        disabled={selectedName === 'default'}
        className="border-destructive/35 text-destructive hover:bg-destructive/10"
      >
        <Trash2 className="mr-2 h-4 w-4" />
        {t('personality.delete')}
      </Button>
    </div>
  </div>

  {/* 原有的配置表单 Cards */}
  {/* ... 保留现有的 Card 组件 ... */}
</div>
```

- [ ] **Step 3: 移除 GuidedConfigFrame 依赖**

由于不再需要左侧边栏，可以移除 GuidedConfigFrame 包装：

```tsx
// 移除 GuidedConfigFrame 导入
// import GuidedConfigFrame from '@/components/config-forms/GuidedConfigFrame';

// 直接返回内容，不再用 GuidedConfigFrame 包装
return (
  <div className="flex h-full flex-col">
    {/* 顶部头像选择器 */}
    {/* 下方详情区域 */}
  </div>
);
```

- [ ] **Step 4: 验证人格页面**

手动测试：
1. 访问 `/personality`
2. 确认顶部显示横向头像列表
3. 点击不同头像，确认下方详情切换
4. 确认"添加"按钮正常工作
5. 确认保存、切换、删除功能正常

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/PersonalityModern.tsx
git commit -m "refactor(personality): redesign with horizontal avatar selector layout

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Chunk 4: 样式调整和测试

### Task 4: 整体样式调整

**Files:**
- Modify: `frontend/src/pages/Chat.tsx` (样式微调)
- Modify: `frontend/src/pages/PersonalityModern.tsx` (样式微调)

- [ ] **Step 1: 调整 Chat.tsx 中各页面的过渡动画**

添加页面切换动画：

```tsx
import { AnimatePresence, motion } from 'framer-motion';

// 在 return 中
<AnimatePresence mode="wait">
  {isChatRoute && (
    <motion.div
      key="chat"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.15 }}
      className="absolute inset-0 flex flex-col px-3 pb-3 pt-2"
    >
      {/* 聊天内容 */}
    </motion.div>
  )}
  {isPersonalityRoute && (
    <motion.div
      key="personality"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.15 }}
      className="absolute inset-0 overflow-y-auto"
    >
      <PersonalityModern />
    </motion.div>
  )}
  {isMemoryRoute && (
    <motion.div
      key="memory"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.15 }}
      className="absolute inset-0 overflow-y-auto p-5"
    >
      <EventsPage />
    </motion.div>
  )}
</AnimatePresence>
```

- [ ] **Step 2: 验证所有页面切换流畅**

手动测试所有路由切换，确认动画流畅，无闪烁。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/Chat.tsx frontend/src/pages/PersonalityModern.tsx
git commit -m "style: add page transition animations

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

### Task 5: 最终测试

- [ ] **Step 1: 完整功能测试**

测试清单：
- [ ] 聊天页面正常显示和发送消息
- [ ] 点击人格 → 直接显示人格页面
- [ ] 人格页面头像选择器正常工作
- [ ] 人格创建、编辑、保存、删除正常
- [ ] 点击记忆 → 直接显示记忆页面
- [ ] 记忆页面 Tab 切换正常
- [ ] 点击设置 → 弹窗正常显示
- [ ] 折叠按钮正常工作
- [ ] 折叠状态刷新后保持
- [ ] 从折叠状态点击侧边栏按钮可以正常导航

- [ ] **Step 2: Final Commit**

```bash
git add -A
git commit -m "feat: complete panel layout redesign

- Add sidebar collapse functionality
- Remove Sheet overlay for personality and memory pages
- Redesign personality page with horizontal avatar selector
- Add page transition animations

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```
