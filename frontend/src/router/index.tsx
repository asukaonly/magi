/**
 * Router configuration.
 */
import React from 'react';
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import MainLayout from '../components/layout/MainLayout';
import ShellRouteHost from '../components/layout/ShellRouteHost';
import { configApi } from '../api/modules/config';
import { LoadingSpinner } from '../components/ui/loading-spinner';

const ChatPage = React.lazy(() =>
  import('../pages/Chat').then((m) => ({ default: m.ChatPage }))
);
const TimelinePage = React.lazy(() =>
  import('../pages/Timeline').then((m) => ({ default: m.TimelinePage }))
);
const MemoryPage = React.lazy(() =>
  import('../pages/Memory').then((m) => ({ default: m.MemoryPage }))
);
const PersonalityPage = React.lazy(() =>
  import('../pages/Personality').then((m) => ({ default: m.PersonalityPage }))
);
const OnboardingPage = React.lazy(() =>
  import('../pages/Onboarding').then((m) => ({ default: m.default }))
);

// Lazy-loaded route components
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
        element: <Navigate to="/chat" replace />,
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
        path: 'settings',
        element: (
          <React.Suspense fallback={<LoadingFallback />}>
            <ShellRouteHost overlay="settings" />
          </React.Suspense>
        ),
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
        path: 'events',
        element: (
          <React.Suspense fallback={<LoadingFallback />}>
            <MemoryPage />
          </React.Suspense>
        ),
      },
      {
        path: 'timeline',
        element: (
          <React.Suspense fallback={<LoadingFallback />}>
            <TimelinePage />
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
