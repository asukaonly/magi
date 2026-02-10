/**
 * MainLayout组件 - 现代化设计
 */
import React from 'react';
import { Layout } from 'antd';
import { Outlet } from 'react-router-dom';
import Header from './Header';
import Sidebar from './Sidebar';

const { Content } = Layout;

const MainLayout: React.FC = () => {
  return (
    <Layout style={{ minHeight: '100vh', background: '#f5f7fa' }}>
      <Sidebar />
      <Layout style={{ marginLeft: 200, background: '#f5f7fa' }}>
        <Header />
        <Content
          style={{
            padding: '16px 24px 24px',
            minHeight: 'calc(100vh - 64px)',
          }}
        >
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
};

export default MainLayout;
