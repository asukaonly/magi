/**
 * App主组件 - 现代化主题配置
 */
import React from 'react';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import AppRouter from './router';

const App: React.FC = () => {
  console.log('🔵 App 组件渲染');
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          // 主色：青绿色（替代俗套的紫色）
          colorPrimary: '#0d9488',
          colorPrimaryHover: '#0f766e',
          colorPrimaryActive: '#0d9488',
          colorPrimaryBg: '#f0fdfa',

          // 背景色
          colorBgContainer: '#ffffff',
          colorBgElevated: '#ffffff',
          colorBgLayout: '#f9fafb',

          // 边框色
          colorBorder: '#e5e7eb',
          colorBorderSecondary: '#f3f4f6',

          // 文字色
          colorText: '#111827',
          colorTextSecondary: '#6b7280',
          colorTextTertiary: '#9ca3af',
          colorTextQuaternary: '#d1d5db',

          // 圆角
          borderRadius: 8,
          borderRadiusLG: 8,
          borderRadiusSM: 6,
          borderRadiusXS: 4,

          // 字体
          fontSize: 14,
          fontSizeHeading1: 28,
          fontSizeHeading2: 24,
          fontSizeHeading3: 20,
          fontSizeHeading4: 16,
          fontSizeHeading5: 14,

          // 阴影
          boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
          boxShadowSecondary: '0 1px 2px rgba(0,0,0,0.05)',

          // 间距
          marginXS: 8,
          marginSM: 12,
          margin: 16,
          marginMD: 20,
          marginLG: 24,
          marginXL: 32,
        },
        components: {
          // 卡片组件
          Card: {
            borderRadiusLG: 8,
            boxShadowTertiary: '0 1px 3px rgba(0,0,0,0.05)',
            borderWidth: 1,
            borderColor: '#e5e7eb',
          },

          // 菜单组件（浅色主题）
          Menu: {
            itemBorderRadius: 6,
            itemSelectedBg: '#f0fdfa',
            itemSelectedColor: '#0d9488',
            itemHoverBg: '#f9fafb',
            itemActiveBg: '#f0fdfa',
            itemMarginInline: 8,
            itemPaddingInline: 12,
          },

          // 按钮组件
          Button: {
            borderRadius: 6,
            defaultShadow: '0 1px 2px rgba(0,0,0,0.05)',
            defaultBg: '#ffffff',
            defaultColor: '#111827',
            defaultBorderColor: '#e5e7eb',
            defaultHoverBg: '#f9fafb',
            defaultHoverBorderColor: '#d1d5db',
            primaryShadow: '0 1px 2px rgba(13, 148, 136, 0.2)',
            contentFontSizeLG: 16,
            fontWeight: 500,
          },

          // 输入框组件
          Input: {
            borderRadius: 6,
            borderWidth: 1,
            borderColor: '#e5e7eb',
            hoverBorderColor: '#d1d5db',
            activeBorderColor: '#0d9488',
            colorBgContainer: '#ffffff',
          },
          TextArea: {
            borderRadius: 6,
            borderWidth: 1,
            borderColor: '#e5e7eb',
            hoverBorderColor: '#d1d5db',
            activeBorderColor: '#0d9488',
          },

          // 选择器组件
          Select: {
            borderRadius: 6,
            optionSelectedBg: '#f0fdfa',
            colorBgElevated: '#ffffff',
          },

          // 模态框组件
          Modal: {
            borderRadiusLG: 12,
            contentBg: '#ffffff',
          },

          // 标签页组件
          Tabs: {
            inkBarColor: '#0d9488',
            itemSelectedColor: '#0d9488',
            itemHoverColor: '#0f766e',
            itemActiveColor: '#0d9488',
            cardBg: '#ffffff',
          },

          // 表格组件
          Table: {
            borderColor: '#e5e7eb',
            headerBg: '#f9fafb',
            headerSplitColor: '#e5e7eb',
            rowHoverBg: '#f9fafb',
            borderRadius: 8,
          },

          // 标签组件
          Tag: {
            borderRadiusSM: 4,
            defaultBg: '#f3f4f6',
            defaultColor: '#6b7280',
          },

          // 提示组件
          Tooltip: {
            borderRadius: 6,
            colorBgDefault: '#111827',
          },

          // 下拉菜单
          Dropdown: {
            borderRadius: 8,
          },

          // 分页器
          Pagination: {
            borderRadius: 6,
            itemActiveBg: '#0d9488',
            itemActiveBorderColor: '#0d9488',
          },

          // 进度条
          Progress: {
            colorSuccess: '#10b981',
            colorException: '#ef4444',
            colorInfo: '#3b82f6',
          },

          // 开关
          Switch: {
            colorPrimary: '#0d9488',
            colorPrimaryHover: '#0f766e',
          },

          // 单选框
          Radio: {
            colorPrimary: '#0d9488',
            colorPrimaryHover: '#0f766e',
            buttonSolidCheckedColor: '#0d9488',
            buttonSolidCheckedBg: '#f0fdfa',
            buttonSolidCheckedBorderColor: '#0d9488',
          },

          // 复选框
          Checkbox: {
            colorPrimary: '#0d9488',
            colorPrimaryHover: '#0f766e',
            checkboxBg: '#ffffff',
          },

          // 滑块
          Slider: {
            colorPrimary: '#0d9488',
            colorPrimaryBorderHover: '#0f766e',
            trackBg: '#f0fdfa',
            trackHoverBg: '#f0fdfa',
          },

          // 告警
          Alert: {
            borderRadius: 8,
            infoBg: '#eff6ff',
            infoColor: '#1e40af',
            infoBorderColor: '#bfdbfe',
            successBg: '#ecfdf5',
            successColor: '#065f46',
            successBorderColor: '#a7f3d0',
            warningBg: '#fffbeb',
            warningColor: '#92400e',
            warningBorderColor: '#fde68a',
            errorBg: '#fef2f2',
            errorColor: '#991b1b',
            errorBorderColor: '#fecaca',
          },

          // 时间线
          Timeline: {
            dotBg: '#ffffff',
          },

          // 消息提示
          message: {
            borderRadius: 8,
          },

          // 通知
          notification: {
            borderRadius: 8,
          },

          // 分割线
          Divider: {
            colorSplit: '#e5e7eb',
            colorText: '#6b7280',
          },

          // 描述列表
          Descriptions: {
            labelBg: '#f9fafb',
          },
        },
      }}
    >
      <AppRouter />
    </ConfigProvider>
  );
};

export default App;
