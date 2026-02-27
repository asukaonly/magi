import React, { useState, useEffect } from 'react';
import { Outlet } from 'react-router-dom';
import { useLocation } from 'react-router-dom';
import Header from './Header';
import Sidebar from './Sidebar';

const MainLayoutContent: React.FC = () => {
  const [sidebarWidth, setSidebarWidth] = useState(240);
  const location = useLocation();
  const isChatPage = location.pathname === '/chat';

  // 初始化时从 localStorage 读取折叠状态
  useEffect(() => {
    const collapsed = localStorage.getItem('sidebar-collapsed') === 'true';
    setSidebarWidth(collapsed ? 64 : 240);

    // 监听侧边栏切换事件
    const handleSidebarToggle = (e: Event) => {
      const customEvent = e as CustomEvent<{ collapsed: boolean; width: number }>;
      setSidebarWidth(customEvent.detail.width);
    };

    window.addEventListener('sidebar-toggle', handleSidebarToggle);

    return () => {
      window.removeEventListener('sidebar-toggle', handleSidebarToggle);
    };
  }, []);

  return (
    <div
      className="h-screen overflow-hidden bg-background transition-[margin] duration-300"
      style={{ marginLeft: sidebarWidth }}
    >
      <Header />
      <main
        className={isChatPage
          ? 'h-[calc(100vh-64px)] overflow-hidden px-0'
          : 'h-[calc(100vh-64px)] overflow-y-auto px-8 pb-8 pt-6'}
        style={{ marginTop: 64 }}
      >
        <div className={isChatPage ? 'page-enter h-full' : 'page-enter'}>
          <Outlet />
        </div>
      </main>
    </div>
  );
};

const MainLayout: React.FC = () => {
  return (
    <div className="min-h-screen bg-background">
      <Sidebar />
      <MainLayoutContent />
    </div>
  );
};

export default MainLayout;
