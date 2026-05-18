import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { useChatShellStore, useConversationStore } from '@/stores';
import { isMacPlatform } from '@/lib/platform';
import { cn } from '@/lib/utils';
import { ChatTodayStrip } from '@/components/chat/ChatTodayStrip';
import { Sparkles } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { ChatWorkspacePicker } from './ChatWorkspacePicker';
import { AppWindowControls } from './AppWindowControls';

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

const isChatRoute = (pathname: string): boolean =>
  pathname === '/' || pathname === '/chat';

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
  const chatChromeVisible = isChatRoute(location.pathname) && Boolean(currentSessionId);

  return (
    <div
      className={cn(
        'relative z-30 flex shrink-0 items-center border-b border-border/30 bg-background/95 backdrop-blur',
        TITLE_BAR_HEIGHT_CLASS,
      )}
      style={{ WebkitAppRegion: 'drag' } as React.CSSProperties}
      data-tauri-drag-region
    >
      {/* macOS traffic-light reserve (left). Windows/Linux: small left padding. */}
      <div className={cn('shrink-0', isMac ? 'w-[72px]' : 'w-3')} />

      {/* Center / left content: route-specific chrome. */}
      <div className="flex min-w-0 flex-1 items-center gap-2">
        {chatChromeVisible ? <ChatTodayStrip /> : null}
      </div>

      {/* Right content: route-specific actions. */}
      <div
        className="flex shrink-0 items-center gap-2 pr-2"
        style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}
      >
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
