import { useCallback, useEffect } from 'react';
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

      {/* Windows / Linux: hand-drawn window controls in the right slot. */}
      {!isMac ? <AppWindowControls className="ml-1" /> : null}
    </div>
  );
};
