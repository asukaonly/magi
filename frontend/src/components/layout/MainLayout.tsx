import React, { useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { useChatShellStore } from '@/stores';
import { panelByPathname } from '@/pages/chat-route-helpers';
import AppShellProviders from './AppShellProviders';
import Sidebar from './Sidebar';
import ShellOverlays from './ShellOverlays';

const SHELL_DRAG_STRIP_LEFT = '84px';

const MainLayout: React.FC = () => {
  const location = useLocation();
  const setActivePanel = useChatShellStore((state) => state.setActivePanel);

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
          <div className="col-start-2 min-h-0 min-w-0">
            <main className="h-full overflow-hidden">
              <div className="page-enter h-full overflow-hidden">
                <Outlet />
              </div>
            </main>
          </div>
          <ShellOverlays />
        </div>
      </div>
    </AppShellProviders>
  );
};

export default MainLayout;
