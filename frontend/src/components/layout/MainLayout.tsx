import React from 'react';
import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';

const MainLayout: React.FC = () => {
  return (
    <div className="h-screen w-screen overflow-hidden">
      <div className="desktop-surface relative grid h-full w-full grid-cols-[320px_minmax(0,1fr)] grid-rows-[minmax(0,1fr)] overflow-hidden">
        {/* Keep an invisible drag strip for macOS overlay mode without rendering a detached title bar */}
        <div
          className="absolute right-0 top-0 z-50 h-16"
          style={{ left: '78px', WebkitAppRegion: 'drag' } as React.CSSProperties}
          data-tauri-drag-region
        />
        <Sidebar />
        <div className="min-h-0 min-w-0">
          <main className="h-full overflow-hidden">
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
