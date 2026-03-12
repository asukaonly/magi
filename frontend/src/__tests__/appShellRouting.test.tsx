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

vi.mock('../pages/Memory', () => ({
  MemoryPage: () => <div data-testid="memory-page">memory-page</div>,
  default: () => <div data-testid="memory-page">memory-page</div>,
}));

vi.mock('../pages/Personality', () => ({
  PersonalityPage: () => <div data-testid="personality-page">personality-page</div>,
  default: () => <div data-testid="personality-page">personality-page</div>,
}));

vi.mock('../components/layout/ShellRouteHost', () => ({
  default: ({ overlay }: { overlay: string }) => (
    <div data-testid={`shell-route-${overlay}`}>{overlay}</div>
  ),
}));

describe('app shell routing', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/chat');
  });

  it('renders settings from the shell instead of through the chat page', async () => {
    window.history.replaceState({}, '', '/settings');
    vi.resetModules();
    const { default: AppRouter } = await import('@/router');

    render(<AppRouter />);

    expect(await screen.findByTestId('shell-route-settings')).toBeInTheDocument();
    expect(screen.queryByTestId('chat-page')).not.toBeInTheDocument();
  });

  it('renders memory and personality as dedicated routes instead of through the chat page', async () => {
    window.history.replaceState({}, '', '/events');
    vi.resetModules();
    const { default: AppRouter } = await import('@/router');
    const { unmount } = render(<AppRouter />);

    expect(await screen.findByTestId('memory-page')).toBeInTheDocument();
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
