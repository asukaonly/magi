import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

const { localStorageMock } = vi.hoisted(() => {
  const mock = {
    getItem: vi.fn((_key: string): string | null => null),
    setItem: vi.fn((_key: string, _value: string) => undefined),
    removeItem: vi.fn((_key: string) => undefined),
  };
  vi.stubGlobal('localStorage', mock);
  return { localStorageMock: mock };
});

import { apiClient } from '@/api/client';
import { configApi, DEFAULT_SYSTEM_CONFIG } from '@/api/modules/config';
import { personasApi } from '@/api/modules/personas';
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
  afterEach(() => {
    vi.restoreAllMocks();
    localStorageMock.getItem.mockReturnValue(null);
    localStorageMock.setItem.mockClear();
    localStorageMock.removeItem.mockClear();
  });

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

  it('activates the locale default seed after quick onboarding completes', async () => {
    const user = userEvent.setup();
    const initialConfig = {
      ...DEFAULT_SYSTEM_CONFIG,
      preferences: {
        ...DEFAULT_SYSTEM_CONFIG.preferences,
        language: 'en' as const,
        user_mode: 'quick' as const,
        scenario: 'chat_assistant',
      },
    };
    localStorageMock.getItem.mockImplementation((key: string) => {
      if (key === 'magi_onboarding_state') {
        return JSON.stringify({
          phase: 'guided',
          mode: 'quick',
          current: 2,
          scenario: 'chat_assistant',
          values: initialConfig,
        });
      }
      return null;
    });
    vi.spyOn(configApi, 'completeOnboarding').mockResolvedValue({ success: true, message: 'ok', data: initialConfig } as any);
    vi.spyOn(personasApi, 'seed').mockResolvedValue({ success: true, data: { created_ids: [] } } as any);
    vi.spyOn(personasApi, 'seedPreviews').mockResolvedValue({
      success: true,
      data: [
        {
          seed_slug: 'nova_assistant',
          name: 'Nova',
          description: '',
          avatar: '',
          group: 'general',
          order: 1,
        },
        {
          seed_slug: 'echo_ai_ssistant',
          name: 'Echo-01',
          description: '',
          avatar: '',
          group: 'general',
          order: 2,
        },
      ],
    } as any);
    vi.spyOn(personasApi, 'list').mockResolvedValue({
      success: true,
      data: [
        {
          persona_id: 'uuid-echo',
          name: 'Echo-01',
          slug: 'echo_ai_ssistant',
          locale: 'zh',
          avatar_path: '',
          group_name: 'general',
          sort_order: 2,
          is_builtin: true,
          description: '',
        },
        {
          persona_id: 'uuid-nova',
          name: 'Nova',
          slug: 'nova_assistant',
          locale: 'en',
          avatar_path: '',
          group_name: 'general',
          sort_order: 1,
          is_builtin: true,
          description: '',
        },
      ],
    } as any);
    vi.spyOn(personasApi, 'setActive').mockResolvedValue({ success: true, persona_id: 'uuid-nova' });
    vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: {
        success: true,
        data: {
          ready: true,
          status: 'ready',
          runtime_ready: true,
          runtime_status: 'ready',
        },
      },
    });

    render(<OnboardingFlow initialConfig={initialConfig} />);

    await user.click(await screen.findByRole('button', { name: 'actions.enterApp' }));

    await waitFor(() => expect(personasApi.setActive).toHaveBeenCalledWith('uuid-nova'));
    expect(personasApi.seedPreviews).toHaveBeenCalledWith('en');
  });
});
