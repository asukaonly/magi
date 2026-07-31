import { Outlet, useNavigate } from 'react-router';
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { getOnboardingStatusMock } = vi.hoisted(() => ({
  getOnboardingStatusMock: vi.fn(),
}));

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
      getOnboardingStatus: getOnboardingStatusMock,
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

vi.mock('../pages/Onboarding', () => {
  function OnboardingPageMock() {
    const navigate = useNavigate();
    return (
      <div data-testid="onboarding-page">
        onboarding-page
        <button type="button" onClick={() => navigate('/')}>
          finish-onboarding
        </button>
      </div>
    );
  }

  return { default: OnboardingPageMock };
});

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
    localStorage.clear();
    getOnboardingStatusMock.mockReset();
    getOnboardingStatusMock.mockResolvedValue({ data: { completed: true } });
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

  it('stops on a retryable error when onboarding status cannot be read', async () => {
    const user = userEvent.setup();
    getOnboardingStatusMock
      .mockRejectedValueOnce(new Error('backend unavailable'))
      .mockResolvedValueOnce({ data: { completed: true } });
    vi.resetModules();
    const { default: AppRouter } = await import('@/router');

    await act(async () => {
      render(<AppRouter />);
    });

    expect(await screen.findByText('shell.onboardingStatusErrorTitle')).toBeInTheDocument();
    expect(screen.queryByTestId('onboarding-page')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'shell.retryOnboardingStatus' }));

    expect(await screen.findByTestId('chat-page')).toBeInTheDocument();
  });

  it('routes incomplete installations to onboarding', async () => {
    getOnboardingStatusMock.mockResolvedValue({ data: { completed: false } });
    vi.resetModules();
    const { default: AppRouter } = await import('@/router');

    await act(async () => {
      render(<AppRouter />);
    });

    expect(await screen.findByTestId('onboarding-page')).toBeInTheDocument();
    expect(screen.queryByTestId('main-layout')).not.toBeInTheDocument();
  });

  it('redirects completed installations away from onboarding', async () => {
    window.history.replaceState({}, '', '/onboarding');
    vi.resetModules();
    const { default: AppRouter } = await import('@/router');

    await act(async () => {
      render(<AppRouter />);
    });

    expect(await screen.findByTestId('chat-page')).toBeInTheDocument();
    expect(screen.queryByTestId('onboarding-page')).not.toBeInTheDocument();
  });

  it('removes legacy onboarding credentials before opening a completed installation', async () => {
    localStorage.setItem('magi_onboarding_state', JSON.stringify({
      version: 1,
      current: 3,
      values: {
        preferences: { language: 'en' },
        llm: {
          providers: {
            openai: { api_key: 'sk-legacy-secret' },
          },
        },
      },
      apiKey: 'sk-root-secret',
    }));
    vi.resetModules();
    const { default: AppRouter } = await import('@/router');

    await act(async () => {
      render(<AppRouter />);
    });

    expect(await screen.findByTestId('chat-page')).toBeInTheDocument();
    const stored = localStorage.getItem('magi_onboarding_state') || '';
    expect(stored).not.toContain('sk-legacy-secret');
    expect(stored).not.toContain('sk-root-secret');
    expect(stored).not.toContain('api_key');
    expect(JSON.parse(stored).values).toEqual({
      preferences: { language: 'en' },
    });
  });

  it('rechecks completion when leaving onboarding for the main app', async () => {
    const user = userEvent.setup();
    getOnboardingStatusMock.mockResolvedValueOnce({ data: { completed: false } });
    window.history.replaceState({}, '', '/onboarding');
    vi.resetModules();
    const { default: AppRouter } = await import('@/router');

    await act(async () => {
      render(<AppRouter />);
    });

    expect(await screen.findByTestId('onboarding-page')).toBeInTheDocument();
    getOnboardingStatusMock.mockResolvedValue({ data: { completed: true } });
    await user.click(screen.getByRole('button', { name: 'finish-onboarding' }));

    expect(await screen.findByTestId('chat-page')).toBeInTheDocument();
    expect(getOnboardingStatusMock).toHaveBeenCalledTimes(2);
  });
});
