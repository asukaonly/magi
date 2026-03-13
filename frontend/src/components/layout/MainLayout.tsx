import React, { useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useChatShellStore } from '@/stores';
import { cn } from '@/lib/utils';
import { PanelLeftClose, PanelLeft } from 'lucide-react';
import { panelByPathname } from '@/pages/chat-route-helpers';
import AppShellProviders from './AppShellProviders';
import Sidebar from './Sidebar';
import ShellOverlays from './ShellOverlays';

const SHELL_TOGGLE_LEFT = '78px';
const SHELL_DRAG_STRIP_LEFT = '124px';

const MainLayout: React.FC = () => {
  const { t } = useTranslation('app');
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
            type="button"
            onClick={toggleSidebarCollapsed}
            className="absolute top-3 z-[60] flex h-10 w-10 items-center justify-center rounded-xl border border-border/40 bg-card/90 text-muted-foreground shadow-sm transition-colors hover:bg-muted hover:text-foreground"
            style={{
              left: SHELL_TOGGLE_LEFT,
              transition: 'left 0.2s ease'
            }}
            aria-label={sidebarCollapsed ? t('shell.expandSidebar') : t('shell.collapseSidebar')}
            title={sidebarCollapsed ? t('shell.expandSidebar') : t('shell.collapseSidebar')}
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
            className="absolute right-0 top-0 z-40 h-14"
            style={{
              left: SHELL_DRAG_STRIP_LEFT,
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
