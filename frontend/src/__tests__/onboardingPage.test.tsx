import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { DEFAULT_SYSTEM_CONFIG } from '@/api/modules/config';
import OnboardingPage from '@/pages/Onboarding';

const { getOnboardingStatusMock, getOnboardingTemplateMock, navigateMock } = vi.hoisted(() => ({
  getOnboardingStatusMock: vi.fn(),
  getOnboardingTemplateMock: vi.fn(),
  navigateMock: vi.fn(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock('react-router', () => ({
  useNavigate: () => navigateMock,
}));

vi.mock('@/api/modules/config', async () => {
  const actual = await vi.importActual<typeof import('@/api/modules/config')>('@/api/modules/config');
  return {
    ...actual,
    configApi: {
      ...actual.configApi,
      getOnboardingStatus: getOnboardingStatusMock,
      getOnboardingTemplate: getOnboardingTemplateMock,
    },
  };
});

vi.mock('@/components/onboarding/OnboardingFlow', () => ({
  default: () => <div data-testid="onboarding-flow">onboarding-flow</div>,
}));

vi.mock('@/components/plugins/PluginInstallPanel', () => ({
  PluginInstallPanel: () => <div data-testid="plugin-install-panel" />,
}));

vi.mock('@/components/layout/DesktopTitleBar', () => ({
  DesktopTitleBar: ({ fixed }: { fixed?: boolean }) => (
    <div data-fixed={String(Boolean(fixed))} data-testid="desktop-title-bar" />
  ),
}));

describe('OnboardingPage', () => {
  beforeEach(() => {
    localStorage.clear();
    getOnboardingStatusMock.mockReset();
    getOnboardingStatusMock.mockResolvedValue({ data: { completed: false } });
    getOnboardingTemplateMock.mockReset();
    navigateMock.mockReset();
  });

  it('does not substitute defaults when the onboarding template fails', async () => {
    const user = userEvent.setup();
    getOnboardingTemplateMock.mockRejectedValueOnce(new Error('template unavailable'));

    render(<OnboardingPage />);

    expect(screen.getByTestId('desktop-title-bar')).toHaveAttribute('data-fixed', 'false');
    expect(screen.getByTestId('onboarding-window-content')).toContainElement(
      await screen.findByText('page.loadConfigFailed'),
    );
    expect(screen.queryByTestId('onboarding-flow')).not.toBeInTheDocument();

    getOnboardingTemplateMock.mockResolvedValueOnce({
      data: { config: DEFAULT_SYSTEM_CONFIG },
    });
    await user.click(screen.getByRole('button', { name: 'page.retryLoadConfig' }));

    expect(await screen.findByTestId('onboarding-flow')).toBeInTheDocument();
    expect(screen.getByTestId('desktop-title-bar')).toHaveAttribute('data-fixed', 'false');
  });

  it('removes credentials from an older browser snapshot before loading the backend draft', async () => {
    localStorage.setItem('magi_onboarding_state', JSON.stringify({
      version: 1,
      current: 2,
      values: {
        preferences: { language: 'zh' },
        llm: {
          providers: {
            openai: { api_key: 'sk-stale-browser-secret' },
          },
        },
      },
      seedSlug: 'ember',
      api_key: 'sk-stale-root-secret',
    }));
    getOnboardingTemplateMock.mockRejectedValueOnce(new Error('template unavailable'));

    render(<OnboardingPage />);

    expect(await screen.findByText('page.loadConfigFailed')).toBeInTheDocument();
    const stored = localStorage.getItem('magi_onboarding_state') || '';
    expect(stored).not.toContain('sk-stale-browser-secret');
    expect(stored).not.toContain('sk-stale-root-secret');
    expect(stored).not.toContain('api_key');
    expect(JSON.parse(stored).values).toEqual({
      preferences: { language: 'zh' },
    });
  });

  it('treats a successful response without a template as a load failure', async () => {
    getOnboardingTemplateMock.mockResolvedValueOnce({ data: null });

    render(<OnboardingPage />);

    expect(await screen.findByText('page.loadConfigFailed')).toBeInTheDocument();
    expect(screen.queryByTestId('onboarding-flow')).not.toBeInTheDocument();
  });

  it('redirects when onboarding completes between the status and template requests', async () => {
    getOnboardingTemplateMock.mockRejectedValueOnce(new Error('already completed'));
    getOnboardingStatusMock.mockResolvedValueOnce({ data: { completed: true } });

    render(<OnboardingPage />);

    await vi.waitFor(() => expect(navigateMock).toHaveBeenCalledWith('/', { replace: true }));
    expect(screen.queryByText('page.loadConfigFailed')).not.toBeInTheDocument();
    expect(screen.queryByTestId('onboarding-flow')).not.toBeInTheDocument();
  });
});
