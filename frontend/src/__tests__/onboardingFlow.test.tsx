import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

const { localStorageMock } = vi.hoisted(() => {
  const mock = {
    getItem: vi.fn(() => null),
    setItem: vi.fn(),
    removeItem: vi.fn(),
  };
  vi.stubGlobal('localStorage', mock);
  return { localStorageMock: mock };
});

import { DEFAULT_SYSTEM_CONFIG } from '@/api/modules/config';
import OnboardingFlow from '@/components/onboarding/OnboardingFlow';

vi.mock('react-i18next', () => ({
  initReactI18next: {
    type: '3rdParty',
    init: vi.fn(),
  },
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: {
      resolvedLanguage: 'zh-CN',
      language: 'zh-CN',
      changeLanguage: vi.fn(),
      on: vi.fn(),
      off: vi.fn(),
    },
  }),
}));

vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
}));

describe('OnboardingFlow', () => {
  it('shows the welcome entrypoint first and keeps quick mode focused on scenario and provider setup', async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);

    const { container } = render(
      <OnboardingFlow
        initialConfig={{
          ...DEFAULT_SYSTEM_CONFIG,
          preferences: {
            ...DEFAULT_SYSTEM_CONFIG.preferences,
            user_mode: 'quick',
          },
        }}
      />
    );

    expect(container.innerHTML).toContain('fixed inset-0');
    expect(screen.getByText('welcome.title')).toBeInTheDocument();
    expect(screen.getByText('welcome.subtitle')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'welcome.quickMode welcome.quickModeDesc' }));

    expect(await screen.findByText('steps.scenario')).toBeInTheDocument();
    expect(screen.getByText('steps.llmProviders')).toBeInTheDocument();
    expect(screen.queryByText('steps.personality')).not.toBeInTheDocument();
    expect(screen.queryByText('steps.llmModels')).not.toBeInTheDocument();
  });

  it('includes a dedicated model-selection step after entering expert mode', async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);

    render(
      <OnboardingFlow
        initialConfig={{
          ...DEFAULT_SYSTEM_CONFIG,
          preferences: {
            ...DEFAULT_SYSTEM_CONFIG.preferences,
            user_mode: 'expert',
          },
        }}
      />
    );

    await user.click(screen.getByRole('button', { name: 'welcome.expertMode welcome.expertModeDesc' }));

    expect(await screen.findByText('steps.llmProviders')).toBeInTheDocument();
    expect(screen.getByText('steps.llmModels')).toBeInTheDocument();
  });

  it('renders the welcome mode selection entrypoint with both mode cards', () => {
    localStorageMock.getItem.mockReturnValue(null);

    render(
      <OnboardingFlow
        initialConfig={{
          ...DEFAULT_SYSTEM_CONFIG,
          preferences: {
            ...DEFAULT_SYSTEM_CONFIG.preferences,
            user_mode: null,
          },
        }}
      />
    );

    expect(screen.getByText('welcome.title')).toBeInTheDocument();
    expect(screen.getByText('welcome.subtitle')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'welcome.quickMode welcome.quickModeDesc' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'welcome.expertMode welcome.expertModeDesc' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '中文' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'EN' })).toBeInTheDocument();
  });
});
