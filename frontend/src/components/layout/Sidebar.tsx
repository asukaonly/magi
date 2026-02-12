/**
 * Sidebar组件 - 现代化可折叠设计
 * 参考 Linear/Raycast 风格：浅色、细线边框、微妙阴影
 */
import React, { useState, useEffect } from 'react';
import { Layout, Menu, Button } from 'antd';
import {
  DashboardOutlined,
  SettingOutlined,
  MessageOutlined,
  UserOutlined,
  DatabaseOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  ThunderboltFilled,
} from '@ant-design/icons';
import { useNavigate, useLocation } from 'react-router-dom';

const { Sider } = Layout;

// 创建 sidebar context
export const SidebarContext = React.createContext<{
  collapsed: boolean;
  toggleCollapse: () => void;
  sidebarWidth: number;
}>({
  collapsed: false,
  toggleCollapse: () => {},
  sidebarWidth: 240,
});

const Sidebar: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const sidebarWidth = collapsed ? 64 : 240;

  // 从 localStorage 恢复折叠状态
  useEffect(() => {
    const savedCollapsed = localStorage.getItem('sidebar-collapsed') === 'true';
    if (savedCollapsed !== collapsed) {
      setCollapsed(savedCollapsed);
    }
  }, []);

  const menuItems = [
    {
      key: '/',
      icon: <DashboardOutlined />,
      label: '仪表盘',
    },
    {
      key: '/chat',
      icon: <MessageOutlined />,
      label: 'AI 对话',
    },
    {
      key: '/personality',
      icon: <UserOutlined />,
      label: '人格配置',
    },
    {
      key: '/events',
      icon: <DatabaseOutlined />,
      label: '记忆查看',
    },
    {
      key: '/settings',
      icon: <SettingOutlined />,
      label: '系统设置',
    },
  ];

  const handleMenuClick = ({ key }: { key: string }) => {
    navigate(key);
  };

  const toggleCollapse = () => {
    const newCollapsed = !collapsed;
    setCollapsed(newCollapsed);
    localStorage.setItem('sidebar-collapsed', String(newCollapsed));

    // 触发自定义事件通知其他组件
    window.dispatchEvent(new CustomEvent('sidebar-toggle', {
      detail: { collapsed: newCollapsed, width: newCollapsed ? 64 : 240 }
    }));
  };

  return (
    <SidebarContext.Provider value={{ collapsed, toggleCollapse, sidebarWidth }}>
      <Sider
        width={240}
        collapsedWidth={64}
        collapsed={collapsed}
        collapsible
        trigger={null}
        style={{
          background: '#ffffff',
          borderRight: '1px solid #e5e7eb',
          overflow: 'hidden',
          height: '100vh',
          position: 'fixed',
          left: 0,
          top: 0,
          boxShadow: '1px 0 3px rgba(0,0,0,0.05)',
          zIndex: 10,
        }}
        className="sidebar-transition"
      >
        {/* Logo Area */}
        <div
          style={{
            height: 64,
            display: 'flex',
            alignItems: 'center',
            justifyContent: collapsed ? 'center' : 'flex-start',
            gap: 8,
            padding: collapsed ? 0 : '0 20px',
            borderBottom: '1px solid #e5e7eb',
            transition: 'all 0.3s ease',
          }}
        >
          {!collapsed ? (
            <>
              <ThunderboltFilled style={{ fontSize: 24, color: '#0d9488' }} />
              <div style={{ display: 'flex', flexDirection: 'column' }}>
                <span
                  style={{
                    color: '#111827',
                    fontSize: 18,
                    fontWeight: 700,
                    lineHeight: 1,
                  }}
                >
                  Magi
                </span>
                <span
                  style={{
                    color: '#9ca3af',
                    fontSize: 11,
                    fontWeight: 400,
                    lineHeight: 1.4,
                  }}
                >
                  AI Framework
                </span>
              </div>
            </>
          ) : (
            <ThunderboltFilled style={{ fontSize: 20, color: '#0d9488' }} />
          )}
        </div>

        {/* Menu - 使用 inlineCollapsed 控制折叠 */}
        <Menu
          mode="inline"
          theme="light"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={handleMenuClick}
          inlineCollapsed={collapsed}
          inlineIndent={16}
          style={{
            borderRight: 0,
            paddingTop: '12px',
            background: 'transparent',
          }}
        />

        {/* 折叠按钮 */}
        <div
          style={{
            position: 'absolute',
            bottom: 16,
            left: 0,
            right: 0,
            display: 'flex',
            justifyContent: collapsed ? 'center' : 'flex-end',
            paddingRight: collapsed ? 0 : 12,
            padding: collapsed ? 0 : '0 12px',
          }}
        >
          <Button
            type="text"
            icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            onClick={toggleCollapse}
            style={{
              width: collapsed ? 40 : '100%',
              height: 36,
              display: 'flex',
              alignItems: 'center',
              justifyContent: collapsed ? 'center' : 'center',
              color: '#6b7280',
              border: '1px solid #e5e7eb',
              borderRadius: 6,
              transition: 'all 0.2s ease',
            }}
          />
        </div>
      </Sider>
    </SidebarContext.Provider>
  );
};

export default Sidebar;
