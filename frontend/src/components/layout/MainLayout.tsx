import React from 'react';
import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import Header from './Header';
import { cn } from '@/lib/utils';
import { useChatShellStore } from '@/stores';

const MainLayout: React.FC = () => {
  const sidebarCollapsed = useChatShellStore((state) => state.sidebarCollapsed);

  return (
    <div className="h-screen w-screen overflow-hidden">
      <div
        className={cn(
          'grid h-full overflow-hidden bg-card/60',
          sidebarCollapsed ? 'grid-cols-[72px_minmax(0,1fr)]' : 'grid-cols-[280px_minmax(0,1fr)]'
        )}
      >
        <Sidebar />
        <div className="flex min-w-0 flex-col">
          <Header />
          <main className="min-h-0 flex-1 overflow-hidden">
            <div className="page-enter h-full overflow-hidden">
              <Outlet />
            </div>
          </main>
        </div>
      </div>
    </div>
  );
};

export default MainLayout;
