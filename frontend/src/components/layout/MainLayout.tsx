import React from 'react';
import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import Header from './Header';
import { cn } from '@/lib/utils';
import { useChatShellStore } from '@/stores';

const MainLayout: React.FC = () => {
  const sidebarCollapsed = useChatShellStore((state) => state.sidebarCollapsed);

  return (
    <div className="h-screen p-3">
      <div
        className={cn(
          'desktop-surface grid h-full overflow-hidden rounded-[22px]',
          sidebarCollapsed ? 'grid-cols-[72px_minmax(0,1fr)]' : 'grid-cols-[280px_minmax(0,1fr)]'
        )}
      >
        <Sidebar />
        <div className="flex min-w-0 flex-col">
          <Header />
          <main className="min-h-0 flex-1">
            <div className="page-enter h-full">
              <Outlet />
            </div>
          </main>
        </div>
      </div>
    </div>
  );
};

export default MainLayout;

