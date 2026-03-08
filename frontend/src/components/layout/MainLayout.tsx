import React from 'react';
import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';

const MainLayout: React.FC = () => {
  return (
    <div className="h-screen w-screen overflow-hidden">
      {/* Title bar drag region for macOS overlay mode - excludes traffic light buttons area */}
      <div
        className="absolute right-0 top-0 z-50 h-8"
        style={{ left: '72px', WebkitAppRegion: 'drag' } as React.CSSProperties}
        data-tauri-drag-region
      />
      <div className="mt-8 grid h-[calc(100vh-2rem)] grid-cols-[320px_minmax(0,1fr)] grid-rows-[minmax(0,1fr)] overflow-hidden bg-card/60">
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
