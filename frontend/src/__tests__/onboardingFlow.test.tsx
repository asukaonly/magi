import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

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

// Mock the streaming preview so persona chat does not hit the network.
vi.mock('@/api/modules/chatPreview', () => ({
  streamChatPreview: vi.fn(() =>
    (async function* () {
      yield 'hi';
    })(),
  ),
}));

// Mock the inner LLMProviderConfigurationSection so we have a simple
// provider-picker + api-key input that exercises LLMSetupStep's plumbing.
vi.mock('@/components/config-forms/LLMProviderConfigurationSection', () => ({
  LLMProviderConfigurationSection: ({
    value,
    activeProviderId,
    onActiveProviderChange,
    onProviderChange,
    onSetProvider,
    registry,
  }: any) => {
    const providerIds = registry?.providers?.map((p: any) => p.id) ?? [];
    return (
      <div>
        <label htmlFor="provider-select">provider</label>
        <select
          id="provider-select"
          value={activeProviderId ?? ''}
          onChange={(e) => {
            const pid = e.target.value;
            if (!pid) return;
            onSetProvider?.(pid, {
              enabled: true,
              provider_type: pid,
              display_name: pid,
              api_key: '',
              base_url: '',
              services: {
                chat: { enabled: true, api_key: '', base_url: '' },
                embedding: { enabled: false, api_key: '', base_url: '' },
                image_generation: { enabled: false, api_key: '', base_url: '' },
                tts: { enabled: false, api_key: '', base_url: '' },
              },
              api_format: 'openai',
              custom_models: [],
              custom_default_model: '',
              model_metadata_overrides: {},
            });
            onActiveProviderChange?.(pid);
          }}
        >
          <option value="">--</option>
          {providerIds.map((pid: string) => (
            <option key={pid} value={pid}>
              {pid}
            </option>
          ))}
        </select>
        <label htmlFor="api-key-input">api key</label>
        <input
          id="api-key-input"
          value={value.providers?.[activeProviderId ?? '']?.api_key ?? ''}
          onChange={(e) => {
            const pid = activeProviderId;
            if (!pid) return;
            onProviderChange?.(pid, (draft: any) => {
              draft.api_key = e.target.value;
              draft.enabled = e.target.value.length > 0;
            });
          }}
        />
      </div>
    );
  },
}));

const stubCatalog = () => ({
  providers: [
    {
      id: 'anthropic',
      provider_type: 'anthropic',
      source: 'builtin',
      display_name: 'Anthropic',
    },
    {
      id: 'openai',
      provider_type: 'openai',
      source: 'builtin',
      display_name: 'OpenAI',
    },
  ],
});

const stubTemplate = () => ({
  template: { enabled: true, display_name: 'Custom' },
  defaults: null,
});

const stubSeedPreviews = () => [
  {
    seed_slug: 'nova',
    name: 'Nova',
    description: 'Polished assistant',
    avatar: '/avatars/nova.png',
    group: 'general',
    order: 0,
  },
  {
    seed_slug: 'ember',
    name: 'Ember',
    description: 'Deep listener',
    avatar: '/avatars/ember.png',
    group: 'general',
    order: 1,
  },
];

