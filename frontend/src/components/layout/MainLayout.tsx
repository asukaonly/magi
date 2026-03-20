import React, { useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useChatShellStore, useChatTraceStore } from '@/stores';
import { cn } from '@/lib/utils';
import { PanelLeftClose, PanelLeft } from 'lucide-react';
import { panelByPathname } from '@/pages/chat-route-helpers';
import AppShellProviders from './AppShellProviders';
import Sidebar from './Sidebar';
import ShellOverlays from './ShellOverlays';

const SHELL_TOGGLE_LEFT = '84px';
const SHELL_TOGGLE_TOP = '14px';
const SHELL_DRAG_STRIP_LEFT = '120px';

const MainLayout: React.FC = () => {
  const { t } = useTranslation('app');
  const location = useLocation();
  const { sidebarCollapsed, toggleSidebarCollapsed, setActivePanel } = useChatShellStore();
  const drawerOpen = useChatTraceStore((state) => state.drawerOpen);

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
          {!drawerOpen ? (
            <button
              type="button"
              onClick={toggleSidebarCollapsed}
              className="absolute z-[60] flex h-7 w-7 items-center justify-center rounded-md border border-border/30 bg-card/75 text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground"
              style={{
                left: SHELL_TOGGLE_LEFT,
                top: SHELL_TOGGLE_TOP,
                transition: 'left 0.2s ease'
              }}
              aria-label={sidebarCollapsed ? t('shell.expandSidebar') : t('shell.collapseSidebar')}
              title={sidebarCollapsed ? t('shell.expandSidebar') : t('shell.collapseSidebar')}
              data-tauri-drag-region={false}
            >
              {sidebarCollapsed ? (
                <PanelLeft className="h-3.5 w-3.5" />
              ) : (
                <PanelLeftClose className="h-3.5 w-3.5" />
              )}
            </button>
          ) : null}

          {/* Keep an invisible drag strip for macOS overlay mode without rendering a detached title bar */}
          <div
            className="absolute right-0 top-0 z-40 h-4"
            style={{
              left: SHELL_DRAG_STRIP_LEFT,
              WebkitAppRegion: 'drag'
            } as React.CSSProperties}
            data-tauri-drag-region
          />
          <Sidebar collapsed={sidebarCollapsed} />
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
