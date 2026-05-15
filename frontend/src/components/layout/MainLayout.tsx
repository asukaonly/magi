import React, { useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useChatShellStore, useConversationStore } from '@/stores';
import { useBackendHealth } from '@/hooks/useBackendHealth';
import { panelByPathname } from '@/pages/chat-route-helpers';
import AppShellProviders from './AppShellProviders';
import BackendHealthBanner from './BackendHealthBanner';
import Sidebar from './Sidebar';
import ShellOverlays from './ShellOverlays';
import { PermissionModalHost, AskDialog } from '@/components/control';
import { ErrorBoundary } from '@/components/ui/ErrorBoundary';

const SHELL_DRAG_STRIP_LEFT = '56px';

const PageContentErrorFallback = () => {
  const { t } = useTranslation('app');
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 bg-background p-8 text-center text-foreground">
      <div>
        <h1 className="text-lg font-semibold">{t('shell.contentErrorTitle')}</h1>
        <p className="mt-2 max-w-md text-sm text-muted-foreground">{t('shell.contentErrorDescription')}</p>
      </div>
      <button
        type="button"
        className="rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground hover:bg-primary/90"
        onClick={() => window.location.reload()}
      >
        {t('shell.reload')}
      </button>
    </div>
  );
};

const SidebarErrorFallback = () => {
  const { t } = useTranslation('app');
  return (
    <aside className="flex min-h-0 flex-col justify-center border-r border-border/70 bg-background p-6 text-foreground">
      <h2 className="text-sm font-semibold">{t('shell.sidebarErrorTitle')}</h2>
      <p className="mt-2 text-sm leading-6 text-muted-foreground">{t('shell.sidebarErrorDescription')}</p>
      <button
        type="button"
        className="mt-4 rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground hover:bg-primary/90"
        onClick={() => window.location.reload()}
      >
        {t('shell.reload')}
      </button>
    </aside>
  );
};

const ShellOverlayErrorFallback = () => {
  const { t } = useTranslation('app');
  const setActivePanel = useChatShellStore((state) => state.setActivePanel);
  return (
    <div className="absolute right-4 top-6 z-50 max-w-sm rounded-lg border border-destructive/40 bg-background p-4 text-sm text-foreground shadow-lg">
      <div className="font-medium">{t('shell.overlayErrorTitle')}</div>
      <p className="mt-1 text-muted-foreground">{t('shell.overlayErrorDescription')}</p>
      <div className="mt-3 flex items-center gap-2">
        <button
          type="button"
          className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted"
          onClick={() => setActivePanel('none')}
        >
          {t('shell.dismiss')}
        </button>
        <button
          type="button"
          className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground hover:bg-primary/90"
          onClick={() => window.location.reload()}
        >
          {t('shell.reload')}
        </button>
      </div>
    </div>
  );
};

const MainLayout: React.FC = () => {
  const location = useLocation();
  const activePanel = useChatShellStore((state) => state.activePanel);
  const setActivePanel = useChatShellStore((state) => state.setActivePanel);
  const currentSessionId = useConversationStore((state) => state.currentSessionId);
  useBackendHealth();

  useEffect(() => {
    setActivePanel(panelByPathname(location.pathname));
  }, [location.pathname, setActivePanel]);

  return (
    <AppShellProviders>
      <div className="h-screen w-screen overflow-hidden">
        <div className="desktop-surface relative grid h-full w-full grid-cols-[auto_minmax(0,1fr)] grid-rows-[minmax(0,1fr)] overflow-hidden">
          {/* Keep an invisible drag strip for macOS overlay mode without rendering a detached title bar */}
          <div
            className="absolute right-0 top-0 z-40 h-4"
            style={{
              left: SHELL_DRAG_STRIP_LEFT,
              WebkitAppRegion: 'drag'
            } as React.CSSProperties}
            data-tauri-drag-region
          />
          <ErrorBoundary resetKey={location.pathname} fallback={<SidebarErrorFallback />}>
            <Sidebar />
          </ErrorBoundary>
          <div className="col-start-2 flex min-h-0 min-w-0 flex-col">
            <BackendHealthBanner />
            <main className="min-h-0 flex-1 overflow-hidden">
              <div className="page-enter h-full overflow-hidden">
                <ErrorBoundary resetKey={location.pathname} fallback={<PageContentErrorFallback />}>
                  <Outlet />
                </ErrorBoundary>
              </div>
            </main>
          </div>
          <ErrorBoundary resetKey={activePanel} fallback={<ShellOverlayErrorFallback />}>
            <ShellOverlays />
          </ErrorBoundary>
        </div>
      </div>
      <ErrorBoundary resetKey={currentSessionId} fallback={null}>
        {/* Control-plane hosts mirror pending interactions into the active chat. */}
        <PermissionModalHost sessionId={currentSessionId} intervalMs={0} />
        <AskDialog sessionId={currentSessionId} intervalMs={0} />
      </ErrorBoundary>
    </AppShellProviders>
  );
};

export default MainLayout;
