import React, { useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { useChatShellStore } from '@/stores';
import { cn } from '@/lib/utils';
import { PanelLeftClose, PanelLeft } from 'lucide-react';
import { panelByPathname } from '@/pages/chat-route-helpers';
import AppShellProviders from './AppShellProviders';
import Sidebar from './Sidebar';
import ShellOverlays from './ShellOverlays';

const MainLayout: React.FC = () => {
  const location = useLocation();
  const { sidebarCollapsed, toggleSidebarCollapsed, setActivePanel } = useChatShellStore();

  useEffect(() => {
    setActivePanel(panelByPathname(location.pathname));
  }, [location.pathname, setActivePanel]);

  return (
    <AppShellProviders>
      <div className="h-screen w-screen overflow-hidden">
        <div
          className={cn(
            "desktop-surface relative grid h-full w-full grid-cols-[320px_minmax(0,1fr)] grid-rows-[minmax(0,1fr)] overflow-hidden",
            sidebarCollapsed && "grid-cols-[0px_minmax(0,1fr)]"
          )}
        >
          {/* Collapse/Expand Button */}
          <button
            onClick={toggleSidebarCollapsed}
            className="absolute left-3 top-3 z-50 rounded-md p-2 transition-colors hover:bg-accent"
            style={{
              left: sidebarCollapsed ? '10px' : '78px',
              transition: 'left 0.2s ease'
            }}
            data-tauri-drag-region={false}
          >
            {sidebarCollapsed ? (
              <PanelLeft className="h-4 w-4" />
            ) : (
              <PanelLeftClose className="h-4 w-4" />
            )}
          </button>

          {/* Keep an invisible drag strip for macOS overlay mode without rendering a detached title bar */}
          <div
            className="absolute right-0 top-0 z-50 h-16"
            style={{
              left: sidebarCollapsed ? '38px' : '78px',
              WebkitAppRegion: 'drag'
            } as React.CSSProperties}
            data-tauri-drag-region
          />
          <Sidebar collapsed={sidebarCollapsed} />
          <div className="min-h-0 min-w-0">
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
