/**
 * 路由配置
 */
import React from 'react';
import { createBrowserRouter, RouterProvider } from 'react-router-dom';
import MainLayout from '../components/layout/MainLayout';
import Dashboard from '../pages/Dashboard';
import { Spin } from 'antd';

// 懒加载页面
const SettingsPage = React.lazy(() =>
  import('../pages/Settings').then((m) => ({ default: m.SettingsPage }))
);
const ChatPage = React.lazy(() =>
  import('../pages/Chat').then((m) => ({ default: m.ChatPage }))
);
const PersonalityPage = React.lazy(() =>
  import('../pages/Personality').then((m) => ({ default: m.default }))
);
const EventsPage = React.lazy(() =>
  import('../pages/Events').then((m) => ({ default: m.default }))
);

// 加载组件
const LoadingFallback = () => (
  <div
    style={{
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      height: '100vh',
      background: '#f9fafb',
    }}
  >
    <Spin size="large" tip="加载中..." />
  </div>
);

const router = createBrowserRouter([
  {
    path: '/',
    element: <MainLayout />,
    children: [
      {
        index: true,
        element: <Dashboard />,
      },
      {
        path: 'personality',
        element: (
          <React.Suspense fallback={<LoadingFallback />}>
            <PersonalityPage />
          </React.Suspense>
        ),
      },
      {
        path: 'settings',
        element: (
          <React.Suspense fallback={<LoadingFallback />}>
            <SettingsPage />
          </React.Suspense>
        ),
      },
      {
        path: 'chat',
        element: (
          <React.Suspense fallback={<LoadingFallback />}>
            <ChatPage />
          </React.Suspense>
        ),
      },
      {
        path: 'events',
        element: (
          <React.Suspense fallback={<LoadingFallback />}>
            <EventsPage />
          </React.Suspense>
        ),
      },
    ],
  },
]);

const AppRouter: React.FC = () => {
  console.log('🚀 AppRouter 渲染');
  return <RouterProvider router={router} />;
};

export default AppRouter;
