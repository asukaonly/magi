import { Outlet } from 'react-router-dom';
import { render, screen } from '@testing-library/react';
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
  MemoryWorkbenchPage: () => <div data-testid="memory-workbench-page">memory-workbench-page</div>,
  MemoryEventsPage: () => <div data-testid="memory-events-page">memory-events-page</div>,
  MemoryKnowledgePage: () => <div data-testid="memory-knowledge-page">memory-knowledge-page</div>,
  MemoryReflectionPage: () => <div data-testid="memory-reflection-page">memory-reflection-page</div>,
  MemorySkillsPage: () => <div data-testid="memory-skills-page">memory-skills-page</div>,
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
    const { unmount } = render(<AppRouter />);

    expect(await screen.findByTestId('memory-overview-page')).toBeInTheDocument();
    expect(screen.queryByTestId('chat-page')).not.toBeInTheDocument();

    unmount();
    window.history.replaceState({}, '', '/personality');
    vi.resetModules();
    const nextRouter = await import('@/router');
    render(<nextRouter.default />);

    expect(await screen.findByTestId('personality-page')).toBeInTheDocument();
    expect(screen.queryByTestId('chat-page')).not.toBeInTheDocument();
  });
});
