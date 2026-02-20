/**
 * 路由配置
 */
import React from 'react';
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import MainLayout from '../components/layout/MainLayout';
import Dashboard from '../pages/Dashboard';
import { configApi } from '../api/modules/config';
import { LoadingSpinner } from '../components/ui/loading-spinner';

// 懒加载页面
const SettingsPage = React.lazy(() =>
  import('../pages/Settings').then((m) => ({ default: m.SettingsPage }))
);
const ChatPage = React.lazy(() =>
  import('../pages/Chat').then((m) => ({ default: m.ChatPage }))
);
const PersonalityPage = React.lazy(() =>
  import('../pages/PersonalityModern').then((m) => ({ default: m.default }))
);
const EventsPage = React.lazy(() =>
  import('../pages/Events').then((m) => ({ default: m.default }))
);
const OnboardingPage = React.lazy(() =>
  import('../pages/Onboarding').then((m) => ({ default: m.default }))
);

// 加载组件
const LoadingFallback = () => (
  <LoadingFallbackInner />
);

const LoadingFallbackInner = () => {
  const { t } = useTranslation('app');
  return (
    <div className="flex h-screen items-center justify-center bg-background text-muted-foreground">
      <div className="flex items-center gap-3">
        <LoadingSpinner className="h-6 w-6" />
        <span className="text-sm">{t('common.loading')}</span>
      </div>
    </div>
  );
};

const OnboardingGuard: React.FC<{ children: React.ReactElement }> = ({ children }) => {
  const [loading, setLoading] = React.useState(true);
  const [completed, setCompleted] = React.useState(false);

  React.useEffect(() => {
    const check = async () => {
      try {
        const response = await configApi.get();
        setCompleted(!!response.data?.preferences?.onboarding_completed);
      } catch {
        setCompleted(false);
      } finally {
        setLoading(false);
      }
    };
    void check();
  }, []);

  if (loading) {
    return <LoadingFallback />;
  }
  if (!completed) {
    return <Navigate to="/onboarding" replace />;
  }
  return children;
};

const router = createBrowserRouter([
  {
    path: '/onboarding',
    element: (
      <React.Suspense fallback={<LoadingFallback />}>
        <OnboardingPage />
      </React.Suspense>
    ),
  },
  {
    path: '/',
    element: (
      <OnboardingGuard>
        <MainLayout />
      </OnboardingGuard>
    ),
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