describe('OnboardingFlow (linear 4-step)', () => {
  beforeEach(() => {
    vi.spyOn(configApi, 'resolveLLMProviderCatalog').mockResolvedValue(
      stubCatalog() as any,
    );
    vi.spyOn(configApi, 'getLLMCustomProviderTemplate').mockResolvedValue(
      stubTemplate() as any,
    );
    vi.spyOn(personasApi, 'seedPreviews').mockResolvedValue({
      success: true,
      data: stubSeedPreviews(),
    } as any);
    vi.spyOn(personasApi, 'seed').mockResolvedValue({
      success: true,
      data: { created_ids: [] },
    } as any);
    vi.spyOn(personasApi, 'list').mockResolvedValue({
      success: true,
      data: [
        {
          persona_id: 'uuid-nova',
          name: 'Nova',
          slug: 'nova',
          locale: 'en',
          avatar_path: '',
          group_name: 'general',
          sort_order: 0,
          is_builtin: true,
          description: '',
        },
        {
          persona_id: 'uuid-ember',
          name: 'Ember',
          slug: 'ember',
          locale: 'en',
          avatar_path: '',
          group_name: 'general',
          sort_order: 1,
          is_builtin: true,
          description: '',
        },
      ],
    } as any);
    vi.spyOn(personasApi, 'setActive').mockResolvedValue({
      success: true,
      persona_id: 'uuid-ember',
    } as any);
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
    } as any);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    localStorageMock.getItem.mockReturnValue(null);
    localStorageMock.setItem.mockClear();
    localStorageMock.removeItem.mockClear();
  });

  it('renders the welcome entrypoint with no mode cards', () => {
    localStorageMock.getItem.mockReturnValue(null);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    expect(screen.getByText('welcome.title')).toBeInTheDocument();
    expect(screen.getByText('welcome.subtitle')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /welcome\.getStarted/ })).toBeInTheDocument();
    // Mode cards no longer exist anywhere in the flow.
    expect(screen.queryByText(/welcome\.quickMode/)).not.toBeInTheDocument();
    expect(screen.queryByText(/welcome\.expertMode/)).not.toBeInTheDocument();
    // No quick/expert copy anywhere on Welcome.
    expect(screen.queryByText(/quick mode|快速模式|expert mode|专家模式/i)).toBeNull();
  });

  it('walks through welcome → LLM setup → persona preview → completion and persists seed_slug on save', async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    const completeOnboarding = vi
      .spyOn(configApi, 'completeOnboarding')
      .mockResolvedValue({ success: true, message: 'ok', data: DEFAULT_SYSTEM_CONFIG } as any);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    // Step 0: Welcome → Get Started
    await user.click(screen.getByRole('button', { name: /welcome\.getStarted/ }));

    // Step 1: LLM setup — wait for the registry-loaded provider picker
    const providerSelect = await screen.findByLabelText(/provider/i);
    await user.selectOptions(providerSelect, 'openai');
    const nextBtn = screen.getByRole('button', { name: 'actions.next' });
    // Until an API key is typed, the LLM step is invalid and Next stays disabled.
    expect(nextBtn).toBeDisabled();
    await user.type(screen.getByLabelText(/api key/i), 'sk-test');
    await waitFor(() => expect(nextBtn).toBeEnabled());
    await user.click(nextBtn);

    // Step 2: Persona preview — pick Ember and confirm
    await screen.findByRole('button', { name: /Ember/i });
    await user.click(screen.getByRole('button', { name: /Ember/i }));
    await user.click(
      screen.getByRole('button', { name: /^(personaPreview\.)?confirm$/i }),
    );

    // Step 3: Completion — click Enter App
    const enterApp = await screen.findByRole('button', { name: 'actions.enterApp' });
    await user.click(enterApp);

    await waitFor(() => expect(completeOnboarding).toHaveBeenCalledTimes(1));
    const payload = completeOnboarding.mock.calls[0][0] as any;
    expect(payload.preferences.onboarding_completed).toBe(true);
    expect(payload.llm.providers.openai.enabled).toBe(true);
    expect(payload.llm.providers.openai.api_key).toBe('sk-test');

    // No mode references anywhere across the rendered flow.
    expect(screen.queryByText(/quick mode|快速模式|expert mode|专家模式/i)).toBeNull();
  });

  it('surfaces the embedding-fallback row when an Anthropic-style provider is picked', async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(screen.getByRole('button', { name: /welcome\.getStarted/ }));

    const providerSelect = await screen.findByLabelText(/provider/i);
    await user.selectOptions(providerSelect, 'anthropic');

    await waitFor(() =>
      expect(screen.getByTestId('llm-setup-embedding-row')).toBeInTheDocument(),
    );
  });

  it('activates the chosen persona slug after onboarding completes', async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    vi.spyOn(configApi, 'completeOnboarding').mockResolvedValue({
      success: true,
      message: 'ok',
      data: DEFAULT_SYSTEM_CONFIG,
    } as any);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(screen.getByRole('button', { name: /welcome\.getStarted/ }));
    const providerSelect = await screen.findByLabelText(/provider/i);
    await user.selectOptions(providerSelect, 'openai');
    await user.type(screen.getByLabelText(/api key/i), 'sk-test');
    const nextBtn = screen.getByRole('button', { name: 'actions.next' });
    await waitFor(() => expect(nextBtn).toBeEnabled());
    await user.click(nextBtn);

    await screen.findByRole('button', { name: /Ember/i });
    await user.click(screen.getByRole('button', { name: /Ember/i }));
    await user.click(
      screen.getByRole('button', { name: /^(personaPreview\.)?confirm$/i }),
    );
    const enterApp = await screen.findByRole('button', { name: 'actions.enterApp' });
    await user.click(enterApp);

    await waitFor(() =>
      expect(personasApi.setActive).toHaveBeenCalledWith('uuid-ember'),
    );
  });
});
