import React, { useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { useChatShellStore, useConversationStore } from '@/stores';
import { useBackendHealth } from '@/hooks/useBackendHealth';
import { panelByPathname } from '@/pages/chat-route-helpers';
import AppShellProviders from './AppShellProviders';
import BackendHealthBanner from './BackendHealthBanner';
import Sidebar from './Sidebar';
import ShellOverlays from './ShellOverlays';
import { PermissionModalHost, AskDialog } from '@/components/control';

const SHELL_DRAG_STRIP_LEFT = '84px';

const MainLayout: React.FC = () => {
  const location = useLocation();
  const setActivePanel = useChatShellStore((state) => state.setActivePanel);
  const currentSessionId = useConversationStore((state) => state.currentSessionId);
  useBackendHealth();

  useEffect(() => {
    setActivePanel(panelByPathname(location.pathname));
  }, [location.pathname, setActivePanel]);

  return (
    <AppShellProviders>
      <div className="h-screen w-screen overflow-hidden">
        <div className="desktop-surface relative grid h-full w-full grid-cols-[320px_minmax(0,1fr)] grid-rows-[minmax(0,1fr)] overflow-hidden">
          {/* Keep an invisible drag strip for macOS overlay mode without rendering a detached title bar */}
          <div
            className="absolute right-0 top-0 z-40 h-4"
            style={{
              left: SHELL_DRAG_STRIP_LEFT,
              WebkitAppRegion: 'drag'
            } as React.CSSProperties}
            data-tauri-drag-region
          />
          <Sidebar />
          <div className="col-start-2 flex min-h-0 min-w-0 flex-col">
            <BackendHealthBanner />
            <main className="min-h-0 flex-1 overflow-hidden">
              <div className="page-enter h-full overflow-hidden">
                <Outlet />
              </div>
            </main>
          </div>
          <ShellOverlays />
        </div>
      </div>
      {/* Control-plane hosts are mounted app-wide so prompts from
          background subagents surface regardless of the active page. */}
      <PermissionModalHost sessionId={currentSessionId} intervalMs={0} />
      <AskDialog sessionId={currentSessionId} intervalMs={5000} />
    </AppShellProviders>
  );
};

export default MainLayout;
