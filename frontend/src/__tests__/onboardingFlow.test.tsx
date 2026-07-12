import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { localStorageMock, navigateMock, streamChatPreviewMock } = vi.hoisted(() => {
  const mock = {
    getItem: vi.fn((_key: string): string | null => null),
    setItem: vi.fn((_key: string, _value: string) => undefined),
    removeItem: vi.fn((_key: string) => undefined),
  };
  vi.stubGlobal('localStorage', mock);
  return {
    localStorageMock: mock,
    navigateMock: vi.fn(),
    streamChatPreviewMock: vi.fn(),
  };
});

import { apiClient } from '@/api/client';
import { configApi, DEFAULT_SYSTEM_CONFIG } from '@/api/modules/config';
import { personasApi } from '@/api/modules/personas';
import * as systemSuggestions from '@/api/modules/systemSuggestions';
import OnboardingFlow from '@/components/onboarding/OnboardingFlow';
import { usePluginInstallPanelStore } from '@/stores/pluginInstallPanel';

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
  useNavigate: () => navigateMock,
}));

// Mock the streaming preview so persona chat does not hit the network.
vi.mock('@/api/modules/chatPreview', () => ({
  streamChatPreview: (...args: unknown[]) => streamChatPreviewMock(...args),
}));

const stubChatModel = (id: string) => ({
  id,
  capabilities: {
    vision: false,
    image_output: false,
    tool_calling: true,
    reasoning: true,
  },
  limits: { context_window: 204800, max_output_tokens: 131072 },
  hidden: false,
  preferred: false,
  source: 'builtin',
  input_modalities: ['text'],
  output_modalities: ['text'],
});

const stubCatalog = () => ({
  providers: [
    {
      id: 'anthropic',
      provider_type: 'anthropic',
      source: 'builtin',
      display_name: 'Anthropic',
      default_model: 'claude-sonnet-4-5',
      default_classify_model: 'claude-haiku-4-5',
      default_base_url: 'https://api.anthropic.com/v1',
      api_format: 'anthropic',
      resolved_chat_models: [],
      resolved_embedding_models: [],
    },
    {
      id: 'openai',
      provider_type: 'openai',
      source: 'builtin',
      display_name: 'OpenAI',
      default_model: 'gpt-4o',
      default_classify_model: 'gpt-4o-mini',
      default_base_url: 'https://api.openai.com/v1',
      api_format: 'openai',
      resolved_chat_models: [],
      resolved_embedding_models: [{ id: 'text-embedding-3-small', dimensions: [1536] }],
    },
    {
      id: 'glm',
      provider_type: 'glm',
      source: 'builtin',
      display_name: 'Z.ai',
      default_model: 'glm-5.1',
      default_classify_model: 'glm-4.6',
      default_base_url: 'https://open.bigmodel.cn/api/paas/v4',
      api_format: 'openai',
      resolved_chat_models: [stubChatModel('glm-5.1'), stubChatModel('glm-4.6')],
      resolved_embedding_models: [{ id: 'embedding-3', dimensions: [1024] }],
      plans: [
        {
          id: 'codeplan',
          display_name: 'Z.ai CodePlan',
          default_model: 'glm-5.1',
          default_classify_model: 'glm-4.5-air',
          default_base_url: 'https://open.bigmodel.cn/api/coding/paas/v4',
          endpoints: [
            {
              id: 'china',
              label: 'China',
              base_url: 'https://open.bigmodel.cn/api/coding/paas/v4',
              api_format: 'openai',
            },
          ],
          embedding_models: [],
          image_generation_models: [],
          resolved_chat_models: [stubChatModel('glm-5.1'), stubChatModel('glm-4.5-air')],
          resolved_embedding_models: [],
          resolved_image_generation_models: [],
        },
      ],
    },
  ],
});

const stubCodePlanCatalog = (): ReturnType<typeof stubCatalog> => {
  const catalog = stubCatalog();
  const glm = catalog.providers.find((provider) => provider.id === 'glm');
  if (glm) {
    glm.resolved_chat_models = [stubChatModel('glm-5.1'), stubChatModel('glm-4.5-air')];
    glm.resolved_embedding_models = [];
  }
  return catalog;
};

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

