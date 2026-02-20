import React, { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  Database,
  LayoutDashboard,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  UserRound,
  Zap,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export const SidebarContext = React.createContext<{
  collapsed: boolean;
  toggleCollapse: () => void;
  sidebarWidth: number;
}>({
  collapsed: false,
  toggleCollapse: () => undefined,
  sidebarWidth: 240,
});

const Sidebar: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const sidebarWidth = collapsed ? 64 : 240;

  useEffect(() => {
    const savedCollapsed = localStorage.getItem('sidebar-collapsed') === 'true';
    setCollapsed(savedCollapsed);
  }, []);

  const menuItems = [
    { key: '/', icon: LayoutDashboard, label: '仪表盘' },
    { key: '/chat', icon: MessageSquare, label: 'AI 对话' },
    { key: '/personality', icon: UserRound, label: '人格配置' },
    { key: '/events', icon: Database, label: '记忆查看' },
    { key: '/settings', icon: Settings, label: '系统设置' },
  ];

  const toggleCollapse = () => {
    const next = !collapsed;
    setCollapsed(next);
    localStorage.setItem('sidebar-collapsed', String(next));
    window.dispatchEvent(new CustomEvent('sidebar-toggle', { detail: { collapsed: next, width: next ? 64 : 240 } }));
  };

  return (
    <SidebarContext.Provider value={{ collapsed, toggleCollapse, sidebarWidth }}>
      <aside
        className={cn(
          'fixed left-0 top-0 z-20 h-screen border-r bg-card transition-all duration-300',
          collapsed ? 'w-16' : 'w-60'
        )}
      >
        <div className={cn('flex h-16 items-center border-b px-4', collapsed ? 'justify-center px-0' : 'gap-2')}>
          <Zap className="h-5 w-5 text-primary" />
          {!collapsed && (
            <div className="flex flex-col">
              <span className="text-base font-semibold">Magi</span>
              <span className="text-[11px] text-muted-foreground">AI Framework</span>
            </div>
          )}
        </div>

        <nav className="space-y-1 p-3">
          {menuItems.map((item) => {
            const Icon = item.icon;
            const active = location.pathname === item.key;
            return (
              <button
                key={item.key}
                type="button"
                onClick={() => navigate(item.key)}
                className={cn(
                  'flex h-10 w-full items-center rounded-md px-3 text-sm transition-colors',
                  active ? 'bg-accent text-accent-foreground' : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                  collapsed && 'justify-center px-0'
                )}
              >
                <Icon className="h-4 w-4 shrink-0" />
                {!collapsed && <span className="ml-2">{item.label}</span>}
              </button>
            );
          })}
        </nav>

        <div className="absolute bottom-3 left-0 w-full px-3">
          <Button variant="outline" className={cn('w-full', collapsed && 'px-0')} onClick={toggleCollapse}>
            {collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
          </Button>
        </div>
      </aside>
    </SidebarContext.Provider>
  );
};

export default Sidebar;
