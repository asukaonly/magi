/**
 * Router configuration.
 */
import React from 'react';
import { createBrowserRouter, Navigate, RouterProvider, useRouteError } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import MainLayout from '../components/layout/MainLayout';
import { configApi } from '../api/modules/config';
import { LoadingSpinner } from '../components/ui/loading-spinner';

const ChatPage = React.lazy(() =>
  import('../pages/Chat').then((m) => ({ default: m.ChatPage }))
);
const TimelinePage = React.lazy(() =>
  import('../pages/Timeline').then((m) => ({ default: m.TimelinePage }))
);
const MemoryOverviewPage = React.lazy(() =>
  import('../pages/memory-pages').then((m) => ({ default: m.MemoryOverviewPage }))
);
const MemoryWorkbenchPage = React.lazy(() =>
  import('../pages/memory-pages').then((m) => ({ default: m.MemoryWorkbenchPage }))
);
const MemoryEventsPage = React.lazy(() =>
  import('../pages/memory-pages').then((m) => ({ default: m.MemoryEventsPage }))
);
const MemoryKnowledgePage = React.lazy(() =>
  import('../pages/memory-pages').then((m) => ({ default: m.MemoryKnowledgePage }))
);
const MemoryReflectionPage = React.lazy(() =>
  import('../pages/memory-pages').then((m) => ({ default: m.MemoryReflectionPage }))
);
const MemorySkillsPage = React.lazy(() =>
  import('../pages/memory-pages').then((m) => ({ default: m.MemorySkillsPage }))
);
const PersonalityPage = React.lazy(() =>
  import('../pages/Personality').then((m) => ({ default: m.PersonalityPage }))
);
const TasksPage = React.lazy(() =>
  import('../pages/Tasks').then((m) => ({ default: m.TasksPage }))
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

function RouteErrorFallback() {
  const { t } = useTranslation('app');
  const error = useRouteError();
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className="flex h-screen flex-col items-center justify-center gap-4 bg-background p-8 text-foreground">
      <h1 className="text-xl font-semibold">{t('shell.routeErrorTitle')}</h1>
      <pre className="max-w-xl overflow-auto rounded-md bg-muted p-4 text-sm text-muted-foreground">{message}</pre>
      <button
        type="button"
        className="rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground hover:bg-primary/90"
        onClick={() => window.location.reload()}
      >
        {t('shell.reload')}
      </button>
    </div>
  );
}

const router = createBrowserRouter([
  {
    path: '/onboarding',
    errorElement: <RouteErrorFallback />,
    element: (
      <React.Suspense fallback={<LoadingFallback />}>
        <OnboardingPage />
      </React.Suspense>
    ),
  },
  {
    path: '/',
    errorElement: <RouteErrorFallback />,
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
            <MemoryOverviewPage />
          </React.Suspense>
        ),
      },
      {
        path: 'memory',
        children: [
          {
            index: true,
            element: <Navigate to="/memory/overview" replace />,
          },
          {
            path: 'overview',
            element: (
              <React.Suspense fallback={<LoadingFallback />}>
                <MemoryOverviewPage />
              </React.Suspense>
            ),
          },
          {
            path: 'workbench',
            element: (
              <React.Suspense fallback={<LoadingFallback />}>
                <MemoryWorkbenchPage />
              </React.Suspense>
            ),
          },
          {
            path: 'events',
            element: (
              <React.Suspense fallback={<LoadingFallback />}>
                <MemoryEventsPage />
              </React.Suspense>
            ),
          },
          {
            path: 'knowledge',
            element: (
              <React.Suspense fallback={<LoadingFallback />}>
                <MemoryKnowledgePage />
              </React.Suspense>
            ),
          },
          {
            path: 'reflection',
            element: (
              <React.Suspense fallback={<LoadingFallback />}>
                <MemoryReflectionPage />
              </React.Suspense>
            ),
          },
          {
            path: 'skills',
            element: (
              <React.Suspense fallback={<LoadingFallback />}>
                <MemorySkillsPage />
              </React.Suspense>
            ),
          },
        ],
      },
      {
        path: 'timeline',
        element: (
          <React.Suspense fallback={<LoadingFallback />}>
            <TimelinePage />
          </React.Suspense>
        ),
      },
      {
        path: 'tasks',
        element: (
          <React.Suspense fallback={<LoadingFallback />}>
            <TasksPage />
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
