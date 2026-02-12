/**
 * Header组件 - 现代化设计
 * 极简风格：浅色背景、细线边框、微妙阴影
 */
import React, { useState, useEffect } from 'react';
import { Layout, Space, Dropdown, Avatar, Typography } from 'antd';
import { UserOutlined, SettingOutlined, LogoutOutlined } from '@ant-design/icons';
import type { MenuProps } from 'antd';
import { useLocation } from 'react-router-dom';

const { Header: AntHeader } = Layout;
const { Text } = Typography;

// 页面标题映射
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
    const handleSidebarToggle = (e: Event) => {
      const customEvent = e as CustomEvent<{ collapsed: boolean; width: number }>;
      setCurrentSidebarWidth(customEvent.detail.width);
    };

    window.addEventListener('sidebar-toggle', handleSidebarToggle);

    return () => {
      window.removeEventListener('sidebar-toggle', handleSidebarToggle);
    };
  }, []);

  const menuItems: MenuProps['items'] = [
    {
      key: 'settings',
      icon: <SettingOutlined />,
      label: '设置',
      onClick: () => window.location.href = '/settings',
    },
    {
      type: 'divider',
    },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: '退出',
      danger: true,
    },
  ];

  // 获取当前页面标题
  const pageTitle = pageTitleMap[location.pathname] || 'Magi AI Framework';

  return (
    <AntHeader
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        background: 'rgba(255, 255, 255, 0.9)',
        backdropFilter: 'blur(12px)',
        borderBottom: '1px solid #e5e7eb',
        padding: '0 32px',
        height: 64,
        position: 'fixed',
        top: 0,
        left: currentSidebarWidth,
        right: 0,
        zIndex: 9,
        transition: 'left 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
      }}
      className="sidebar-transition"
    >
      {/* 左侧：页面标题 */}
      <Text style={{ fontSize: 18, fontWeight: 600, color: '#111827' }}>
        {pageTitle}
      </Text>

      {/* 右侧：用户操作 */}
      <Space size="middle">
        <Dropdown menu={{ items: menuItems }} placement="bottomRight" trigger={['click']}>
          <Avatar
            icon={<UserOutlined />}
            style={{
              cursor: 'pointer',
              background: '#0d9488',
              border: '2px solid #e5e7eb',
              transition: 'all 0.2s ease',
            }}
          />
        </Dropdown>
      </Space>
    </AntHeader>
  );
};

export default Header;
