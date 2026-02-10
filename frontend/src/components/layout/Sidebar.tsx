/**
 * Sidebar组件 - 现代化设计
 */
import React from 'react';
import { Layout, Menu } from 'antd';
import {
  DashboardOutlined,
  RobotOutlined,
  UnorderedListOutlined,
  ToolOutlined,
  DatabaseOutlined,
  LineChartOutlined,
  SettingOutlined,
  MessageOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { useNavigate, useLocation } from 'react-router-dom';

const { Sider } = Layout;

const Sidebar: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();

  const menuItems = [
    {
      key: '/',
      icon: <DashboardOutlined />,
      label: '仪表盘',
    },
    {
      key: '/agents',
      icon: <RobotOutlined />,
      label: 'Agent管理',
    },
    {
      key: '/tasks',
      icon: <UnorderedListOutlined />,
      label: '任务管理',
    },
    {
      key: '/tools',
      icon: <ToolOutlined />,
      label: '工具管理',
    },
    {
      key: '/memory',
      icon: <DatabaseOutlined />,
      label: '记忆管理',
    },
    {
      key: '/metrics',
      icon: <LineChartOutlined />,
      label: '指标监控',
    },
    {
      key: '/personality',
      icon: <UserOutlined />,
      label: '人格配置',
    },
    {
      key: '/settings',
      icon: <SettingOutlined />,
      label: '系统设置',
    },
    {
      key: '/chat',
      icon: <MessageOutlined />,
      label: 'AI 对话',
    },
  ];

  const handleMenuClick = ({ key }: { key: string }) => {
    navigate(key);
  };

  return (
    <Sider
      width={200}
      style={{
        background: '#fff',
        borderRight: '1px solid #e8e8e8',
        overflow: 'hidden',
        height: '100vh',
        position: 'fixed',
        left: 0,
        top: 0,
        boxShadow: '2px 0 8px rgba(0,0,0,0.04)',
        zIndex: 10,
      }}
    >
      {/* Logo Area */}
      <div
        style={{
          height: 64,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          borderBottom: '1px solid #e8e8e8',
          background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
        }}
      >
        <span
          style={{
            color: '#fff',
            fontSize: 20,
            fontWeight: 700,
            letterSpacing: '0.5px',
          }}
        >
          Magi
        </span>
      </div>

      {/* Menu */}
      <Menu
        mode="inline"
        selectedKeys={[location.pathname]}
        items={menuItems}
        onClick={handleMenuClick}
        style={{
          borderRight: 0,
          paddingTop: '8px',
        }}
      />
    </Sider>
  );
};

export default Sidebar;
