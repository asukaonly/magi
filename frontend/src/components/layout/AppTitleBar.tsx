import React, { useCallback } from 'react';
import { useLocation } from 'react-router';
import { useChatShellStore, useConversationStore } from '@/stores';
import { isMacPlatform } from '@/lib/platform';
import { cn } from '@/lib/utils';
import { Sparkles } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { shouldRenderChatWorkspace } from '@/domain/chat/shell-routing';
import { ChatWorkspacePicker } from './ChatWorkspacePicker';
import { AppWindowControls } from './AppWindowControls';
import { NotificationBell } from './NotificationBell';
import { Calendar } from '@/components/ui/calendar';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { MonthGridPicker } from '@/components/timeline/immersive/picker/MonthGridPicker';
import { WeekListPicker } from '@/components/timeline/immersive/picker/WeekListPicker';

const SCALE_OPTIONS = ['month', 'week', 'day', 'hour'] as const;


const TimelineTitleBarSlot: React.FC = () => {
  const { t } = useTranslation('app');
  const panel = useChatShellStore((s) => s.timelinePanel);

  return (
    <div className="flex h-full flex-1 items-center gap-3 px-3 text-xs">
      <div className="flex-1" />
      {/* Scale tab group */}
      <div className="flex rounded-md bg-foreground/5 p-0.5">
        {SCALE_OPTIONS.map((s) => (
          <button
            key={s}
            type="button"
            data-active={s === panel.scale ? 'true' : 'false'}
            onClick={() => panel.onScaleChange?.(s)}
            onMouseDown={(e) => e.stopPropagation()}
            aria-label={t(`timeline.scale.${s}`)}
            className={cn(
              'min-w-[28px] rounded-sm px-2.5 py-1 text-center transition-colors',
              s === panel.scale
                ? 'bg-[hsl(var(--app-chrome-elevated))] text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {t(`timeline.scaleShort.${s}`, {
              defaultValue: t(`timeline.scale.${s}`),
            })}
          </button>
        ))}
      </div>
      {/* Date label + prev/next nav grouped together */}
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={() => panel.onPrevious?.()}
          onMouseDown={(e) => e.stopPropagation()}
          aria-label={t('timeline.nav.previous')}
          className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-[hsl(var(--app-chrome-elevated)/0.78)] hover:text-foreground"
        >
          ‹
        </button>
        <Popover>
          <PopoverTrigger asChild>
            <button
              type="button"
              onMouseDown={(e) => e.stopPropagation()}
              data-no-drag
              className="w-[160px] cursor-pointer rounded border border-transparent bg-transparent px-2 py-0.5 text-center text-xs text-muted-foreground transition-colors hover:bg-[hsl(var(--app-chrome-elevated)/0.72)] hover:text-foreground"
            >
              {panel.dateLabel}
            </button>
          </PopoverTrigger>
          <PopoverContent
            align="center"
            className="w-auto p-0"
            onMouseDown={(e) => e.stopPropagation()}
          >
            {panel.scale === "month" ? (
              <MonthGridPicker
                selectedMonth={(() => {
                  const d = new Date(panel.viewportStart * 1000);
                  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
                })()}
                onSelectMonth={(m) => panel.onSelectFromDateInput?.(m)}
              />
            ) : panel.scale === "week" ? (
              <WeekListPicker
                selectedWeekStart={panel.viewportStart}
                onSelectWeek={(w) => panel.onSelectFromDateInput?.(w)}
              />
            ) : (
              <>
                <Calendar
                  mode="single"
                  selected={new Date(panel.viewportStart * 1000)}
                  onSelect={(date) => {
                    if (!date) return;
                    const y = date.getFullYear();
                    const m = String(date.getMonth() + 1).padStart(2, "0");
                    const d = String(date.getDate()).padStart(2, "0");
                    if (panel.scale === "hour") {
                      const currentHour = new Date(panel.viewportStart * 1000).getHours();
                      const hh = String(currentHour).padStart(2, "0");
                      panel.onSelectFromDateInput?.(`${y}-${m}-${d}T${hh}:00`);
                    } else {
                      panel.onSelectFromDateInput?.(`${y}-${m}-${d}`);
                    }
                  }}
                  initialFocus
                />
                {panel.scale === "hour" ? (
                  <div className="border-t border-border px-3 py-2">
                    <div className="mb-1.5 text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
                      {t('timeline.titlebar.hour', { defaultValue: 'Hour' })}
                    </div>
                    <div className="grid grid-cols-6 gap-1">
                      {Array.from({ length: 24 }, (_, i) => i).map((h) => {
                        const selectedHour = new Date(panel.viewportStart * 1000).getHours();
                        const isSel = h === selectedHour;
                        return (
                          <button
                            key={h}
                            type="button"
                            onMouseDown={(e) => e.stopPropagation()}
                            onClick={() => {
                              const dt = new Date(panel.viewportStart * 1000);
                              const y = dt.getFullYear();
                              const m = String(dt.getMonth() + 1).padStart(2, "0");
                              const dd = String(dt.getDate()).padStart(2, "0");
                              const hh = String(h).padStart(2, "0");
                              panel.onSelectFromDateInput?.(`${y}-${m}-${dd}T${hh}:00`);
                            }}
                            className={cn(
                              "rounded px-2 py-1 text-xs",
                              isSel
                                ? "bg-foreground text-background"
                                : "text-muted-foreground hover:bg-foreground/5 hover:text-foreground"
                            )}
                          >
                            {String(h).padStart(2, "0")}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                ) : null}
              </>
            )}
          </PopoverContent>
        </Popover>
        <button
          type="button"
          disabled={!panel.canGoNext}
          onClick={() => panel.onNext?.()}
          onMouseDown={(e) => e.stopPropagation()}
          aria-label={t('timeline.nav.next')}
          className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-[hsl(var(--app-chrome-elevated)/0.78)] hover:text-foreground disabled:cursor-not-allowed disabled:opacity-30"
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
        placeholder={t('timeline.filters.queryInWindow', { defaultValue: '筛选当前时段' })}
        aria-label={t('timeline.filters.queryInWindow', { defaultValue: '筛选当前时段' })}
        className="h-6 w-40 rounded-md border-transparent bg-[hsl(var(--app-chrome-elevated)/0.72)] px-2 text-xs shadow-[inset_0_0_0_1px_hsl(var(--app-chrome-divider)/0.38)]"
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
 * Native decorations are disabled on Windows/Linux during Tauri setup so
 * only AppWindowControls are shown. macOS keeps titleBarStyle: Overlay.
 *
 * Per-route content (current behavior — chat-only chrome):
 *   - "/", "/chat"    → workspace picker + portrait toggle
 *   - everything else → empty (just acts as the drag/resize handle)
 */

const TITLE_BAR_HEIGHT_CLASS = 'h-9'; // 36px

export const AppTitleBar = () => {
  const { t } = useTranslation('app');
  const location = useLocation();
  const isMac = isMacPlatform();

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
        'relative z-30 flex shrink-0 items-center bg-[hsl(var(--app-chrome-surface))] shadow-[inset_0_-1px_0_hsl(var(--app-chrome-divider)/0.42)] select-none',
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
          <div className="min-w-0 flex-1" />

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
                    'hover:bg-[hsl(var(--app-chrome-elevated)/0.78)] hover:text-foreground',
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

      {/* Global notification bell — rendered for every route (outside the
          isTimelineRoute ternary), just before the window controls. Extra
          right padding keeps the unread badge clear of the window corner. */}
      <div data-testid="tour-target-bell" className={cn('flex shrink-0 items-center', isMac ? 'pr-3' : 'pr-1')}>
        <NotificationBell />
      </div>

      {/* Windows / Linux: hand-drawn window controls in the right slot. */}
      {!isMac ? <AppWindowControls className="ml-1" /> : null}
    </div>
  );
};
