import React, { useCallback, useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { useChatShellStore, useConversationStore } from '@/stores';
import { isMacPlatform } from '@/lib/platform';
import { cn } from '@/lib/utils';
import { ChatTodayStrip } from '@/components/chat/ChatTodayStrip';
import { Sparkles } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { shouldRenderChatWorkspace } from '@/pages/chat-route-helpers';
import { ChatWorkspacePicker } from './ChatWorkspacePicker';
import { AppWindowControls } from './AppWindowControls';

const SCALE_LABEL: Record<string, string> = { month: "月", week: "周", day: "日", hour: "时" };

const isoWeekValue = (date: Date): string => {
  const target = new Date(date);
  target.setHours(0, 0, 0, 0);
  // Thursday of this week determines the ISO year/week
  target.setDate(target.getDate() + 3 - ((target.getDay() + 6) % 7));
  const firstThursday = new Date(target.getFullYear(), 0, 4);
  const weekNum = 1 + Math.round(
    ((target.getTime() - firstThursday.getTime()) / 86400000 - 3 + ((firstThursday.getDay() + 6) % 7)) / 7
  );
  return `${target.getFullYear()}-W${String(weekNum).padStart(2, "0")}`;
};

const pad2 = (n: number) => String(n).padStart(2, "0");

const periodInputValue = (scale: string, startSec: number): string => {
  if (!startSec) return "";
  const d = new Date(startSec * 1000);
  if (scale === "month") return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}`;
  if (scale === "week") return isoWeekValue(d);
  if (scale === "day") return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
  if (scale === "hour") return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}T${pad2(d.getHours())}:00`;
  return "";
};

const inputTypeForScale = (scale: string): string => {
  if (scale === "month") return "month";
  if (scale === "week") return "week";
  if (scale === "day") return "date";
  return "datetime-local";
};

