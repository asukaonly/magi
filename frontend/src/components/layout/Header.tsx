import React, { useEffect, useState } from 'react';
import { LogOut, Settings, UserRound } from 'lucide-react';
import { useLocation } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

const pageTitleMap: Record<string, string> = {
  '/': '仪表盘',
  '/chat': 'AI 对话',
  '/personality': '人格配置',
  '/events': '记忆查看',
  '/settings': '系统设置',
};

const Header: React.FC<{ sidebarWidth?: number }> = ({ sidebarWidth = 240 }) => {
  const location = useLocation();
  const [currentSidebarWidth, setCurrentSidebarWidth] = useState(sidebarWidth);

  useEffect(() => {
    const handleSidebarToggle = (event: Event) => {
      const customEvent = event as CustomEvent<{ width: number }>;
      setCurrentSidebarWidth(customEvent.detail.width);
    };
    window.addEventListener('sidebar-toggle', handleSidebarToggle);
    return () => window.removeEventListener('sidebar-toggle', handleSidebarToggle);
  }, []);

  const pageTitle = pageTitleMap[location.pathname] || 'Magi AI Framework';

  return (
    <header
      className={cn(
        'fixed right-0 top-0 z-10 flex h-16 items-center justify-between border-b bg-background/85 px-8 backdrop-blur transition-[left] duration-300'
      )}
      style={{ left: currentSidebarWidth }}
    >
      <h1 className="text-lg font-semibold">{pageTitle}</h1>
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="icon" onClick={() => (window.location.href = '/settings')}>
          <Settings className="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="icon">
          <UserRound className="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="icon">
          <LogOut className="h-4 w-4" />
        </Button>
      </div>
    </header>
  );
};

export default Header;
