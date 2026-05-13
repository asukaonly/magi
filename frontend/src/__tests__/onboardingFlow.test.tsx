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
import { skillsApi } from '@/api';
import { configApi, DEFAULT_SYSTEM_CONFIG } from '@/api/modules/config';
import { personasApi } from '@/api/modules/personas';
import { pluginsApi } from '@/api/modules/plugins';
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
  const parseLatestOnboardingState = () => {
    const call = [...localStorageMock.setItem.mock.calls]
      .reverse()
      .find(([key]) => key === 'magi_onboarding_state');

    expect(call).toBeTruthy();
    return JSON.parse(call?.[1] as string);
  };

  afterEach(() => {
    vi.restoreAllMocks();
    localStorageMock.getItem.mockReturnValue(null);
    localStorageMock.setItem.mockClear();
    localStorageMock.removeItem.mockClear();
  });

  it('shows the welcome entrypoint first and keeps quick mode focused on scenario and LLM setup', async () => {
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
    expect(screen.getByText('steps.llmModels')).toBeInTheDocument();
    expect(screen.queryByText('steps.personality')).not.toBeInTheDocument();
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

  it('applies the lightweight chat preset before moving quick onboarding into LLM setup', async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);

    render(
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

    await user.click(screen.getByRole('button', { name: 'welcome.quickMode welcome.quickModeDesc' }));
    await user.click(await screen.findByRole('button', { name: /scenario\.chatAssistant/ }));
    await user.click(screen.getByRole('button', { name: 'actions.next' }));

    const savedState = parseLatestOnboardingState();

    expect(savedState.scenario).toBe('chat_assistant');
    expect(savedState.values.memory.retention_days).toBe(60);
    expect(savedState.values.memory.l2.enabled).toBe(false);
    expect(savedState.values.memory.l3.enabled).toBe(false);
    expect(savedState.values.memory.l4.enabled).toBe(false);
    expect(savedState.values.tools.builtIn.weather.enabled).toBe(false);
    expect(savedState.values.agent.background_tasks.auto_detect_long_task).toBe(false);
  });

  it('applies the research-oriented preset for knowledge partner quick onboarding', async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);

    render(
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

    await user.click(screen.getByRole('button', { name: 'welcome.quickMode welcome.quickModeDesc' }));
    await user.click(await screen.findByRole('button', { name: /scenario\.knowledgePartner/ }));
    await user.click(screen.getByRole('button', { name: 'actions.next' }));

    const savedState = parseLatestOnboardingState();

    expect(savedState.scenario).toBe('knowledge_partner');
    expect(savedState.values.memory.retention_days).toBe(365);
    expect(savedState.values.memory.query_expansion.enabled).toBe(true);
    expect(savedState.values.memory.l3.enabled).toBe(true);
    expect(savedState.values.memory.l4.enabled).toBe(true);
    expect(savedState.values.tools.builtIn.weather.enabled).toBe(false);
    expect(savedState.values.agent.background_tasks.auto_detect_long_task).toBe(true);
  });

  it('blocks quick onboarding while selected sensor plugins are not installed', async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    vi.spyOn(pluginsApi, 'getRegistry').mockResolvedValue({
      registry_version: 'test',
      plugins: [
        {
          plugin_id: 'chrome-history',
          name: 'Chrome History',
          name_i18n: {},
          version: '1.0.0',
          description: 'Chrome visits',
          description_i18n: {},
          author: 'Magi',
          official: true,
          contribution_types: ['sensor'],
          platforms: [],
          min_sdk_version: '0.1.0',
          homepage: '',
          repository: '',
          path: 'chrome-history',
          installed: false,
          installed_version: null,
          update_available: false,
        },
        {
          plugin_id: 'git-activity',
          name: 'Git Activity',
          name_i18n: {},
          version: '1.0.0',
          description: 'Git commits',
          description_i18n: {},
          author: 'Magi',
          official: true,
          contribution_types: ['sensor'],
          platforms: [],
          min_sdk_version: '0.1.0',
          homepage: '',
          repository: '',
          path: 'git-activity',
          installed: false,
          installed_version: null,
          update_available: false,
        },
      ],
    });

    render(
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

    await user.click(screen.getByRole('button', { name: 'welcome.quickMode welcome.quickModeDesc' }));
    await user.click(await screen.findByRole('button', { name: /scenario\.knowledgePartner/ }));
    await user.click(screen.getByRole('button', { name: 'actions.next' }));

    await screen.findByText('Chrome History');
    const nextButton = screen.getByRole('button', { name: 'actions.next' });

    await waitFor(() => expect(nextButton).toBeDisabled());

    await user.click(screen.getByRole('button', { name: /Chrome History/ }));
    await user.click(screen.getByRole('button', { name: /Git Activity/ }));

    await waitFor(() => expect(nextButton).toBeEnabled());
  });

  it('activates the scenario-mapped seed after quick onboarding completes', async () => {
    const user = userEvent.setup();
    const initialConfig = {
      ...DEFAULT_SYSTEM_CONFIG,
      preferences: {
        ...DEFAULT_SYSTEM_CONFIG.preferences,
        language: 'en' as const,
        user_mode: 'quick' as const,
        scenario: 'knowledge_partner',
      },
    };
    localStorageMock.getItem.mockImplementation((key: string) => {
      if (key === 'magi_onboarding_state') {
        return JSON.stringify({
          phase: 'guided',
          mode: 'quick',
          current: 4,
          scenario: 'knowledge_partner',
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
          seed_slug: 'halberd',
          name: 'Halberd',
          description: '',
          avatar: '',
          group: 'general',
          order: 4,
        },
        {
          seed_slug: 'nova',
          name: 'Nova',
          description: '',
          avatar: '',
          group: 'general',
          order: 1,
        },
      ],
    } as any);
    vi.spyOn(personasApi, 'list').mockResolvedValue({
      success: true,
      data: [
        {
          persona_id: 'uuid-halberd',
          name: 'Halberd',
          slug: 'halberd',
          locale: 'en',
          avatar_path: '',
          group_name: 'general',
          sort_order: 4,
          is_builtin: true,
          description: '',
        },
        {
          persona_id: 'uuid-nova',
          name: 'Nova',
          slug: 'nova',
          locale: 'en',
          avatar_path: '',
          group_name: 'general',
          sort_order: 1,
          is_builtin: true,
          description: '',
        },
      ],
    } as any);
    vi.spyOn(personasApi, 'setActive').mockResolvedValue({ success: true, persona_id: 'uuid-halberd' });
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

    await waitFor(() => expect(personasApi.setActive).toHaveBeenCalledWith('uuid-halberd'));
    expect(personasApi.seedPreviews).toHaveBeenCalledWith('en');
  });

  it('keeps completion action centered without a footer finish button', async () => {
    const initialConfig = {
      ...DEFAULT_SYSTEM_CONFIG,
      preferences: {
        ...DEFAULT_SYSTEM_CONFIG.preferences,
        language: 'en' as const,
        user_mode: 'quick' as const,
        scenario: 'knowledge_partner',
      },
    };
    localStorageMock.getItem.mockImplementation((key: string) => {
      if (key === 'magi_onboarding_state') {
        return JSON.stringify({
          phase: 'guided',
          mode: 'quick',
          current: 4,
          scenario: 'knowledge_partner',
          values: initialConfig,
        });
      }
      return null;
    });

    render(<OnboardingFlow initialConfig={initialConfig} />);

    expect(await screen.findByRole('button', { name: 'actions.enterApp' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'actions.finish' })).not.toBeInTheDocument();
  });

  it('expands built-in tools and blocks continuing until required config is filled', async () => {
    const initialConfig = {
      ...DEFAULT_SYSTEM_CONFIG,
      preferences: {
        ...DEFAULT_SYSTEM_CONFIG.preferences,
        user_mode: 'expert' as const,
      },
    };
    localStorageMock.getItem.mockImplementation((key: string) => {
      if (key === 'magi_onboarding_state') {
        return JSON.stringify({
          phase: 'guided',
          mode: 'expert',
          current: 5,
          values: initialConfig,
        });
      }
      return null;
    });
    vi.spyOn(skillsApi, 'list').mockResolvedValue([]);

    render(<OnboardingFlow initialConfig={initialConfig} />);

    expect(await screen.findByText('tools.weather.apiKey')).toBeInTheDocument();
    expect(screen.getByText('tools.weather.apiUrl')).toBeInTheDocument();
    expect(screen.getByText('tools.validation.weatherApiKeyRequired')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'actions.next' })).toBeDisabled();
  });

  it('shows completion loading immediately and ignores duplicate finish clicks', async () => {
    const user = userEvent.setup();
    const initialConfig = {
      ...DEFAULT_SYSTEM_CONFIG,
      preferences: {
        ...DEFAULT_SYSTEM_CONFIG.preferences,
        language: 'en' as const,
        user_mode: 'quick' as const,
        scenario: 'knowledge_partner',
      },
    };
    localStorageMock.getItem.mockImplementation((key: string) => {
      if (key === 'magi_onboarding_state') {
        return JSON.stringify({
          phase: 'guided',
          mode: 'quick',
          current: 4,
          scenario: 'knowledge_partner',
          values: initialConfig,
        });
      }
      return null;
    });

    let resolveComplete: (value: any) => void = () => undefined;
    vi.spyOn(configApi, 'completeOnboarding').mockReturnValue(
      new Promise((resolve) => {
        resolveComplete = resolve;
      }) as any
    );
    vi.spyOn(personasApi, 'seed').mockResolvedValue({ success: true, data: { created_ids: [] } } as any);
    vi.spyOn(personasApi, 'seedPreviews').mockResolvedValue({ success: true, data: [] } as any);
    vi.spyOn(personasApi, 'list').mockResolvedValue({ success: true, data: [] } as any);
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

    await waitFor(() => expect(configApi.completeOnboarding).toHaveBeenCalledTimes(1));
    const loadingButton = screen.getByRole('button', { name: 'actions.saving' });
    expect(loadingButton).toBeDisabled();

    await user.click(loadingButton);
    expect(configApi.completeOnboarding).toHaveBeenCalledTimes(1);

    resolveComplete({ success: true, message: 'ok', data: initialConfig });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith('/ready'));
  });
});
