import React, { useEffect } from 'react';
import { Outlet, useLocation } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useChatShellStore, useConversationStore } from '@/stores';
import { useBackendHealth } from '@/hooks/useBackendHealth';
import { useActivePersona } from '@/hooks/useActivePersona';
import { panelByPathname, shouldRenderChatWorkspace } from '@/domain/chat/shell-routing';
import { DEFAULT_USER_ID } from '@/constants';
import AppShellProviders from './AppShellProviders';
import { AppTitleBar } from './AppTitleBar';
import BackendHealthBanner from './BackendHealthBanner';
import Sidebar from './Sidebar';
import ShellOverlays from './ShellOverlays';
import { MemoryPortraitRail } from '@/components/chat/MemoryPortraitRail';
import { PortraitFloater } from '@/components/chat/portrait/PortraitFloater';
import { PermissionModalHost, AskDialog } from '@/components/control';
import { ErrorBoundary } from '@/components/ui/ErrorBoundary';
import { ChatWorkspaceProvider } from '@/stores/chat-workspace-context';
import { ProductTour } from '@/components/onboarding/ProductTour';
import { useProductTourFlag } from '@/hooks/useProductTourFlag';
import { PluginInstallPanel } from '@/components/plugins/PluginInstallPanel';

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

const PortraitRailHost: React.FC = () => {
  const portraitRailOpen = useChatShellStore((s) => s.portraitRailOpen);
  const viewportIsNarrow = useChatShellStore((s) => s.viewportIsNarrow);
  const currentSessionId = useConversationStore((s) => s.currentSessionId);
  const { persona } = useActivePersona();
  if (!portraitRailOpen || !currentSessionId || !persona) {
    return null;
  }
  const props = {
    sessionId: currentSessionId,
    userId: DEFAULT_USER_ID,
    personaId: persona.personaId,
  };
  return viewportIsNarrow ? <PortraitFloater {...props} /> : <MemoryPortraitRail {...props} />;
};

const MainLayout: React.FC = () => {
  const location = useLocation();
  const activePanel = useChatShellStore((state) => state.activePanel);
  const setActivePanel = useChatShellStore((state) => state.setActivePanel);
  const setViewportIsNarrow = useChatShellStore((state) => state.setViewportIsNarrow);
  const viewportIsNarrow = useChatShellStore((state) => state.viewportIsNarrow);
  const portraitRailOpen = useChatShellStore((state) => state.portraitRailOpen);
  const currentSessionId = useConversationStore((state) => state.currentSessionId);
  const { completed: tourCompleted, loaded: tourLoaded, markCompleted: markTour } = useProductTourFlag();
  useBackendHealth();

  useEffect(() => {
    setActivePanel(panelByPathname(location.pathname));
  }, [location.pathname, setActivePanel]);

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return;
    }
    const mql = window.matchMedia('(max-width: 1279px)');
    const apply = (matches: boolean) => setViewportIsNarrow(matches);
    apply(mql.matches);
    const listener = (e: MediaQueryListEvent) => apply(e.matches);
    mql.addEventListener('change', listener);
    return () => mql.removeEventListener('change', listener);
  }, [setViewportIsNarrow]);

  // Portrait rail is chat-shell scoped. Hide it (and collapse the grid
  // back to two columns) whenever the user navigates to timeline, memory,
  // settings, or any other non-chat route.
  const isChatRoute = shouldRenderChatWorkspace(location.pathname);
  const railVisible = isChatRoute && portraitRailOpen;
  const railColumnVisible = railVisible && !viewportIsNarrow;
  const gridColsClass = railColumnVisible
    ? 'grid-cols-[auto_minmax(0,1fr)_auto]'
    : 'grid-cols-[auto_minmax(0,1fr)]';

  return (
    <AppShellProviders>
      <ChatWorkspaceProvider>
        <div className="flex h-screen w-screen flex-col overflow-hidden">
          <AppTitleBar />
          <div className={`desktop-surface relative grid min-h-0 w-full flex-1 ${gridColsClass} grid-rows-[minmax(0,1fr)] overflow-hidden`}>
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
            {railColumnVisible ? (
              <ErrorBoundary resetKey={currentSessionId} fallback={null}>
                <PortraitRailHost />
              </ErrorBoundary>
            ) : null}
            {viewportIsNarrow && railVisible ? (
              <ErrorBoundary resetKey={currentSessionId} fallback={null}>
                <PortraitRailHost />
              </ErrorBoundary>
            ) : null}
            <ErrorBoundary resetKey={activePanel} fallback={<ShellOverlayErrorFallback />}>
              <ShellOverlays />
            </ErrorBoundary>
          </div>
        </div>
      </ChatWorkspaceProvider>
      <ErrorBoundary resetKey={currentSessionId} fallback={null}>
        {/* Control-plane hosts mirror pending interactions into the active chat. */}
        <PermissionModalHost sessionId={currentSessionId} intervalMs={0} />
        <AskDialog sessionId={currentSessionId} intervalMs={0} />
      </ErrorBoundary>
      {/* One-time post-onboarding first context prompt. Best-effort: never blocks chat. */}
      <ErrorBoundary resetKey={String(tourCompleted)} fallback={null}>
        {tourLoaded && !tourCompleted ? <ProductTour onComplete={() => void markTour()} /> : null}
      </ErrorBoundary>
      {/* Single mounted plugin-connect panel; opened from first-run prompt/empty-state/side-card
          via usePluginInstallPanelStore. Renders null until a plugin is selected. */}
      <ErrorBoundary fallback={null}>
        <PluginInstallPanel />
      </ErrorBoundary>
    </AppShellProviders>
  );
};

export default MainLayout;
