import { Outlet } from 'react-router-dom';
import { act, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock('../api/modules/config', async () => {
  const actual = await vi.importActual<typeof import('../api/modules/config')>('../api/modules/config');
  return {
    ...actual,
    configApi: {
      ...actual.configApi,
      get: vi.fn().mockResolvedValue({
        data: {
          preferences: {
            onboarding_completed: true,
          },
        },
      }),
    },
  };
});

vi.mock('../components/layout/MainLayout', () => ({
  default: () => (
    <div data-testid="main-layout">
      <Outlet />
    </div>
  ),
}));

vi.mock('../pages/Chat', () => ({
  ChatPage: () => <div data-testid="chat-page">chat-page</div>,
}));

vi.mock('../pages/Timeline', () => ({
  TimelinePage: () => <div data-testid="timeline-page">timeline-page</div>,
}));

vi.mock('../pages/Onboarding', () => ({
  default: () => <div data-testid="onboarding-page">onboarding-page</div>,
}));

vi.mock('../pages/memory-pages', () => ({
  MemoryOverviewPage: () => <div data-testid="memory-overview-page">memory-overview-page</div>,
  MemorySourcesPage: () => <div data-testid="memory-sources-page">memory-sources-page</div>,
  MemorySourceDetailPage: () => <div data-testid="memory-source-detail-page">memory-source-detail-page</div>,
  MemoryPendingPage: () => <div data-testid="memory-pending-page">memory-pending-page</div>,
  MemoryEventsPage: () => <div data-testid="memory-events-page">memory-events-page</div>,
  MemoryKnowledgePage: () => <div data-testid="memory-knowledge-page">memory-knowledge-page</div>,
  MemorySkillsPage: () => <div data-testid="memory-skills-page">memory-skills-page</div>,
  MemoryStoryPage: () => <div data-testid="memory-story-page">memory-story-page</div>,
  MemoryEpisodesPage: () => <div data-testid="memory-episodes-page">memory-episodes-page</div>,
  MemoryPortraitPage: () => <div data-testid="memory-portrait-page">memory-portrait-page</div>,
  MemoryRecallPage: () => <div data-testid="memory-recall-page">memory-recall-page</div>,
  MemoryGovernancePage: () => <div data-testid="memory-governance-page">memory-governance-page</div>,
}));

vi.mock('../pages/Personality', () => ({
  PersonalityPage: () => <div data-testid="personality-page">personality-page</div>,
  default: () => <div data-testid="personality-page">personality-page</div>,
}));

describe('app shell routing', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/chat');
  });

  it('renders memory routes and personality as dedicated routes instead of through the chat page', async () => {
    window.history.replaceState({}, '', '/memory/overview');
    vi.resetModules();
    const { default: AppRouter } = await import('@/router');
    let unmount!: () => void;
    await act(async () => {
      ({ unmount } = render(<AppRouter />));
    });

    expect(await screen.findByTestId('memory-overview-page')).toBeInTheDocument();
    expect(screen.queryByTestId('chat-page')).not.toBeInTheDocument();

    unmount();
    window.history.replaceState({}, '', '/memory/pending');
    vi.resetModules();
    const pendingRouter = await import('@/router');
    await act(async () => {
      ({ unmount } = render(<pendingRouter.default />));
    });

    expect(await screen.findByTestId('memory-pending-page')).toBeInTheDocument();
    expect(screen.queryByTestId('chat-page')).not.toBeInTheDocument();

    unmount();
    window.history.replaceState({}, '', '/personality');
    vi.resetModules();
    const nextRouter = await import('@/router');
    await act(async () => {
      render(<nextRouter.default />);
    });

    expect(await screen.findByTestId('personality-page')).toBeInTheDocument();
    expect(screen.queryByTestId('chat-page')).not.toBeInTheDocument();
  });
});