const TimelineTitleBarSlot: React.FC = () => {
  const { t } = useTranslation('app');
  const panel = useChatShellStore((s) => s.timelinePanel);

  return (
    <div className="flex h-full flex-1 items-center gap-3 px-3 text-xs">
      <span className="text-sm font-semibold text-foreground">
        {t('timeline.title', { defaultValue: '时间线' })}
      </span>
      <div className="flex-1" />
      {/* Scale tab group */}
      <div className="flex rounded-md bg-foreground/5 p-0.5">
        {(['month', 'week', 'day', 'hour'] as const).map((s) => (
          <button
            key={s}
            type="button"
            data-active={s === panel.scale ? 'true' : 'false'}
            onClick={() => panel.onScaleChange?.(s)}
            onMouseDown={(e) => e.stopPropagation()}
            className={cn(
              'rounded-sm px-2.5 py-1',
              s === panel.scale
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {SCALE_LABEL[s]}
          </button>
        ))}
      </div>
      {/* Date label + prev/next nav grouped together */}
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={() => panel.onPrevious?.()}
          onMouseDown={(e) => e.stopPropagation()}
          className="rounded-md p-1 text-muted-foreground hover:bg-foreground/5"
        >
          ‹
        </button>
        <input
          type={inputTypeForScale(panel.scale)}
          value={periodInputValue(panel.scale, panel.viewportStart)}
          onChange={(e) => panel.onSelectFromDateInput?.(e.target.value)}
          onMouseDown={(e) => e.stopPropagation()}
          data-no-drag
          aria-label={panel.dateLabel}
          className="cursor-pointer rounded border border-transparent bg-transparent px-1.5 py-0.5 text-xs text-muted-foreground hover:border-border hover:text-foreground focus:border-border focus:text-foreground focus:outline-none"
          style={{ minWidth: panel.scale === "hour" ? "150px" : panel.scale === "month" ? "100px" : "120px" }}
        />
        <button
          type="button"
          disabled={!panel.canGoNext}
          onClick={() => panel.onNext?.()}
          onMouseDown={(e) => e.stopPropagation()}
          className="rounded-md p-1 text-muted-foreground hover:bg-foreground/5 disabled:cursor-not-allowed disabled:opacity-30"
        >
          ›
        </button>
      </div>
      {/* Search input */}
      <input
        type="text"
        data-no-drag
        value={panel.draftQuery}
        onChange={(e) => panel.onDraftQueryChange?.(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') panel.onSubmitQuery?.();
        }}
        onMouseDown={(e) => e.stopPropagation()}
        placeholder={t('timeline.searchPlaceholder', { defaultValue: '筛选当前时段' })}
        className="h-6 w-40 rounded-md border border-border bg-background px-2 text-xs"
      />
    </div>
  );
};

/**
 * Selector for elements that should NOT trigger window-drag when clicked.
 * Buttons, links, inputs, dropdown menus, and anything explicitly opted out
 * via `data-no-drag`. `closest()` against this list makes background-vs-
 * interactive detection robust regardless of where the click lands within
 * the title bar.
 */
const NO_DRAG_SELECTOR = 'button, a, input, select, textarea, [data-no-drag], [role="menu"], [role="combobox"]';

/**
 * App-wide title bar. Sits as the first row of MainLayout and spans the
 * full window width so OS chrome (macOS traffic lights, Windows min/max/
 * close) has its own dedicated stripe instead of overlapping content.
 *
 * Per-route content (current behavior — chat-only chrome):
 *   - "/", "/chat"    → TodayStrip + workspace picker + portrait toggle
 *   - everything else → empty (just acts as the drag/resize handle)
 */

const TITLE_BAR_HEIGHT_CLASS = 'h-9'; // 36px

export const AppTitleBar = () => {
  const { t } = useTranslation('app');
  const location = useLocation();
  const isMac = isMacPlatform();

  // Disable native decorations on Windows so our hand-drawn controls own
  // the title bar. macOS uses native traffic-light overlay (tauri.conf
  // titleBarStyle:"Overlay") and Linux follows the Windows path. Runs
  // once at mount; safe no-op when not inside Tauri.
  useEffect(() => {
    if (isMac || typeof window === 'undefined') {
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const mod = await import('@tauri-apps/api/window');
        if (cancelled) return;
        await mod.getCurrentWindow().setDecorations(false);
      } catch {
        /* not running in Tauri */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isMac]);

  const portraitRailOpen = useChatShellStore((s) => s.portraitRailOpen);
  const setPortraitRailOpen = useChatShellStore((s) => s.setPortraitRailOpen);
  const currentSessionId = useConversationStore((s) => s.currentSessionId);
  const chatChromeVisible = shouldRenderChatWorkspace(location.pathname) && Boolean(currentSessionId);
  const isTimelineRoute = location.pathname === '/timeline';

  // Drag + double-click maximize are both handled in mousedown.
  //
  // We cannot use a separate onDoubleClick handler here: as soon as the
  // first mousedown calls `startDragging()` the OS captures the mouse
  // and React never sees a paired click — so dblclick is never emitted
  // for the kind of slow native gesture we'd want it for.
  //
  // Instead we look at `MouseEvent.detail` on the mousedown itself.
  // The browser increments it for every press within the platform's
  // double-click time window, so detail === 2 means the user pressed
  // twice in rapid succession on the same spot. That maps to
  // toggleMaximize; anything else starts a normal window drag.
  const handleMouseDown = useCallback(async (e: React.MouseEvent) => {
    if (e.button !== 0) return;
    const target = e.target as HTMLElement | null;
    if (target?.closest?.(NO_DRAG_SELECTOR)) return;
    try {
      const mod = await import('@tauri-apps/api/window');
      const win = mod.getCurrentWindow();
      if (e.detail >= 2) {
        await win.toggleMaximize();
      } else {
        await win.startDragging();
      }
    } catch {
      /* not in Tauri (e.g. pure browser dev preview) */
    }
  }, []);

  return (
    <div
      className={cn(
        'relative z-30 flex shrink-0 items-center border-b border-border/30 bg-background/95 backdrop-blur select-none',
        TITLE_BAR_HEIGHT_CLASS,
      )}
      onMouseDown={handleMouseDown}
    >
      {/* macOS traffic-light reserve (left). Windows/Linux: small left padding. */}
      <div className={cn('shrink-0', isMac ? 'w-[72px]' : 'w-3')} />

      {/* Center / left content: route-specific chrome. */}
      {isTimelineRoute ? (
        <TimelineTitleBarSlot />
      ) : (
        <>
          <div className="flex min-w-0 flex-1 items-center gap-2">
            {chatChromeVisible ? <ChatTodayStrip /> : null}
          </div>

          {/* Right content: route-specific actions. handleMouseDown bails when
              the click lands on a button so these still work normally. */}
          <div className="flex shrink-0 items-center gap-2 pr-2">
            {chatChromeVisible ? (
              <>
                <ChatWorkspacePicker />
                <button
                  type="button"
                  onClick={() => setPortraitRailOpen(!portraitRailOpen)}
                  aria-label={t('chat.portrait.toggleAria')}
                  aria-pressed={portraitRailOpen}
                  title={t('chat.portrait.toggleAria')}
                  data-testid="chat-portrait-toggle"
                  className={cn(
                    'flex h-7 w-7 items-center justify-center rounded-full text-muted-foreground transition-colors',
                    'hover:bg-muted hover:text-foreground',
                    portraitRailOpen && 'text-foreground',
                  )}
                >
                  <Sparkles className="h-4 w-4" />
                </button>
              </>
            ) : null}
          </div>
        </>
      )}

      {/* Windows / Linux: hand-drawn window controls in the right slot. */}
      {!isMac ? <AppWindowControls className="ml-1" /> : null}
    </div>
  );
};
