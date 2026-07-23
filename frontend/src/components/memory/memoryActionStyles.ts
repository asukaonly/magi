/**
 * Memory 域评审/确认场景的按钮样式原子。
 * 放在 components 层:portrait 组件(components/memory/*)与 memory-pages 共用,
 * 受 components → pages 的 import 边界约束,不能放在 MemoryPageFrame。
 *
 * 圆角遵循 mem-sm/md/lg 三档(见 tailwind.config.js)。
 */

/** 单一主行动:实心深色,每行至多一个 */
export const MEMORY_PRIMARY_ACTION_CLASS =
  'h-9 rounded-mem-sm border-transparent bg-[hsl(var(--memory-title))] px-4 text-sm font-medium text-[hsl(var(--memory-panel-elevated))] shadow-sm transition-colors hover:bg-[hsl(var(--memory-title)/0.86)]';

/** 次级行动:无框 ghost,hover 时浅色垫底 */
export const MEMORY_GHOST_ACTION_CLASS =
  'h-9 rounded-mem-sm border-transparent px-3 text-sm font-medium text-[hsl(var(--memory-body))] transition-colors hover:bg-[hsl(var(--memory-panel-subtle)/0.72)] hover:text-[hsl(var(--memory-title))]';
