/**
 * Router configuration.
 */
import React from 'react';
import { createBrowserRouter, Navigate, RouterProvider, useRouteError } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import MainLayout from '../components/layout/MainLayout';
import OnboardingLoadError from '../components/onboarding/OnboardingLoadError';
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
const MemorySourcesPage = React.lazy(() =>
  import('../pages/memory-pages').then((m) => ({ default: m.MemorySourcesPage }))
);
const MemorySourceDetailPage = React.lazy(() =>
  import('../pages/memory-pages').then((m) => ({ default: m.MemorySourceDetailPage }))
);
const MemoryPendingPage = React.lazy(() =>
  import('../pages/memory-pages').then((m) => ({ default: m.MemoryPendingPage }))
);
const MemoryStoryPage = React.lazy(() =>
  import('../pages/memory-pages').then((m) => ({ default: m.MemoryStoryPage }))
);
const MemoryEpisodesPage = React.lazy(() =>
  import('../pages/memory-pages').then((m) => ({ default: m.MemoryEpisodesPage }))
);
const MemoryExperienceDetailPage = React.lazy(() =>
  import('../pages/memory-pages').then((m) => ({ default: m.MemoryExperienceDetailPage }))
);
const MemoryExperienceDraftPage = React.lazy(() =>
  import('../pages/memory-pages').then((m) => ({ default: m.MemoryExperienceDraftPage }))
);
const MemoryPortraitPage = React.lazy(() =>
  import('../pages/memory-pages').then((m) => ({ default: m.MemoryPortraitPage }))
);
const MemoryRecallPage = React.lazy(() =>
  import('../pages/memory-pages').then((m) => ({ default: m.MemoryRecallPage }))
);
const MemoryGovernancePage = React.lazy(() =>
  import('../pages/memory-pages').then((m) => ({ default: m.MemoryGovernancePage }))
);
const MemoryEventsPage = React.lazy(() =>
  import('../pages/memory-pages').then((m) => ({ default: m.MemoryEventsPage }))
);
const MemoryKnowledgePage = React.lazy(() =>
  import('../pages/memory-pages').then((m) => ({ default: m.MemoryKnowledgePage }))
);
const MemorySkillsPage = React.lazy(() =>
  import('../pages/memory-pages').then((m) => ({ default: m.MemorySkillsPage }))
);
const PersonalityPage = React.lazy(() =>
  import('../pages/Personality').then((m) => ({ default: m.PersonalityPage }))
);
const BackgroundTasksPage = React.lazy(() =>
  import('../pages/tasks-pages').then((m) => ({ default: m.BackgroundTasksPage }))
);
const ScheduleConfigPage = React.lazy(() =>
  import('../pages/tasks-pages').then((m) => ({ default: m.ScheduleConfigPage }))
);
const ScheduleActivityPage = React.lazy(() =>
  import('../pages/tasks-pages').then((m) => ({ default: m.ScheduleActivityPage }))
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

type OnboardingStatusState = 'loading' | 'complete' | 'incomplete' | 'error';
type OnboardingStatusSnapshot = {
  requireCompleted: boolean;
  status: OnboardingStatusState;
};

const OnboardingGuard: React.FC<{
  children: React.ReactElement;
  requireCompleted: boolean;
}> = ({ children, requireCompleted }) => {
  const { t } = useTranslation('app');
  const [snapshot, setSnapshot] = React.useState<OnboardingStatusSnapshot>({
    requireCompleted,
    status: 'loading',
  });
  const requestIdRef = React.useRef(0);
  const status = snapshot.requireCompleted === requireCompleted
    ? snapshot.status
    : 'loading';

  const check = React.useCallback(async () => {
    const requestId = ++requestIdRef.current;
    setSnapshot({ requireCompleted, status: 'loading' });
    try {
      const response = await configApi.getOnboardingStatus();
      const completed = response.data?.completed;
      if (typeof completed !== 'boolean') {
        throw new Error('Onboarding status response is missing completion state');
      }
      if (requestId === requestIdRef.current) {
        setSnapshot({
          requireCompleted,
          status: completed ? 'complete' : 'incomplete',
        });
      }
    } catch {
      if (requestId === requestIdRef.current) {
        setSnapshot({ requireCompleted, status: 'error' });
      }
    }
  }, [requireCompleted]);

  React.useEffect(() => {
    void check();
    return () => {
      requestIdRef.current += 1;
    };
  }, [check]);

  if (status === 'loading') {
    return <LoadingFallback />;
  }
  if (status === 'error') {
    return (
      <OnboardingLoadError
        title={t('shell.onboardingStatusErrorTitle')}
        description={t('shell.onboardingStatusErrorDescription')}
        retryLabel={t('shell.retryOnboardingStatus')}
        onRetry={() => void check()}
      />
    );
  }
  if (requireCompleted && status === 'incomplete') {
    return <Navigate to="/onboarding" replace />;
  }
  if (!requireCompleted && status === 'complete') {
    return <Navigate to="/" replace />;
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
      <OnboardingGuard requireCompleted={false}>
        <React.Suspense fallback={<LoadingFallback />}>
          <OnboardingPage />
        </React.Suspense>
      </OnboardingGuard>
    ),
  },
  {
    path: '/',
    errorElement: <RouteErrorFallback />,
    element: (
      <OnboardingGuard requireCompleted>
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
        element: <Navigate to="/memory/stories" replace />,
      },
      {
        path: 'memory',
        children: [
          {
            index: true,
            element: (
              <React.Suspense fallback={<LoadingFallback />}>
                <MemoryOverviewPage />
              </React.Suspense>
            ),
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
            path: 'sources',
            element: (
              <React.Suspense fallback={<LoadingFallback />}>
                <MemorySourcesPage />
              </React.Suspense>
            ),
          },
          {
            path: 'sources/:sourceName',
            element: (
              <React.Suspense fallback={<LoadingFallback />}>
                <MemorySourceDetailPage />
              </React.Suspense>
            ),
          },
          {
            path: 'pending',
            element: (
              <React.Suspense fallback={<LoadingFallback />}>
                <MemoryPendingPage />
              </React.Suspense>
            ),
          },
          { path: 'workbench', element: <Navigate to="/memory/recall" replace /> },
          { path: 'reflection', element: <Navigate to="/memory/stories" replace /> },
          {
            path: 'stories',
            element: (
              <React.Suspense fallback={<LoadingFallback />}>
                <MemoryStoryPage />
              </React.Suspense>
            ),
          },
          {
            path: 'episodes',
            element: (
              <React.Suspense fallback={<LoadingFallback />}>
                <MemoryEpisodesPage />
              </React.Suspense>
            ),
          },
          {
            path: 'episode-drafts/:draftId',
            element: (
              <React.Suspense fallback={<LoadingFallback />}>
                <MemoryExperienceDraftPage />
              </React.Suspense>
            ),
          },
          {
            path: 'episodes/:experienceId',
            element: (
              <React.Suspense fallback={<LoadingFallback />}>
                <MemoryExperienceDetailPage />
              </React.Suspense>
            ),
          },
          {
            path: 'portrait',
            element: (
              <React.Suspense fallback={<LoadingFallback />}>
                <MemoryPortraitPage />
              </React.Suspense>
            ),
          },
          {
            path: 'recall',
            element: (
              <React.Suspense fallback={<LoadingFallback />}>
                <MemoryRecallPage />
              </React.Suspense>
            ),
          },
          {
            path: 'governance',
            element: (
              <React.Suspense fallback={<LoadingFallback />}>
                <MemoryGovernancePage />
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
        children: [
          { index: true, element: <Navigate to="/tasks/background" replace /> },
          {
            path: 'background',
            element: (
              <React.Suspense fallback={<LoadingFallback />}>
                <BackgroundTasksPage />
              </React.Suspense>
            ),
          },
          {
            path: 'schedules',
            children: [
              {
                index: true,
                element: (
                  <React.Suspense fallback={<LoadingFallback />}>
                    <ScheduleConfigPage />
                  </React.Suspense>
                ),
              },
              {
                path: 'activity',
                element: (
                  <React.Suspense fallback={<LoadingFallback />}>
                    <ScheduleActivityPage />
                  </React.Suspense>
                ),
              },
            ],
          },
        ],
      },
    ],
  },
]);

const AppRouter: React.FC = () => {
  return <RouterProvider router={router} future={{ v7_startTransition: true }} />;
};

export default AppRouter;
