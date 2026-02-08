/**
 * 路由配置
 */
import React from 'react';
import { createBrowserRouter, RouterProvider } from 'react-router-dom';
import MainLayout from '../components/layout/MainLayout';
import Dashboard from '../pages/Dashboard';

// 懒加载页面
const AgentsPage = React.lazy(() =>
  import('../pages/Agents').then((m) => ({ default: m.AgentsPage }))
);
const TasksPage = React.lazy(() =>
  import('../pages/Tasks').then((m) => ({ default: m.TasksPage }))
);
const ToolsPage = React.lazy(() =>
  import('../pages/Tools').then((m) => ({ default: m.ToolsPage }))
);
const MemoryPage = React.lazy(() =>
  import('../pages/Memory').then((m) => ({ default: m.MemoryPage }))
);
const MetricsPage = React.lazy(() =>
  import('../pages/Metrics').then((m) => ({ default: m.MetricsPage }))
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
        path: 'agents',
        element: (
          <React.Suspense fallback={<div>Loading...</div>}>
            <AgentsPage />
          </React.Suspense>
        ),
      },
      {
        path: 'tasks',
        element: (
          <React.Suspense fallback={<div>Loading...</div>}>
            <TasksPage />
          </React.Suspense>
        ),
      },
      {
        path: 'tools',
        element: (
          <React.Suspense fallback={<div>Loading...</div>}>
            <ToolsPage />
          </React.Suspense>
        ),
      },
      {
        path: 'memory',
        element: (
          <React.Suspense fallback={<div>Loading...</div>}>
            <MemoryPage />
          </React.Suspense>
        ),
      },
      {
        path: 'metrics',
        element: (
          <React.Suspense fallback={<div>Loading...</div>}>
            <MetricsPage />
          </React.Suspense>
        ),
      },
    ],
  },
]);

const AppRouter: React.FC = () => {
  return <RouterProvider router={router} />;
};

export default AppRouter;
