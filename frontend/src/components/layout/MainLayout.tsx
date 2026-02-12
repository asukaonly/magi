/**
 * MainLayout组件 - 现代化设计
 * 支持可折叠侧边栏
 */
import React, { useState, useEffect } from 'react';
import { Layout } from 'antd';
import { Outlet } from 'react-router-dom';
import Header from './Header';
import Sidebar, { SidebarContext } from './Sidebar';

const { Content } = Layout;

const MainLayoutContent: React.FC = () => {
  const [sidebarWidth, setSidebarWidth] = useState(240);

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
    <Layout
      style={{
        marginLeft: sidebarWidth,
        background: '#f9fafb',
        transition: 'margin-left 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
      }}
      className="sidebar-transition"
    >
      <Header />
      <Content
        style={{
          padding: '24px 32px 32px',
          marginTop: 64,
          minHeight: 'calc(100vh - 64px)',
        }}
      >
        <div className="page-enter">
          <Outlet />
        </div>
      </Content>
    </Layout>
  );
};

const MainLayout: React.FC = () => {
  return (
    <Layout style={{ minHeight: '100vh', background: '#f9fafb' }}>
      <Sidebar />
      <MainLayoutContent />
    </Layout>
  );
};

export default MainLayout;