describe('OnboardingFlow (linear 5-step)', () => {
  beforeEach(() => {
    streamChatPreviewMock.mockReset();
    streamChatPreviewMock.mockImplementation(() =>
      (async function* () {
        yield 'hi';
      })(),
    );
    vi.spyOn(configApi, 'resolveLLMProviderCatalog').mockResolvedValue(
      stubCatalog() as any,
    );
    vi.spyOn(configApi, 'getLLMCustomProviderTemplate').mockResolvedValue(
      stubTemplate() as any,
    );
    vi.spyOn(configApi, 'update').mockResolvedValue({
      success: true,
      message: 'ok',
      data: DEFAULT_SYSTEM_CONFIG,
    } as any);
    vi.spyOn(configApi, 'updateOnboardingDraft').mockResolvedValue({
      success: true,
      message: 'ok',
      data: DEFAULT_SYSTEM_CONFIG,
    } as any);
    vi.spyOn(configApi, 'getOnboardingStatus').mockResolvedValue({
      success: true,
      message: 'ok',
      data: { completed: false },
    } as any);
    vi.spyOn(configApi, 'testLLMProviderConnection').mockResolvedValue({
      model: 'gpt-4o',
      latency_ms: 42,
      preview: 'hello',
    });
    vi.spyOn(personasApi, 'seedPreviews').mockResolvedValue({
      success: true,
      data: stubSeedPreviews(),
    } as any);
    vi.spyOn(systemSuggestions, 'listInstallable').mockResolvedValue([
      {
        plugin_id: 'chrome-history',
        category: 'browser_history',
        installed: false,
        rationale: { zh: '', en: '' },
      },
    ]);
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
    navigateMock.mockReset();
    usePluginInstallPanelStore.getState().closePanel();
  });

  it('renders the welcome entrypoint with no mode cards', () => {
    localStorageMock.getItem.mockReturnValue(null);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    expect(screen.getByText('welcome.brand')).toBeInTheDocument();
    expect(screen.getByText('welcome.title')).toBeInTheDocument();
    expect(screen.queryByText('welcome.subtitleLine1')).not.toBeInTheDocument();
    expect(screen.queryByText('welcome.subtitleLine2')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /welcome\.getStarted/ })).toBeInTheDocument();
    // Mode cards no longer exist anywhere in the flow.
    expect(screen.queryByText(/welcome\.quickMode/)).not.toBeInTheDocument();
    expect(screen.queryByText(/welcome\.expertMode/)).not.toBeInTheDocument();
    // No quick/expert copy anywhere on Welcome.
    expect(screen.queryByText(/quick mode|快速模式|expert mode|专家模式/i)).toBeNull();
  });

  it('returns legacy recovered progress to model setup before later steps', async () => {
    localStorageMock.getItem.mockImplementation((key: string) => {
      if (key !== 'magi_onboarding_state') {
        return null;
      }
      return JSON.stringify({
        current: 3,
        values: DEFAULT_SYSTEM_CONFIG,
        seedSlug: 'ember',
      });
    });

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    expect(await screen.findByTestId('llm-setup-provider-openai')).toBeInTheDocument();
    expect(screen.queryByText('firstContext.title')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Ember/i })).not.toBeInTheDocument();
    expect(configApi.testLLMProviderConnection).not.toHaveBeenCalled();
  });

  it('walks through welcome → LLM setup → persona preview → first context → completion and persists seed_slug on save', async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    const completeOnboarding = vi
      .spyOn(configApi, 'completeOnboarding')
      .mockResolvedValue({ success: true, message: 'ok', data: DEFAULT_SYSTEM_CONFIG } as any);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    // Step 0: Welcome → Get Started
    await user.click(screen.getByRole('button', { name: /welcome\.getStarted/ }));

    // Step 1: LLM setup — choose a flat provider card and paste the key.
    await user.click(await screen.findByTestId('llm-setup-provider-openai'));
    const nextBtn = screen.getByRole('button', { name: 'actions.next' });
    // Until an API key is typed, the LLM step is invalid and Next stays disabled.
    expect(nextBtn).toBeDisabled();
    await user.type(screen.getByTestId('llm-setup-api-key'), 'sk-test');
    await waitFor(() => expect(nextBtn).toBeEnabled());
    await user.click(nextBtn);

    await waitFor(() => expect(configApi.testLLMProviderConnection).toHaveBeenCalledTimes(1));
    expect(configApi.testLLMProviderConnection).toHaveBeenCalledWith(
      expect.objectContaining({
        provider_id: 'openai',
        model: 'gpt-4o',
        provider: expect.objectContaining({
          api_key: 'sk-test',
          services: expect.objectContaining({
            chat: expect.objectContaining({ api_key: 'sk-test' }),
          }),
        }),
      }),
    );

    // Step 2: Persona preview — pick Ember (the active rail item is the
    // selection) and advance with the standard footer Next button.
    await screen.findByRole('button', { name: /Ember/i });
    await user.click(screen.getByRole('button', { name: /Ember/i }));
    await user.click(screen.getByRole('button', { name: 'actions.next' }));

    await waitFor(() => expect(configApi.updateOnboardingDraft).toHaveBeenCalledTimes(1));
    const earlyPayload = vi.mocked(configApi.updateOnboardingDraft).mock.calls[0][0] as any;
    expect(Object.keys(earlyPayload).sort()).toEqual(['language', 'llm']);
    expect(earlyPayload.language).toBe('zh');
    expect(earlyPayload.llm.providers.openai.enabled).toBe(true);
    expect(configApi.update).not.toHaveBeenCalled();

    // Step 3: First context — this is a real step now, not a footer on completion.
    expect(await screen.findByText('firstContext.title')).toBeInTheDocument();
    expect(screen.getByTestId('empty-state-connect-chrome-history')).toBeInTheDocument();
    expect(screen.getByTestId('empty-state-connect-calendar')).toBeInTheDocument();
    expect(screen.queryByText('firstContext.kicker')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'actions.skipContext' }));

    // Step 4: Completion — click Enter App. No source cards are rendered here.
    const enterApp = await screen.findByRole('button', { name: 'actions.enterApp' });
    expect(screen.queryByTestId('empty-state-connect-chrome-history')).not.toBeInTheDocument();
    await user.click(enterApp);

    await waitFor(() => expect(completeOnboarding).toHaveBeenCalledTimes(1));
    const payload = completeOnboarding.mock.calls[0][0] as any;
    expect(Object.keys(payload).sort()).toEqual(['language', 'llm']);
    expect(payload.language).toBe('zh');
    expect(payload.llm.providers.openai.enabled).toBe(true);
    expect(payload.llm.providers.openai.api_key).toBe('sk-test');
    expect(configApi.testLLMProviderConnection).toHaveBeenCalledTimes(1);

    // No mode references anywhere across the rendered flow.
    expect(screen.queryByText(/quick mode|快速模式|expert mode|专家模式/i)).toBeNull();
  });

  it('preserves the chosen persona after moving forward and back', async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(screen.getByRole('button', { name: /welcome\.getStarted/ }));
    await user.click(await screen.findByTestId('llm-setup-provider-openai'));
    await user.type(screen.getByTestId('llm-setup-api-key'), 'sk-test');
    await user.click(screen.getByRole('button', { name: 'actions.next' }));

    const ember = await screen.findByRole('button', { name: /Ember/i });
    await user.click(ember);
    expect(ember).toHaveAttribute('aria-pressed', 'true');
    await user.click(screen.getByRole('button', { name: 'actions.next' }));

    await screen.findByText('firstContext.title');
    await user.click(screen.getByRole('button', { name: 'actions.previous' }));

    expect(await screen.findByRole('button', { name: /Ember/i })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(screen.getByRole('button', { name: /Nova/i })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
  });

  it('uses the welcome language for persona previews and final persona setup', async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    const completeOnboarding = vi
      .spyOn(configApi, 'completeOnboarding')
      .mockResolvedValue({ success: true, message: 'ok', data: DEFAULT_SYSTEM_CONFIG } as any);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await waitFor(() => expect(personasApi.seedPreviews).toHaveBeenCalledWith('zh'));
    await user.click(screen.getByRole('button', { name: 'EN' }));
    await waitFor(() => expect(personasApi.seedPreviews).toHaveBeenCalledWith('en'));
    await user.click(screen.getByRole('button', { name: /welcome\.getStarted/ }));

    await user.click(await screen.findByTestId('llm-setup-provider-openai'));
    await user.type(screen.getByTestId('llm-setup-api-key'), 'sk-test');
    await user.click(screen.getByRole('button', { name: 'actions.next' }));

    await user.click(await screen.findByRole('button', { name: /Ember/i }));
    await user.type(screen.getByPlaceholderText(/composerPlaceholder/i), 'hello');
    await user.click(screen.getByRole('button', { name: /^(personaPreview\.)?send$/i }));
    await waitFor(() =>
      expect(streamChatPreviewMock).toHaveBeenCalledWith(
        expect.objectContaining({ seed_slug: 'ember', locale: 'en' }),
      ),
    );

    await user.click(screen.getByRole('button', { name: 'actions.next' }));
    await user.click(await screen.findByRole('button', { name: 'actions.skipContext' }));
    await user.click(await screen.findByRole('button', { name: 'actions.enterApp' }));

    await waitFor(() => expect(completeOnboarding).toHaveBeenCalledTimes(1));
    expect(completeOnboarding).toHaveBeenCalledWith(
      expect.objectContaining({ language: 'en' }),
    );
    expect(personasApi.seed).toHaveBeenCalledWith('en');
  });

  it('automatically validates a keyless custom OpenAI-compatible endpoint', async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(screen.getByRole('button', { name: /welcome\.getStarted/ }));
    await user.click(await screen.findByTestId('llm-setup-provider-custom'));
    await user.type(screen.getByTestId('llm-setup-base-url'), 'http://127.0.0.1:11434/v1');
    await user.type(screen.getByTestId('llm-setup-custom-model'), 'local-model');
    const nextButton = screen.getByRole('button', { name: 'actions.next' });
    await waitFor(() => expect(nextButton).toBeEnabled());
    await user.click(nextButton);

    await screen.findByRole('button', { name: /Ember/i });
    expect(configApi.testLLMProviderConnection).toHaveBeenCalledTimes(1);
    expect(configApi.testLLMProviderConnection).toHaveBeenCalledWith(
      expect.objectContaining({
        model: 'local-model',
        provider: expect.objectContaining({
          provider_type: 'custom',
          api_key: '',
          base_url: 'http://127.0.0.1:11434/v1',
        }),
      }),
    );
  });

  it('reuses a successful manual model test after returning from persona', async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(screen.getByRole('button', { name: /welcome\.getStarted/ }));
    await user.click(await screen.findByTestId('llm-setup-provider-openai'));
    await user.type(screen.getByTestId('llm-setup-api-key'), 'sk-test');
    await user.click(screen.getByRole('button', { name: 'llm.actions.testConnection' }));
    expect(await screen.findByText('llm.providerConfiguration.testSuccess')).toBeInTheDocument();
    expect(configApi.testLLMProviderConnection).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('button', { name: 'actions.next' }));
    await screen.findByRole('button', { name: /Ember/i });
    await user.click(screen.getByRole('button', { name: 'actions.previous' }));

    expect(await screen.findByText('llm.providerConfiguration.testSuccess')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'actions.next' }));
    await screen.findByRole('button', { name: /Ember/i });
    expect(configApi.testLLMProviderConnection).toHaveBeenCalledTimes(1);
  });

  it('invalidates a successful test as soon as the provider plan changes', async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(screen.getByRole('button', { name: /welcome\.getStarted/ }));
    await user.click(await screen.findByTestId('llm-setup-provider-glm'));
    await user.type(screen.getByTestId('llm-setup-api-key'), 'glm-key');
    await user.click(screen.getByRole('button', { name: 'llm.actions.testConnection' }));
    expect(await screen.findByText('llm.providerConfiguration.testSuccess')).toBeInTheDocument();
    expect(configApi.testLLMProviderConnection).toHaveBeenCalledTimes(1);

    let resolvePlanCatalog: ((value: ReturnType<typeof stubCatalog>) => void) | undefined;
    const pendingPlanCatalog = new Promise<ReturnType<typeof stubCatalog>>((resolve) => {
      resolvePlanCatalog = resolve;
    });
    vi.mocked(configApi.resolveLLMProviderCatalog).mockReturnValueOnce(pendingPlanCatalog as any);

    await user.click(screen.getByText('llm.providerPlans.default'));
    await user.click(await screen.findByText('Z.ai CodePlan'));
    expect(screen.getByText('llm.providerConfiguration.testSuccess')).toBeInTheDocument();
    const nextButton = screen.getByRole('button', { name: 'actions.next' });
    const previousButton = screen.getByRole('button', { name: 'actions.previous' });
    expect(nextButton).toBeDisabled();
    expect(previousButton).toBeDisabled();
    expect(screen.getByTestId('llm-setup-api-key')).toBeDisabled();
    resolvePlanCatalog?.(stubCodePlanCatalog());
    await waitFor(() => expect(nextButton).toBeEnabled());
    expect(previousButton).toBeEnabled();
    expect(screen.getByTestId('llm-setup-api-key')).toBeEnabled();
    expect(screen.queryByText('llm.providerConfiguration.testSuccess')).not.toBeInTheDocument();
    await user.click(nextButton);

    await screen.findByRole('button', { name: /Ember/i });
    expect(configApi.testLLMProviderConnection).toHaveBeenCalledTimes(2);
    expect(configApi.testLLMProviderConnection).toHaveBeenLastCalledWith(
      expect.objectContaining({
        model: 'glm-5.1',
        provider: expect.objectContaining({ provider_plan: 'codeplan' }),
      }),
    );
    await user.click(screen.getByRole('button', { name: /Ember/i }));
    await user.click(screen.getByRole('button', { name: 'actions.next' }));
    await waitFor(() => expect(configApi.updateOnboardingDraft).toHaveBeenCalledTimes(1));
    const draftPayload = vi.mocked(configApi.updateOnboardingDraft).mock.calls[0][0] as any;
    expect(draftPayload.llm.selections.context_decider.model).toBe('glm-4.5-air');
    expect(draftPayload.llm.selections.context_decider.limits.context_window).toBe(204800);
  });

  it('keeps the previous provider settings when plan resolution fails', async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(screen.getByRole('button', { name: /welcome\.getStarted/ }));
    await user.click(await screen.findByTestId('llm-setup-provider-glm'));
    await user.type(screen.getByTestId('llm-setup-api-key'), 'glm-key');
    await user.click(screen.getByRole('button', { name: 'llm.actions.testConnection' }));
    expect(await screen.findByText('llm.providerConfiguration.testSuccess')).toBeInTheDocument();
    expect(configApi.testLLMProviderConnection).toHaveBeenCalledTimes(1);

    let rejectPlanCatalog: ((reason?: unknown) => void) | undefined;
    const pendingPlanCatalog = new Promise<ReturnType<typeof stubCatalog>>((_, reject) => {
      rejectPlanCatalog = reject;
    });
    vi.mocked(configApi.resolveLLMProviderCatalog).mockReturnValueOnce(pendingPlanCatalog as any);

    await user.click(screen.getByText('llm.providerPlans.default'));
    await user.click(await screen.findByText('Z.ai CodePlan'));
    const nextButton = screen.getByRole('button', { name: 'actions.next' });
    const previousButton = screen.getByRole('button', { name: 'actions.previous' });
    expect(nextButton).toBeDisabled();
    expect(previousButton).toBeDisabled();

    rejectPlanCatalog?.(new Error('catalog unavailable'));
    expect(await screen.findByText('llmSetup.planLoadFailed')).toBeInTheDocument();
    await waitFor(() => expect(nextButton).toBeEnabled());
    expect(previousButton).toBeEnabled();
    expect(screen.getByText('llm.providerConfiguration.testSuccess')).toBeInTheDocument();
    await user.click(nextButton);

    await screen.findByRole('button', { name: /Ember/i });
    expect(configApi.testLLMProviderConnection).toHaveBeenCalledTimes(1);
    expect(configApi.testLLMProviderConnection).toHaveBeenLastCalledWith(
      expect.objectContaining({
        model: 'glm-5.1',
        provider: expect.objectContaining({ provider_plan: null }),
      }),
    );
  });

  it('tests again after the API key changes', async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(screen.getByRole('button', { name: /welcome\.getStarted/ }));
    await user.click(await screen.findByTestId('llm-setup-provider-openai'));
    const keyInput = screen.getByTestId('llm-setup-api-key');
    await user.type(keyInput, 'sk-first');
    await user.click(screen.getByRole('button', { name: 'llm.actions.testConnection' }));
    expect(await screen.findByText('llm.providerConfiguration.testSuccess')).toBeInTheDocument();

    await user.clear(keyInput);
    await user.type(keyInput, 'sk-second');
    await waitFor(() =>
      expect(screen.queryByText('llm.providerConfiguration.testSuccess')).not.toBeInTheDocument(),
    );
    await user.click(screen.getByRole('button', { name: 'actions.next' }));

    await screen.findByRole('button', { name: /Ember/i });
    expect(configApi.testLLMProviderConnection).toHaveBeenCalledTimes(2);
  });

  it('tests again after the primary model changes', async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(screen.getByRole('button', { name: /welcome\.getStarted/ }));
    await user.click(await screen.findByTestId('llm-setup-provider-openai'));
    await user.type(screen.getByTestId('llm-setup-api-key'), 'sk-test');
    await user.click(screen.getByRole('button', { name: 'llm.actions.testConnection' }));
    expect(await screen.findByText('llm.providerConfiguration.testSuccess')).toBeInTheDocument();

    await user.click(screen.getByTestId('llm-setup-advanced-toggle'));
    const modelInput = screen.getByTestId('llm-setup-core-model');
    await user.clear(modelInput);
    await user.type(modelInput, 'gpt-4.1');
    await waitFor(() =>
      expect(screen.queryByText('llm.providerConfiguration.testSuccess')).not.toBeInTheDocument(),
    );
    await user.click(screen.getByRole('button', { name: 'actions.next' }));

    await screen.findByRole('button', { name: /Ember/i });
    expect(configApi.testLLMProviderConnection).toHaveBeenCalledTimes(2);
    expect(configApi.testLLMProviderConnection).toHaveBeenLastCalledWith(
      expect.objectContaining({ model: 'gpt-4.1' }),
    );
  });

  it('reuses success after a fast-model change but retests after the endpoint changes', async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(screen.getByRole('button', { name: /welcome\.getStarted/ }));
    await user.click(await screen.findByTestId('llm-setup-provider-openai'));
    await user.type(screen.getByTestId('llm-setup-api-key'), 'sk-test');
    await user.click(screen.getByRole('button', { name: 'llm.actions.testConnection' }));
    expect(await screen.findByText('llm.providerConfiguration.testSuccess')).toBeInTheDocument();

    await user.click(screen.getByTestId('llm-setup-advanced-toggle'));
    const fastModelInput = screen.getByTestId('llm-setup-fast-model');
    await user.clear(fastModelInput);
    await user.type(fastModelInput, 'gpt-4o-mini-new');
    expect(screen.getByText('llm.providerConfiguration.testSuccess')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'actions.next' }));

    await screen.findByRole('button', { name: /Ember/i });
    expect(configApi.testLLMProviderConnection).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole('button', { name: 'actions.previous' }));

    await user.click(await screen.findByTestId('llm-setup-advanced-toggle'));
    const baseUrlInput = await screen.findByTestId('llm-setup-base-url');
    await user.clear(baseUrlInput);
    await user.type(baseUrlInput, 'https://relay.example.com/v1');
    await waitFor(() =>
      expect(screen.queryByText('llm.providerConfiguration.testSuccess')).not.toBeInTheDocument(),
    );
    await user.click(screen.getByRole('button', { name: 'actions.next' }));

    await screen.findByRole('button', { name: /Ember/i });
    expect(configApi.testLLMProviderConnection).toHaveBeenCalledTimes(2);
    expect(configApi.testLLMProviderConnection).toHaveBeenLastCalledWith(
      expect.objectContaining({
        provider: expect.objectContaining({ base_url: 'https://relay.example.com/v1' }),
      }),
    );
  });

  it('stays on model setup when automatic validation fails', async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    vi.mocked(configApi.testLLMProviderConnection).mockRejectedValueOnce(
      new Error('invalid credentials'),
    );

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(screen.getByRole('button', { name: /welcome\.getStarted/ }));
    await user.click(await screen.findByTestId('llm-setup-provider-openai'));
    await user.type(screen.getByTestId('llm-setup-api-key'), 'bad-key');
    await user.click(screen.getByRole('button', { name: 'actions.next' }));

    expect(await screen.findByText('llm.providerConfiguration.testFailed')).toBeInTheDocument();
    expect(screen.getByTestId('llm-setup-api-key')).toHaveValue('bad-key');
    expect(screen.queryByRole('button', { name: /Ember/i })).not.toBeInTheDocument();
  });

  it('enters the app when completion was saved but the response was lost', async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    vi.spyOn(configApi, 'completeOnboarding').mockRejectedValue(new Error('response lost'));
    vi.mocked(configApi.getOnboardingStatus).mockResolvedValue({
      success: true,
      message: 'ok',
      data: { completed: true },
    } as any);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(screen.getByRole('button', { name: /welcome\.getStarted/ }));
    await user.click(await screen.findByTestId('llm-setup-provider-openai'));
    await user.type(screen.getByTestId('llm-setup-api-key'), 'sk-test');
    const nextBtn = screen.getByRole('button', { name: 'actions.next' });
    await waitFor(() => expect(nextBtn).toBeEnabled());
    await user.click(nextBtn);

    await screen.findByRole('button', { name: /Ember/i });
    await user.click(screen.getByRole('button', { name: /Ember/i }));
    await user.click(screen.getByRole('button', { name: 'actions.next' }));
    await screen.findByText('firstContext.title');
    await user.click(screen.getByRole('button', { name: 'actions.skipContext' }));
    await user.click(await screen.findByRole('button', { name: 'actions.enterApp' }));

    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith('/'));
    expect(localStorageMock.removeItem).toHaveBeenCalledWith('magi_onboarding_state');
  });

  it('keeps the first-context step open after a selected source finishes connecting', async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    const openPanel = vi.spyOn(usePluginInstallPanelStore.getState(), 'openPanel');

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(screen.getByRole('button', { name: /welcome\.getStarted/ }));
    await user.click(await screen.findByTestId('llm-setup-provider-openai'));
    await user.type(screen.getByTestId('llm-setup-api-key'), 'sk-test');
    const nextBtn = screen.getByRole('button', { name: 'actions.next' });
    await waitFor(() => expect(nextBtn).toBeEnabled());
    await user.click(nextBtn);

    await screen.findByRole('button', { name: /Ember/i });
    await user.click(screen.getByRole('button', { name: /Ember/i }));
    await user.click(screen.getByRole('button', { name: 'actions.next' }));

    await screen.findByText('firstContext.title');
    await user.click(screen.getByTestId('empty-state-connect-chrome-history'));

    expect(openPanel).toHaveBeenCalledWith('chrome-history', {
      install: true,
      context: 'first_context',
      onDone: expect.any(Function),
    });
    expect(screen.getByText('firstContext.title')).toBeInTheDocument();

    const onDone = openPanel.mock.calls[0]?.[1]?.onDone;
    onDone?.();

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'actions.finishContext' })).toBeInTheDocument(),
    );
    expect(screen.getByText('firstContext.connectedCount')).toBeInTheDocument();
    expect(screen.queryByTestId('empty-state-connect-chrome-history')).not.toBeInTheDocument();
    expect(screen.getByTestId('empty-state-connect-calendar')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'actions.enterApp' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'actions.finishContext' }));
    expect(await screen.findByRole('button', { name: 'actions.enterApp' })).toBeInTheDocument();
  });

  it('surfaces the embedding-fallback row when an Anthropic-style provider is picked', async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(screen.getByRole('button', { name: /welcome\.getStarted/ }));

    await user.click(await screen.findByTestId('llm-setup-provider-anthropic'));

    await waitFor(() =>
      expect(screen.getByTestId('llm-setup-embedding-row')).toBeInTheDocument(),
    );
  });

  it('repeats the missing-vector warning on the first-context step without blocking skip', async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(screen.getByRole('button', { name: /welcome\.getStarted/ }));
    await user.click(await screen.findByTestId('llm-setup-provider-anthropic'));
    await user.type(screen.getByTestId('llm-setup-api-key'), 'sk-test');
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'actions.next' })).toBeEnabled(),
    );
    await user.click(screen.getByRole('button', { name: 'actions.next' }));

    await screen.findByRole('button', { name: /Ember/i });
    await user.click(screen.getByRole('button', { name: /Ember/i }));
    await user.click(screen.getByRole('button', { name: 'actions.next' }));

    const warning = await screen.findByTestId('first-context-memory-warning');
    const title = screen.getByText('firstContext.title');
    expect(warning.compareDocumentPosition(title) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'actions.skipContext' }));
    expect(await screen.findByRole('button', { name: 'actions.enterApp' })).toBeInTheDocument();
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
    await user.click(await screen.findByTestId('llm-setup-provider-openai'));
    await user.type(screen.getByTestId('llm-setup-api-key'), 'sk-test');
    const nextBtn = screen.getByRole('button', { name: 'actions.next' });
    await waitFor(() => expect(nextBtn).toBeEnabled());
    await user.click(nextBtn);

    await screen.findByRole('button', { name: /Ember/i });
    await user.click(screen.getByRole('button', { name: /Ember/i }));
    await user.click(screen.getByRole('button', { name: 'actions.next' }));
    await user.click(await screen.findByRole('button', { name: 'actions.skipContext' }));
    const enterApp = await screen.findByRole('button', { name: 'actions.enterApp' });
    await user.click(enterApp);

    await waitFor(() =>
      expect(personasApi.setActive).toHaveBeenCalledWith('uuid-ember'),
    );
  });

  it('creates and activates a custom generated persona on completion', async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    vi.spyOn(configApi, 'completeOnboarding').mockResolvedValue({
      success: true,
      message: 'ok',
      data: DEFAULT_SYSTEM_CONFIG,
    } as any);
    const generated = {
      name: 'Sage',
      avatar: '',
      description: 'wise mentor',
      appearance_prompt: '',
      identity_core: {
        identity_statement: 'a patient mentor',
        values_loved: [],
        values_rejected: [],
        attention_biases: [],
      },
      idiolect: {
        sentence_style: 'measured and kind',
        vocab_available: [],
        vocab_avoided: [],
        structural_quirks: [],
      },
      registers: {},
      quiet_hours: [],
      signature_triggers: [],
      persona_layers: [],
      dynamic_state_rules: {},
      milestone_conditions: {},
      interim_lines: {},
      bootstrap: null,
    };
    vi.spyOn(personasApi, 'generateWithProgress').mockResolvedValue({
      success: true,
      message: 'ok',
      data: generated,
      stages: [],
    } as any);
    const createSpy = vi.spyOn(personasApi, 'create').mockResolvedValue({
      success: true,
      data: { persona_id: 'uuid-custom', name: 'Sage', slug: 'custom-1' },
    } as any);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(screen.getByRole('button', { name: /welcome\.getStarted/ }));
    await user.click(await screen.findByTestId('llm-setup-provider-openai'));
    await user.type(screen.getByTestId('llm-setup-api-key'), 'sk-test');
    const nextBtn = screen.getByRole('button', { name: 'actions.next' });
    await waitFor(() => expect(nextBtn).toBeEnabled());
    await user.click(nextBtn);

    // Persona step: generate a custom persona, which auto-selects it.
    await user.click(await screen.findByTestId('persona-create-custom'));
    await user.type(screen.getByTestId('persona-custom-description'), 'a wise mentor');
    await user.click(screen.getByTestId('persona-custom-generate'));
    // Back in chat mode with the custom persona selected — advance.
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'actions.next' })).toBeEnabled(),
    );
    await user.click(screen.getByRole('button', { name: 'actions.next' }));
    await user.click(await screen.findByRole('button', { name: 'actions.skipContext' }));

    const enterApp = await screen.findByRole('button', { name: 'actions.enterApp' });
    await user.click(enterApp);

    await waitFor(() => expect(createSpy).toHaveBeenCalled());
    const createArg = createSpy.mock.calls[0][0] as { config_json: string };
    expect(JSON.parse(createArg.config_json).name).toBe('Sage');
    await waitFor(() =>
      expect(personasApi.setActive).toHaveBeenCalledWith('uuid-custom'),
    );
  });

  it('disables the footer Next button while a custom persona is generating', async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    let resolveGen: (value: any) => void = () => {};
    vi.spyOn(personasApi, 'generateWithProgress').mockImplementation(
      () => new Promise((resolve) => { resolveGen = resolve; }),
    );

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(screen.getByRole('button', { name: /welcome\.getStarted/ }));
    await user.click(await screen.findByTestId('llm-setup-provider-openai'));
    await user.type(screen.getByTestId('llm-setup-api-key'), 'sk-test');
    const nextBtn = screen.getByRole('button', { name: 'actions.next' });
    await waitFor(() => expect(nextBtn).toBeEnabled());
    await user.click(nextBtn);

    // Start a generation on the persona step.
    await user.click(await screen.findByTestId('persona-create-custom'));
    await user.type(screen.getByTestId('persona-custom-description'), 'a wise mentor');
    await user.click(screen.getByTestId('persona-custom-generate'));

    // Footer Next is disabled while the generation is in flight...
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'actions.next' })).toBeDisabled(),
    );

    // ...and re-enabled once it resolves.
    resolveGen({
      success: true,
      message: 'ok',
      data: {
        name: 'Sage',
        avatar: '',
        description: 'wise',
        appearance_prompt: '',
        identity_core: { identity_statement: 'patient', values_loved: [], values_rejected: [], attention_biases: [] },
        idiolect: { sentence_style: 'calm', vocab_available: [], vocab_avoided: [], structural_quirks: [] },
        registers: {},
        quiet_hours: [],
        signature_triggers: [],
        persona_layers: [],
        dynamic_state_rules: {},
        milestone_conditions: {},
        interim_lines: {},
        bootstrap: null,
      },
      stages: [],
    });
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'actions.next' })).toBeEnabled(),
    );
  });
});
