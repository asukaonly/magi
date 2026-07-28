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

describe('OnboardingPage', () => {
  beforeEach(() => {
    getOnboardingStatusMock.mockReset();
    getOnboardingStatusMock.mockResolvedValue({ data: { completed: false } });
    getOnboardingTemplateMock.mockReset();
    navigateMock.mockReset();
  });

  it('does not substitute defaults when the onboarding template fails', async () => {
    const user = userEvent.setup();
    getOnboardingTemplateMock.mockRejectedValueOnce(new Error('template unavailable'));

    render(<OnboardingPage />);

    expect(await screen.findByText('page.loadConfigFailed')).toBeInTheDocument();
    expect(screen.queryByTestId('onboarding-flow')).not.toBeInTheDocument();

    getOnboardingTemplateMock.mockResolvedValueOnce({
      data: { config: DEFAULT_SYSTEM_CONFIG },
    });
    await user.click(screen.getByRole('button', { name: 'page.retryLoadConfig' }));

    expect(await screen.findByTestId('onboarding-flow')).toBeInTheDocument();
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
