/**
 * Header组件 - 现代化设计
 */
import React from 'react';
import { Layout, Space, Dropdown, Avatar, Typography } from 'antd';
import { UserOutlined, SettingOutlined, LogoutOutlined } from '@ant-design/icons';
import type { MenuProps } from 'antd';

const { Header: AntHeader } = Layout;
const { Text } = Typography;

const Header: React.FC = () => {
  const menuItems: MenuProps['items'] = [
    {
      key: 'settings',
      icon: <SettingOutlined />,
      label: '设置',
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

  return (
    <AntHeader
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        background: '#fff',
        borderBottom: '1px solid #e8e8e8',
        padding: '0 24px',
        height: 64,
        lineHeight: '64px',
        position: 'fixed',
        top: 0,
        left: 200,
        right: 0,
        zIndex: 9,
        boxShadow: '0 1px 4px rgba(0,0,0,0.04)',
      }}
    >
      <Space>
        <Text strong style={{ fontSize: 16 }}>
          Magi AI Agent Framework
        </Text>
      </Space>

      <Space size="middle">
        <Dropdown menu={{ items: menuItems }} placement="bottomRight">
          <Avatar
            icon={<UserOutlined />}
            style={{
              cursor: 'pointer',
              background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
            }}
          />
        </Dropdown>
      </Space>
    </AntHeader>
  );
};

export default Header;
