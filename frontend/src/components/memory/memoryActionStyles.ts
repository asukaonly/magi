/**
 * Memory 域评审/确认场景的按钮样式原子。
 * 放在 components 层:portrait 组件(components/memory/*)与 memory-pages 共用,
 * 受 components → pages 的 import 边界约束,不能放在 MemoryPageFrame。
 *
 * 主行动 = 主题主色(accent)填充 pill;次级 = 无框文字按钮。
 * 亮/暗与各主题变体的 accent 由 token 自动跟随。
 */

/** 单一主行动:主题主色填充,每行至多一个 */
export const MEMORY_PRIMARY_ACTION_CLASS =
  'h-8 rounded-full border-transparent bg-[hsl(var(--memory-accent))] px-3.5 text-[13px] font-medium text-[hsl(var(--memory-accent-foreground))] transition-colors duration-200 hover:bg-[hsl(var(--memory-accent)/0.85)]';

/** 次级行动:无框文字按钮,hover 时浅色垫底、文字加深 */
export const MEMORY_GHOST_ACTION_CLASS =
  'h-8 rounded-full border-transparent px-3 text-[13px] font-medium text-[hsl(var(--memory-muted))] transition-colors duration-200 hover:bg-[hsl(var(--memory-panel-subtle)/0.55)] hover:text-[hsl(var(--memory-title))]';
