import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { DEFAULT_SYSTEM_CONFIG } from '@/api/modules/config';
import OnboardingFlow from '@/components/onboarding/OnboardingFlow';

vi.mock('react-i18next', () => ({
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
  it('uses a viewport-filling frame layout and keeps quick mode on provider configuration only', () => {
    vi.stubGlobal('localStorage', {
      getItem: vi.fn(() => null),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    });

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

    expect(container.innerHTML).toContain('h-[clamp(620px,82vh,840px)]');
    expect(screen.getByText('steps.language')).toBeInTheDocument();
    expect(screen.getByText('steps.llmProviders')).toBeInTheDocument();
    expect(screen.queryByText('steps.personality')).not.toBeInTheDocument();
    expect(screen.queryByText('steps.llmModels')).not.toBeInTheDocument();
  });

  it('includes a dedicated model-selection step in expert mode', () => {
    vi.stubGlobal('localStorage', {
      getItem: vi.fn(() => null),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    });

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

    expect(screen.getByText('steps.llmProviders')).toBeInTheDocument();
    expect(screen.getByText('steps.llmModels')).toBeInTheDocument();
  });

  it('renders the mode step with the same heading structure as other onboarding steps', async () => {
    const user = userEvent.setup();

    vi.stubGlobal('localStorage', {
      getItem: vi.fn(() => null),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    });

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

    await user.click(screen.getByRole('button', { name: 'actions.next' }));

    expect(await screen.findByText('mode.label')).toBeInTheDocument();
    expect(screen.getByText('mode.description')).toBeInTheDocument();
    expect(screen.getByText('mode.quick')).toBeInTheDocument();
    expect(screen.getByText('mode.expert')).toBeInTheDocument();
  });
});
