import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import { configApi, type LLMConfig } from '../api/modules/config';
import { SimpleForm as Form } from '../components/onboarding/simple-form';
import LLMForm from '../components/config-forms/LLMForm';
import MemoryForm from '../components/config-forms/MemoryForm';

vi.mock('../api/modules/config', async () => {
  const actual = await vi.importActual<typeof import('../api/modules/config')>('../api/modules/config');
  const providerRegistry: any = {
    providers: [
      {
        id: 'openai',
        display_name: 'OpenAI',
        description: 'General purpose',
        icon: 'openai',
        default_model: 'gpt-5.2',
        default_classify_model: 'gpt-4.1-mini',
        default_base_url: 'https://api.openai.com/v1',
        chat_models: [
          {
            id: 'gpt-5.2',
            label: 'GPT-5.2',
            capabilities: {
              vision: true,
              image_output: false,
              tool_calling: true,
              reasoning: true,
              embedding: false,
            },
            limits: {
              context_window: 400000,
              max_output_tokens: 128000,
            },
            provider_options_example: {},
          },
          {
            id: 'gpt-4.1-mini',
            label: 'GPT-4.1 Mini',
            capabilities: {
              vision: true,
              image_output: false,
              tool_calling: true,
              reasoning: true,
              embedding: false,
            },
            limits: {
              context_window: 128000,
              max_output_tokens: 32000,
            },
            provider_options_example: {},
          },
        ],
        embedding_models: [
          {
            id: 'text-embedding-3-small',
            label: 'Text Embedding 3 Small',
            dimensions: [1536, 512],
          },
        ],
        fields: {
          api_key: { visible: true, required: true },
          base_url: { visible: true, required: false },
        },
      },
      {
        id: 'anthropic',
        display_name: 'Anthropic',
        description: 'Reasoning',
        icon: 'anthropic',
        default_model: 'claude-sonnet-4-6',
        default_base_url: 'https://api.anthropic.com/v1',
        chat_models: [
          {
            id: 'claude-sonnet-4-6',
            label: 'Claude Sonnet 4.6',
            capabilities: {
              vision: true,
              image_output: false,
              tool_calling: true,
              reasoning: true,
              embedding: false,
            },
            limits: {
              context_window: 200000,
              max_output_tokens: 64000,
            },
            provider_options_example: {},
          },
        ],
        fields: {
          api_key: { visible: true, required: true },
          base_url: { visible: true, required: false },
        },
      },
      {
        id: 'glm',
        display_name: 'Z.ai',
        description: 'Fast',
        icon: 'zai',
        default_model: 'glm-5',
        default_classify_model: 'glm-5',
        default_base_url: 'https://open.bigmodel.cn/api/paas/v4',
        chat_models: [
          {
            id: 'glm-5',
            label: 'GLM-5',
            capabilities: {
              vision: false,
              image_output: false,
              tool_calling: true,
              reasoning: true,
              embedding: false,
            },
            limits: {
              context_window: 128000,
              max_output_tokens: 32000,
            },
            provider_options_example: {
              thinking: { type: 'disabled' },
            },
          },
        ],
        embedding_models: [
          {
            id: 'embedding-3',
            label: 'Embedding-3',
            dimensions: [1024],
          },
        ],
        fields: {
          api_key: { visible: true, required: true },
          base_url: { visible: true, required: false },
        },
      },
      {
        id: 'gemini',
        display_name: 'Google Gemini',
        description: 'Multimodal models from Google',
        icon: 'gemini',
        default_model: 'gemini-2.5-flash',
        default_base_url: 'https://generativelanguage.googleapis.com/v1beta/openai',
        chat_models: [
          {
            id: 'gemini-2.5-flash',
            label: 'Gemini 2.5 Flash',
            capabilities: {
              vision: true,
              image_output: false,
              tool_calling: true,
              reasoning: true,
              embedding: false,
            },
            limits: {
              context_window: 1048576,
              max_output_tokens: 65536,
            },
            provider_options_example: {},
          },
        ],
        fields: {
          api_key: { visible: true, required: true },
          base_url: { visible: true, required: false },
        },
      },
      {
        id: 'deepseek',
        display_name: 'DeepSeek',
        description: 'Reasoning and coding models',
        icon: 'deepseek',
        default_model: 'deepseek-chat',
        default_base_url: 'https://api.deepseek.com',
        chat_models: [
          {
            id: 'deepseek-chat',
            label: 'DeepSeek Chat',
            capabilities: {
              vision: false,
              image_output: false,
              tool_calling: true,
              reasoning: true,
              embedding: false,
            },
            limits: {
              context_window: 128000,
              max_output_tokens: 8192,
            },
            provider_options_example: {},
          },
        ],
        fields: {
          api_key: { visible: true, required: true },
          base_url: { visible: true, required: false },
        },
      },
      {
        id: 'kimi',
        display_name: 'Kimi',
        description: 'Long context models from Moonshot AI',
        icon: 'kimi',
        default_model: 'moonshot-v1-32k',
        default_base_url: 'https://api.moonshot.cn/v1',
        chat_models: [
          {
            id: 'moonshot-v1-32k',
            label: 'Moonshot V1 32K',
            capabilities: {
              vision: false,
              image_output: false,
              tool_calling: true,
              reasoning: true,
              embedding: false,
            },
            limits: {
              context_window: 32768,
              max_output_tokens: 8192,
            },
            provider_options_example: {},
          },
        ],
        fields: {
          api_key: { visible: true, required: true },
          base_url: { visible: true, required: false },
        },
      },
      {
        id: 'minimax',
        display_name: 'MiniMax',
        description: 'General multimodal models from MiniMax',
        icon: 'minimax',
        default_model: 'MiniMax-M2.5',
        default_base_url: 'https://api.minimaxi.com/v1',
        chat_models: [
          {
            id: 'MiniMax-M2.5',
            label: 'MiniMax M2.5',
            capabilities: {
              vision: true,
              image_output: false,
              tool_calling: true,
              reasoning: true,
              embedding: false,
            },
            limits: {
              context_window: 1000192,
              max_output_tokens: 8192,
            },
            provider_options_example: {},
          },
        ],
        fields: {
          api_key: { visible: true, required: true },
          base_url: { visible: true, required: false },
        },
      },
    ],
    custom_provider: {
      enabled: true,
      display_name: 'Custom Provider',
      fields: {
        custom_name: { visible: true, required: true },
        api_format: { visible: true, required: true, options: ['openai', 'anthropic'] },
        model: { visible: true, required: true },
        api_key: { visible: true, required: true },
        base_url: { visible: true, required: false },
      },
      capabilities: {
        vision: false,
        image_output: false,
        tool_calling: true,
        reasoning: true,
        embedding: false,
      },
      limits: {
        context_window: null,
        max_output_tokens: null,
      },
      provider_options_example: {},
    },
  };

  const defaultCustomProvider = {
    enabled: true,
    provider_type: 'custom' as const,
    display_name: '',
    api_key: '',
    base_url: '',
    api_format: 'openai' as const,
    custom_models: [],
    custom_default_model: '',
    model_metadata_overrides: {},
  };

  const defaultChatModalities = (capabilities: Record<string, boolean>) => ({
    input: capabilities.vision ? ['text', 'image'] : ['text'],
    output: capabilities.image_output ? ['text', 'image'] : ['text'],
  });

  const defaultEmbeddingModalities = (capabilities: Record<string, boolean>) => ({
    input: capabilities.vision ? ['text', 'image'] : ['text'],
    output: capabilities.image_output ? ['embedding', 'image'] : ['embedding'],
  });

  const resolveProviderModelsForTest = (provider: Record<string, any>) => {
    const builtinMeta =
      provider.provider_type === 'custom'
        ? undefined
        : providerRegistry.providers.find((item: any) => item.id === provider.provider_type);
    const overrides = provider.model_metadata_overrides || {};
    const customModels = provider.custom_models || [];
    const chatModels = new Map<string, any>();
    const embeddingModels = new Map<string, any>();
    const imageGenerationModels = new Map<string, any>();

    for (const model of builtinMeta?.chat_models || []) {
      const override = overrides[model.id];
      const capabilities = {
        vision: model.capabilities.vision,
        image_output: model.capabilities.image_output,
        tool_calling: model.capabilities.tool_calling,
        reasoning: model.capabilities.reasoning,
        embedding: false,
        ...(override?.capabilities || {}),
      };
      const modalities = defaultChatModalities(capabilities);
      chatModels.set(model.id, {
        id: model.id,
        label: override?.label || model.label || model.id,
        description: override?.description,
        icon: override?.icon,
        source: 'builtin',
        hidden: Boolean(override?.hidden),
        preferred: Boolean(override?.preferred),
        capabilities,
        limits: { ...(model.limits || {}), ...(override?.limits || {}) },
        input_modalities: override?.input_modalities || modalities.input,
        output_modalities: override?.output_modalities || modalities.output,
        provider_options_example: override?.provider_options_example || model.provider_options_example || {},
      });
    }

    for (const model of builtinMeta?.embedding_models || []) {
      const override = overrides[model.id];
      const capabilities = {
        vision: false,
        image_output: false,
        tool_calling: false,
        reasoning: false,
        embedding: true,
        ...(override?.capabilities || {}),
      };
      const modalities = defaultEmbeddingModalities(capabilities);
      embeddingModels.set(model.id, {
        id: model.id,
        label: override?.label || model.label || model.id,
        description: override?.description,
        icon: override?.icon,
        source: 'builtin',
        hidden: Boolean(override?.hidden),
        preferred: Boolean(override?.preferred),
        capabilities,
        dimensions: model.dimensions || [],
        limits: { ...(model.limits || {}), ...(override?.limits || {}) },
        input_modalities: override?.input_modalities || modalities.input,
        output_modalities: override?.output_modalities || modalities.output,
        provider_options_example: override?.provider_options_example || model.provider_options_example || {},
      });
    }

    for (const model of builtinMeta?.image_generation_models || []) {
      const override = overrides[model.id];
      imageGenerationModels.set(model.id, {
        id: model.id,
        label: override?.label || model.label || model.id,
        description: override?.description,
        icon: override?.icon,
        source: 'builtin',
        hidden: Boolean(override?.hidden),
        preferred: Boolean(override?.preferred),
        capabilities: {
          vision: false,
          image_output: true,
          tool_calling: false,
          reasoning: false,
          embedding: false,
          ...(override?.capabilities || {}),
        },
        limits: { ...(override?.limits || {}) },
        input_modalities: override?.input_modalities || ['text'],
        output_modalities: override?.output_modalities || ['image'],
        provider_options_example: override?.provider_options_example || model.provider_options_example || {},
      });
    }

    const customBaseCapabilities =
      provider.provider_type === 'custom'
        ? { ...providerRegistry.custom_provider.capabilities }
        : {
            vision: false,
            image_output: false,
            tool_calling: true,
            reasoning: true,
            embedding: false,
          };
    const customBaseLimits =
      provider.provider_type === 'custom'
        ? { ...providerRegistry.custom_provider.limits }
        : { context_window: null, max_output_tokens: null };
    const customProviderOptions =
      provider.provider_type === 'custom'
        ? providerRegistry.custom_provider.provider_options_example || {}
        : {};

    for (const modelId of customModels) {
      if (chatModels.has(modelId)) continue;
      const override = overrides[modelId];
      const capabilities = { ...customBaseCapabilities, ...(override?.capabilities || {}) };
      const modalities = defaultChatModalities(capabilities);
      chatModels.set(modelId, {
        id: modelId,
        label: override?.label || modelId,
        description: override?.description,
        icon: override?.icon,
        source: 'manual',
        hidden: Boolean(override?.hidden),
        preferred: Boolean(override?.preferred),
        capabilities,
        limits: { ...customBaseLimits, ...(override?.limits || {}) },
        input_modalities: override?.input_modalities || modalities.input,
        output_modalities: override?.output_modalities || modalities.output,
        provider_options_example: override?.provider_options_example || customProviderOptions,
      });
    }

    for (const [modelId, override] of Object.entries(overrides) as Array<[string, any]>) {
      if (!chatModels.has(modelId) && !override?.capabilities?.embedding && !override?.capabilities?.image_output) {
        const capabilities = { ...customBaseCapabilities, ...(override?.capabilities || {}) };
        const modalities = defaultChatModalities(capabilities);
        chatModels.set(modelId, {
          id: modelId,
          label: override?.label || modelId,
          description: override?.description,
          icon: override?.icon,
          source: 'manual',
          hidden: Boolean(override?.hidden),
          preferred: Boolean(override?.preferred),
          capabilities,
          limits: { ...customBaseLimits, ...(override?.limits || {}) },
          input_modalities: override?.input_modalities || modalities.input,
          output_modalities: override?.output_modalities || modalities.output,
          provider_options_example: override?.provider_options_example || customProviderOptions,
        });
      }

      if (override?.capabilities?.image_output && !imageGenerationModels.has(modelId)) {
        const baseChat = chatModels.get(modelId);
        imageGenerationModels.set(modelId, {
          id: modelId,
          label: override?.label || baseChat?.label || modelId,
          description: override?.description || baseChat?.description,
          icon: override?.icon || baseChat?.icon,
          source: baseChat?.source || 'manual',
          hidden: Boolean(override?.hidden),
          preferred: Boolean(override?.preferred),
          capabilities: {
            ...(baseChat?.capabilities || {
              vision: false,
              image_output: true,
              tool_calling: false,
              reasoning: false,
              embedding: false,
            }),
            ...(override?.capabilities || {}),
            image_output: true,
            embedding: false,
          },
          limits: { ...(baseChat?.limits || customBaseLimits), ...(override?.limits || {}) },
          input_modalities: override?.input_modalities || ['text'],
          output_modalities: override?.output_modalities || ['image'],
          provider_options_example:
            override?.provider_options_example || baseChat?.provider_options_example || customProviderOptions,
        });
      }

      if (override?.capabilities?.embedding && !embeddingModels.has(modelId)) {
        const baseChat = chatModels.get(modelId);
        const capabilities = {
          ...(baseChat?.capabilities || {
            vision: false,
            image_output: false,
            tool_calling: false,
            reasoning: false,
            embedding: true,
          }),
          ...(override?.capabilities || {}),
          embedding: true,
        };
        const modalities = defaultEmbeddingModalities(capabilities);
        embeddingModels.set(modelId, {
          id: modelId,
          label: override?.label || baseChat?.label || modelId,
          description: override?.description || baseChat?.description,
          icon: override?.icon || baseChat?.icon,
          source: baseChat?.source || 'manual',
          hidden: Boolean(override?.hidden),
          preferred: Boolean(override?.preferred),
          capabilities,
          dimensions: [],
          limits: { ...(baseChat?.limits || customBaseLimits), ...(override?.limits || {}) },
          input_modalities: override?.input_modalities || modalities.input,
          output_modalities: override?.output_modalities || modalities.output,
          provider_options_example:
            override?.provider_options_example || baseChat?.provider_options_example || customProviderOptions,
        });
      }
    }

    return {
      chat_models: Array.from(chatModels.values()),
      embedding_models: Array.from(embeddingModels.values()),
      image_generation_models: Array.from(imageGenerationModels.values()),
    };
  };

  const toCatalogProvider = (providerId: string, provider: Record<string, any>) => {
    const builtinMeta =
      provider.provider_type === 'custom'
        ? undefined
        : providerRegistry.providers.find((item: any) => item.id === provider.provider_type);
    const resolved = resolveProviderModelsForTest(provider);
    return {
      ...(builtinMeta || {}),
      id: providerId,
      provider_type: provider.provider_type,
      source: provider.provider_type === 'custom' ? 'custom' : 'builtin',
      display_name: provider.display_name || builtinMeta?.display_name || providerId,
      description: builtinMeta?.description,
      icon: provider.provider_type === 'custom' ? 'custom' : builtinMeta?.icon,
      default_model: provider.custom_default_model || builtinMeta?.default_model || resolved.chat_models[0]?.id,
      default_classify_model:
        builtinMeta?.default_classify_model ||
        provider.custom_default_model ||
        builtinMeta?.default_model ||
        resolved.chat_models[0]?.id,
      default_base_url: provider.base_url || builtinMeta?.default_base_url || '',
      api_format: provider.api_format,
      fields: provider.provider_type === 'custom' ? providerRegistry.custom_provider.fields : builtinMeta?.fields,
      resolved_chat_models: resolved.chat_models,
      resolved_embedding_models: resolved.embedding_models,
      resolved_image_generation_models: resolved.image_generation_models,
    };
  };

  const buildCatalog = (providers: Record<string, any> = {}) => {
    const builtinProviders = providerRegistry.providers.map((providerMeta: any) =>
      toCatalogProvider(providerMeta.id, {
        enabled: providers[providerMeta.id]?.enabled ?? false,
        provider_type: providerMeta.id,
        display_name: providers[providerMeta.id]?.display_name || providerMeta.display_name || providerMeta.id,
        api_key: providers[providerMeta.id]?.api_key || '',
        base_url: providers[providerMeta.id]?.base_url || providerMeta.default_base_url || '',
        api_format: providers[providerMeta.id]?.api_format,
        custom_models: providers[providerMeta.id]?.custom_models || [],
        custom_default_model: providers[providerMeta.id]?.custom_default_model || '',
        model_metadata_overrides: providers[providerMeta.id]?.model_metadata_overrides || {},
      })
    );
    const customProviders = Object.entries(providers)
      .filter(([, provider]) => provider?.provider_type === 'custom')
      .map(([providerId, provider]) => toCatalogProvider(providerId, provider));
    return {
      providers: [...builtinProviders, ...customProviders],
    };
  };

  return {
    ...actual,
    configApi: {
      ...actual.configApi,
      getLLMProviderCatalog: vi.fn().mockResolvedValue(buildCatalog()),
      resolveLLMProviderCatalog: vi.fn().mockImplementation(async (payload?: { providers?: Record<string, any> }) =>
        buildCatalog(payload?.providers || {})
      ),
      getLLMCustomProviderTemplate: vi.fn().mockResolvedValue({
        template: providerRegistry.custom_provider,
        defaults: defaultCustomProvider,
      }),
      discoverLLMProviderModels: vi.fn().mockResolvedValue({
        models: ['fetched-model-1', 'fetched-model-2'],
        default_model: 'fetched-model-1',
      }),
      testLLMProviderConnection: vi.fn().mockResolvedValue({
        model: 'gpt-5.2',
        latency_ms: 42,
        preview: 'hello',
      }),
    },
  };
});

describe('config forms', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const llmValue = {
    providers: {
      openai: {
        enabled: true,
        provider_type: 'openai',
        display_name: 'OpenAI',
        api_key: 'sk-openai',
        base_url: 'https://api.openai.com/v1',
      },
      anthropic: {
        enabled: false,
        provider_type: 'anthropic',
        display_name: 'Anthropic',
        api_key: '',
        base_url: 'https://api.anthropic.com/v1',
      },
      glm: {
        enabled: true,
        provider_type: 'glm',
        display_name: 'Z.ai',
        api_key: 'sk-glm',
        base_url: 'https://open.bigmodel.cn/api/paas/v4',
      },
    },
    selections: {
      context_decider: {
        provider_id: 'openai',
        model: 'gpt-5.2',
        capability_override_enabled: false,
        capabilities: {
          vision: true,
          image_output: false,
          tool_calling: true,
          reasoning: true,
          embedding: false,
        },
        limits: {
          context_window: 400000,
          max_output_tokens: 128000,
        },
        provider_options: {},
      },
      core: {
        provider_id: 'openai',
        model: 'gpt-5.2',
        capability_override_enabled: false,
        capabilities: {
          vision: true,
          image_output: false,
          tool_calling: true,
          reasoning: true,
          embedding: false,
        },
        limits: {
          context_window: 400000,
          max_output_tokens: 128000,
        },
        provider_options: {},
      },
      embedding: {
        provider_id: 'openai',
        model: 'text-embedding-3-large',
        capability_override_enabled: false,
        capabilities: {
          vision: false,
          image_output: false,
          tool_calling: false,
          reasoning: false,
          embedding: true,
        },
        limits: {
          context_window: 8192,
          max_output_tokens: 0,
        },
        provider_options: {},
      },
    },
    model_runtime_overrides: {},
  };

  it('renders the configured builtin providers with local icons in the provider list', async () => {
    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode={false} surface="settings" view="providers" showSectionIntro={false} />
      </Form>
    );

    const providerList = await screen.findByTestId('llm-provider-list-pane');

    expect(within(providerList).getByText('OpenAI')).toBeInTheDocument();
    expect(within(providerList).getByText('Anthropic')).toBeInTheDocument();
    expect(within(providerList).getByText('Z.ai')).toBeInTheDocument();
    expect(within(providerList).getByTestId('llm-provider-icon-openai')).toBeInTheDocument();
    expect(within(providerList).getByTestId('llm-provider-icon-anthropic')).toBeInTheDocument();
    expect(within(providerList).getByTestId('llm-provider-icon-zai')).toBeInTheDocument();
  });

  it('pins enabled providers above disabled providers in the settings provider list', async () => {
    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode={false} surface="settings" view="providers" showSectionIntro={false} />
      </Form>
    );

    const providerList = await screen.findByTestId('llm-provider-list-pane');
    const openAiButton = within(providerList).getByText('OpenAI').closest('button');
    const zaiButton = within(providerList).getByText('Z.ai').closest('button');
    const anthropicButton = within(providerList).getByText('Anthropic').closest('button');

    expect(openAiButton).toBeTruthy();
    expect(zaiButton).toBeTruthy();
    expect(anthropicButton).toBeTruthy();
    expect(
      openAiButton!.compareDocumentPosition(anthropicButton!) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(
      zaiButton!.compareDocumentPosition(anthropicButton!) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  });

  it('uses a switch control for provider enablement in the detail pane', async () => {
    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode />
      </Form>
    );

    await waitFor(() => {
      expect(screen.getByTestId('llm-provider-detail-pane')).toBeInTheDocument();
    });

    expect(screen.getByRole('switch', { name: 'llm.fields.enabled' })).toBeInTheDocument();
  });

  it('does not prefill default base url for inactive built-in providers', async () => {
    const user = userEvent.setup();
    const valueWithoutAnthropicBaseUrl = {
      ...llmValue,
      providers: {
        ...llmValue.providers,
        anthropic: {
          ...llmValue.providers.anthropic,
          base_url: '',
        },
      },
    };

    render(
      <Form initialValues={{ llm: valueWithoutAnthropicBaseUrl }}>
        <LLMForm quickMode />
      </Form>
    );

    await user.click((await screen.findByText('Anthropic')).closest('button') as HTMLButtonElement);

    expect(screen.getByLabelText('llm.fields.baseUrl')).toHaveValue('');
  });

  it('lets user switch the core scenario model and shows vision warning', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode />
      </Form>
    );

    const coreCard = await screen.findByTestId('llm-scenario-core');
    const providerSelect = within(coreCard).getByLabelText('llm.fields.provider');

    await user.click(providerSelect);
    await user.click(screen.getByRole('button', { name: 'Z.ai' }));

    await waitFor(() => {
      expect(within(coreCard).getByLabelText('llm.fields.model')).toHaveTextContent('GLM-5');
    });
    expect(screen.getByText('llm.warnings.coreVisionMissing')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('llm.warnings.coreVisionMissing');
  });

  it('shows a memory summarizer tab in settings and lets users unlock dedicated config', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode={false} surface="settings" view="models" showSectionIntro={false} />
      </Form>
    );

    await user.click(await screen.findByRole('tab', { name: 'llm.scenarios.memory_summarizer.title' }));

    const scenarioCard = await screen.findByTestId('llm-scenario-memory_summarizer');
    const inheritCheckbox = within(scenarioCard).getByRole('checkbox', {
      name: 'llm.scenarios.memory_summarizer.inheritLabel',
    });
    const providerSelect = within(scenarioCard).getByLabelText('llm.fields.provider');

    expect(inheritCheckbox).toBeChecked();
    expect(providerSelect).toBeDisabled();

    await user.click(inheritCheckbox);

    expect(providerSelect).not.toBeDisabled();
  });

  it('keeps the memory summarizer selection synced to core while inheritance is enabled', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode={false} surface="settings" view="models" showSectionIntro={false} />
      </Form>
    );

    const coreCard = await screen.findByTestId('llm-scenario-core');
    const coreProviderSelect = within(coreCard).getByLabelText('llm.fields.provider');

    await user.click(coreProviderSelect);
    await user.click(screen.getByRole('button', { name: 'Z.ai' }));

    await user.click(await screen.findByRole('tab', { name: 'llm.scenarios.memory_summarizer.title' }));

    const summaryCard = await screen.findByTestId('llm-scenario-memory_summarizer');
    const summaryProviderSelect = within(summaryCard).getByLabelText('llm.fields.provider');

    await waitFor(() => {
      expect(summaryProviderSelect).toHaveTextContent('Z.ai');
    });
    expect(summaryProviderSelect).toBeDisabled();
  });

  it('hides the core vision warning for custom models with vision metadata overrides', async () => {
    const customValue = {
      ...structuredClone(llmValue),
      providers: {
        ...structuredClone(llmValue.providers),
        custom_proxy: {
          enabled: true,
          provider_type: 'custom',
          display_name: 'Proxy',
          api_key: 'sk-proxy',
          base_url: 'https://proxy.example.com/v1',
          api_format: 'openai',
          custom_models: ['foo-vision'],
          custom_default_model: 'foo-vision',
          model_metadata_overrides: {
            'foo-vision': {
              capabilities: {
                vision: true,
              },
            },
          },
        },
      },
      selections: {
        ...structuredClone(llmValue.selections),
        core: {
          ...structuredClone(llmValue.selections.core),
          provider_id: 'custom_proxy',
          model: 'foo-vision',
          capabilities: {
            ...structuredClone(llmValue.selections.core.capabilities),
            vision: false,
          },
        },
      },
    };

    render(
      <Form initialValues={{ llm: customValue }}>
        <LLMForm quickMode={false} surface="settings" view="models" showSectionIntro={false} />
      </Form>
    );

    await screen.findByTestId('llm-scenario-core');

    await waitFor(() => {
      expect(screen.queryByText('llm.warnings.coreVisionMissing')).not.toBeInTheDocument();
    });
  });

  it('respects vision overrides for custom models whose ids include provider prefixes', async () => {
    const customValue = {
      ...structuredClone(llmValue),
      providers: {
        ...structuredClone(llmValue.providers),
        custom_proxy: {
          enabled: true,
          provider_type: 'custom',
          display_name: 'Zen',
          api_key: 'sk-zen',
          base_url: 'https://proxy.example.com/v1',
          api_format: 'openai',
          custom_models: ['openai/gpt-5.2'],
          custom_default_model: 'openai/gpt-5.2',
          model_metadata_overrides: {
            'openai/gpt-5.2': {
              capabilities: {
                vision: true,
              },
            },
          },
        },
      },
      selections: {
        ...structuredClone(llmValue.selections),
        core: {
          ...structuredClone(llmValue.selections.core),
          provider_id: 'custom_proxy',
          model: 'openai/gpt-5.2',
          capabilities: {
            ...structuredClone(llmValue.selections.core.capabilities),
            vision: false,
          },
        },
      },
    };

    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: customValue }}>
        <LLMForm quickMode={false} surface="settings" view="all" showSectionIntro={false} />
      </Form>
    );

    const coreCard = await screen.findByTestId('llm-scenario-core');
    await waitFor(() => {
      expect(within(coreCard).getByLabelText('llm.fields.model')).toHaveTextContent('openai/gpt-5.2');
    });
    expect(screen.queryByText('llm.warnings.coreVisionMissing')).not.toBeInTheDocument();

    const providerList = await screen.findByTestId('llm-provider-list-pane');
    await user.click((within(providerList).getByText('Zen') as HTMLElement).closest('button') as HTMLButtonElement);
    const modelList = await screen.findByTestId('llm-provider-model-list-pane');
    await user.click((within(modelList).getAllByText('openai/gpt-5.2')[0] as HTMLElement).closest('button') as HTMLButtonElement);

    const editor = screen.getByTestId('llm-provider-model-editor');
    expect(within(editor).getByRole('switch', { name: 'llm.modelFields.vision' })).toHaveAttribute('aria-checked', 'true');
  });

  it('sorts model options alphabetically in the scenario model menu', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode={false} surface="settings" view="models" showSectionIntro={false} />
      </Form>
    );

    const coreCard = await screen.findByTestId('llm-scenario-core');
    await user.click(within(coreCard).getByLabelText('llm.fields.model'));

    const menu = document.querySelector('[data-select-field-menu]');
    expect(menu).toBeTruthy();

    const firstModelButton = within(menu as HTMLElement).getByRole('button', { name: 'GPT-4.1 Mini' });
    const secondModelButton = within(menu as HTMLElement).getByRole('button', { name: 'GPT-5.2' });

    expect(
      firstModelButton.compareDocumentPosition(secondModelButton) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  });

  it('shows a search box for model menus with more than ten options and filters the list', async () => {
    const user = userEvent.setup();
    const manyModels = [
      'zeta-model',
      'alpha-model',
      'lambda-model',
      'beta-model',
      'omega-model',
      'delta-model',
      'sigma-model',
      'theta-model',
      'eta-model',
      'gamma-model',
      'kappa-model',
    ].map((id) => ({
      id,
      label: id,
      source: 'builtin' as const,
      hidden: false,
      preferred: false,
      capabilities: {
        vision: true,
        image_output: false,
        tool_calling: true,
        reasoning: true,
        embedding: false,
      },
      limits: {
        context_window: 128000,
        max_output_tokens: 32000,
      },
      input_modalities: ['text', 'image'],
      output_modalities: ['text'],
      provider_options_example: {},
    }));

    const manyModelCatalog = {
      providers: [
        {
          id: 'openai',
          provider_type: 'openai',
          source: 'builtin',
          display_name: 'OpenAI',
          description: 'General purpose',
          icon: 'openai',
          default_model: 'alpha-model',
          default_classify_model: 'alpha-model',
          default_base_url: 'https://api.openai.com/v1',
          resolved_chat_models: manyModels,
          resolved_embedding_models: [],
          fields: {
            api_key: { visible: true, required: true },
            base_url: { visible: true, required: false },
          },
        },
      ],
    };
    const resolveCatalogMock = vi.mocked(configApi.resolveLLMProviderCatalog);
    const templateMock = vi.mocked(configApi.getLLMCustomProviderTemplate);
    const defaultResolveCatalogImplementation = resolveCatalogMock.getMockImplementation();
    const defaultTemplateImplementation = templateMock.getMockImplementation();
    resolveCatalogMock.mockImplementation(async () => manyModelCatalog as any);
    templateMock.mockImplementation(async () => ({
      template: {
        enabled: true,
        display_name: 'Custom Provider',
        fields: {
          custom_name: { visible: true, required: true },
          api_format: { visible: true, required: true, options: ['openai', 'anthropic'] },
          model: { visible: true, required: true },
          api_key: { visible: true, required: true },
          base_url: { visible: true, required: false },
        },
        capabilities: {
          vision: false,
          image_output: false,
          tool_calling: true,
          reasoning: true,
          embedding: false,
        },
        limits: {
          context_window: null,
          max_output_tokens: null,
        },
        provider_options_example: {},
      },
      defaults: {
        enabled: true,
        provider_type: 'custom',
        display_name: '',
        api_key: '',
        base_url: '',
        api_format: 'openai',
        custom_models: [],
        custom_default_model: '',
        model_metadata_overrides: {},
      },
    }) as any);

    const manyModelValue = {
      providers: {
        openai: {
          enabled: true,
          provider_type: 'openai',
          display_name: 'OpenAI',
          api_key: 'sk-openai',
          base_url: 'https://api.openai.com/v1',
        },
      },
      selections: {
        context_decider: {
          provider_id: 'openai',
          model: 'alpha-model',
          capability_override_enabled: false,
          capabilities: {
            vision: true,
            image_output: false,
            tool_calling: true,
            reasoning: true,
            embedding: false,
          },
          limits: {
            context_window: 128000,
            max_output_tokens: 32000,
          },
          provider_options: {},
        },
        core: {
          provider_id: 'openai',
          model: 'alpha-model',
          capability_override_enabled: false,
          capabilities: {
            vision: true,
            image_output: false,
            tool_calling: true,
            reasoning: true,
            embedding: false,
          },
          limits: {
            context_window: 128000,
            max_output_tokens: 32000,
          },
          provider_options: {},
        },
      },
      model_runtime_overrides: {},
    } as unknown as LLMConfig;

    try {
      render(
        <Form initialValues={{ llm: manyModelValue }}>
          <LLMForm quickMode={false} surface="settings" view="models" showSectionIntro={false} />
        </Form>
      );

      const coreCard = await screen.findByTestId('llm-scenario-core');
      await user.click(within(coreCard).getByLabelText('llm.fields.model'));

      const searchInput = screen.getByPlaceholderText('llm.modelSelection.searchPlaceholder');
      expect(searchInput).toBeInTheDocument();

      await user.type(searchInput, 'omega');

      const menu = document.querySelector('[data-select-field-menu]');
      expect(menu).toBeTruthy();
      await waitFor(() => {
        expect(within(menu as HTMLElement).getByRole('button', { name: 'omega-model' })).toBeInTheDocument();
        expect(within(menu as HTMLElement).queryByRole('button', { name: 'alpha-model' })).not.toBeInTheDocument();
      });
    } finally {
      if (defaultResolveCatalogImplementation) {
        resolveCatalogMock.mockImplementation(defaultResolveCatalogImplementation);
      }
      if (defaultTemplateImplementation) {
        templateMock.mockImplementation(defaultTemplateImplementation);
      }
    }
  });

  it('asks for confirmation before changing embedding dimension on the settings surface', async () => {
    const user = userEvent.setup();
    const controlledValue = {
      ...llmValue,
      selections: {
        ...llmValue.selections,
        embedding: {
          provider_id: 'openai',
          model: 'text-embedding-3-small',
          embedding_dimension: 1536,
          capability_override_enabled: false,
          capabilities: {
            vision: false,
            image_output: false,
            tool_calling: false,
            reasoning: false,
            embedding: true,
          },
          limits: {
            context_window: null,
            max_output_tokens: null,
          },
          provider_options: {},
        },
      },
    } as unknown as LLMConfig;
    const onChange = vi.fn();

    render(
      <LLMForm
        quickMode={false}
        surface="settings"
        view="models"
        showSectionIntro={false}
        value={controlledValue}
        onChange={onChange}
      />
    );

    await user.click(await screen.findByRole('tab', { name: 'llm.scenarios.embedding.title' }));
    const embeddingCard = await screen.findByTestId('llm-scenario-embedding');
    const dimensionField = within(embeddingCard).getByLabelText('llm.fields.embeddingDimension');
    onChange.mockClear();

    await user.click(dimensionField);
    await user.click(screen.getByRole('button', { name: '512' }));

    expect(await screen.findByText('llm.embeddingDimensionConfirm.title')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'llm.embeddingDimensionConfirm.cancel' }));
    const latestAfterCancel = onChange.mock.calls[onChange.mock.calls.length - 1]?.[0] ?? controlledValue;
    expect(latestAfterCancel.selections.embedding.embedding_dimension).toBe(1536);

    await user.click(dimensionField);
    await user.click(screen.getByRole('button', { name: '512' }));
    await user.click(screen.getByRole('button', { name: 'llm.embeddingDimensionConfirm.confirm' }));

    await waitFor(() => {
      const latest = onChange.mock.calls[onChange.mock.calls.length - 1]?.[0];
      expect(latest.selections.embedding.embedding_dimension).toBe(512);
    });
  });

  it('includes override-promoted embedding models in the embedding selection list', async () => {
    const user = userEvent.setup();
    const controlledValue = {
      ...llmValue,
      providers: {
        ...llmValue.providers,
        openai: {
          ...llmValue.providers.openai,
          model_metadata_overrides: {
            'gpt-5.2': {
              label: 'GPT-5.2 Vector',
              capabilities: {
                embedding: true,
              },
            },
          },
        },
      },
      selections: {
        ...llmValue.selections,
        embedding: {
          provider_id: 'openai',
          model: 'gpt-5.2',
          embedding_dimension: null,
          capability_override_enabled: false,
          capabilities: {
            vision: false,
            image_output: false,
            tool_calling: false,
            reasoning: false,
            embedding: true,
          },
          limits: {
            context_window: null,
            max_output_tokens: null,
          },
          provider_options: {},
        },
      },
    } as unknown as LLMConfig;

    render(
      <LLMForm
        quickMode={false}
        surface="settings"
        view="models"
        showSectionIntro={false}
        value={controlledValue}
        onChange={vi.fn()}
      />
    );

    await user.click(await screen.findByRole('tab', { name: 'llm.scenarios.embedding.title' }));
    const embeddingCard = await screen.findByTestId('llm-scenario-embedding');
    expect(within(embeddingCard).getByLabelText('llm.fields.model')).toHaveTextContent('GPT-5.2 Vector (OpenAI)');
  });

  it('stores max concurrency as a shared runtime override for the selected model', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const controlledValue = {
      ...llmValue,
      model_runtime_overrides: {},
    } as unknown as LLMConfig;

    render(
      <LLMForm
        quickMode={false}
        surface="settings"
        view="models"
        showSectionIntro={false}
        value={controlledValue}
        onChange={onChange}
      />
    );

    const coreCard = await screen.findByTestId('llm-scenario-core');

    await user.click(within(coreCard).getByRole('button', { name: 'llm.showAdvanced' }));

    const maxConcurrencyField = within(coreCard).getByLabelText('llm.fields.maxConcurrency');
    await user.clear(maxConcurrencyField);
    await user.type(maxConcurrencyField, '9');

    const expectedOverrides = {
      'openai::api.openai.com::gpt-5.2::chat': {
        max_concurrency: 9,
      },
    };

    await waitFor(() => {
      expect(
        onChange.mock.calls.some(
          ([nextValue]) =>
            JSON.stringify(nextValue?.model_runtime_overrides ?? {}) === JSON.stringify(expectedOverrides)
        )
      ).toBe(true);
    });
  });

  it('does not auto-select a provider or model when onboarding starts with all providers disabled', async () => {
    const onChange = vi.fn();
    const blankValue = {
      providers: {},
      selections: {
        context_decider: {
          provider_id: '',
          model: '',
          capability_override_enabled: false,
          capabilities: {
            vision: false,
            image_output: false,
            tool_calling: true,
            reasoning: true,
            embedding: false,
          },
          limits: {
            context_window: null,
            max_output_tokens: null,
          },
          provider_options: {},
        },
        core: {
          provider_id: '',
          model: '',
          capability_override_enabled: false,
          capabilities: {
            vision: false,
            image_output: false,
            tool_calling: true,
            reasoning: true,
            embedding: false,
          },
          limits: {
            context_window: null,
            max_output_tokens: null,
          },
          provider_options: {},
        },
        embedding: {
          provider_id: '',
          model: '',
          capability_override_enabled: false,
          capabilities: {
            vision: false,
            image_output: false,
            tool_calling: false,
            reasoning: false,
            embedding: true,
          },
          limits: {
            context_window: 8192,
            max_output_tokens: 8192,
          },
          provider_options: {},
        },
        memory_summarizer: {
          provider_id: '',
          model: '',
          capability_override_enabled: false,
          capabilities: {
            vision: false,
            image_output: false,
            tool_calling: true,
            reasoning: true,
            embedding: false,
          },
          limits: {
            context_window: null,
            max_output_tokens: null,
          },
          provider_options: {},
        },
        image_generation: {
          provider_id: '',
          model: '',
          capability_override_enabled: false,
          capabilities: {
            vision: false,
            image_output: true,
            tool_calling: false,
            reasoning: false,
            embedding: false,
          },
          limits: {
            context_window: null,
            max_output_tokens: null,
          },
          provider_options: {},
        },
      },
      model_runtime_overrides: {},
    };

    render(<LLMForm quickMode={false} value={blankValue} onChange={onChange} />);

    await waitFor(() => {
      expect(screen.getByText('llm.providerConfiguration.title')).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(onChange).toHaveBeenCalled();
    });

    const latest = onChange.mock.calls[onChange.mock.calls.length - 1]?.[0];

    expect(latest.providers.openai.enabled).toBe(false);
    expect(latest.providers.anthropic.enabled).toBe(false);
    expect(latest.providers.glm.enabled).toBe(false);
    expect(latest.selections.context_decider.provider_id).toBe('');
    expect(latest.selections.context_decider.model).toBe('');
    expect(latest.selections.core.provider_id).toBe('');
    expect(latest.selections.core.model).toBe('');
  });

  it('lets users add a custom provider model manually', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode />
      </Form>
    );

    await user.click(await screen.findByText('llm.actions.addCustomProvider'));
    await user.type(screen.getByLabelText('llm.fields.modelManualEntry'), 'foo-1');
    await user.click(screen.getByRole('button', { name: 'llm.actions.addModel' }));

    expect(screen.getAllByText('foo-1').length).toBeGreaterThan(0);
    expect(screen.getByLabelText('llm.fields.defaultModel')).toHaveTextContent('foo-1');
  });

  it('lets users add a custom image model and select it for image generation', async () => {
    const user = userEvent.setup();

    function ControlledSettingsLlmForm() {
      const [value, setValue] = React.useState(llmValue as unknown as LLMConfig);
      return (
        <LLMForm
          quickMode={false}
          surface="settings"
          showSectionIntro={false}
          value={value}
          onChange={setValue}
        />
      );
    }

    render(<ControlledSettingsLlmForm />);

    await user.click(await screen.findByRole('button', { name: 'llm.modelKinds.chat' }));
    await user.click(screen.getByRole('option', { name: 'llm.modelKinds.image' }));
    await user.type(screen.getByLabelText('llm.fields.modelManualEntry'), 'gpt-image-custom');
    await user.click(screen.getByRole('button', { name: 'llm.actions.addModel' }));

    await waitFor(() => {
      expect(screen.getAllByText('gpt-image-custom').length).toBeGreaterThan(0);
    });

    const imageTab = screen.getByRole('tab', { name: 'llm.scenarios.image_generation.title' });
    await user.click(imageTab);

    const imagePanel = screen.getByTestId('llm-scenario-image_generation');
    const providerField = within(imagePanel).getByLabelText('llm.fields.provider');
    await waitFor(() => {
      expect(providerField).toHaveTextContent('OpenAI');
    });

    const modelField = within(imagePanel).getByLabelText('llm.fields.model');
    await user.click(modelField);

    await waitFor(() => {
      const menu = document.querySelector('[data-select-field-menu]');
      expect(menu).not.toBeNull();
      expect(within(menu as HTMLElement).getByText('gpt-image-custom')).toBeInTheDocument();
    });
  });

  it('writes model metadata overrides from the provider workbench', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();

    render(
      <LLMForm
        quickMode={false}
        surface="settings"
        view="providers"
        showSectionIntro={false}
        value={llmValue as unknown as LLMConfig}
        onChange={onChange}
      />
    );

    const modelList = await screen.findByTestId('llm-provider-model-list-pane');
    await user.click(within(modelList).getByText('GPT-5.2'));
    await user.click(screen.getByRole('switch', { name: 'llm.modelFields.reasoning' }));

    expect(onChange).toHaveBeenCalled();
    const overrideCall = onChange.mock.calls.find(
      (args: any[]) => args[0]?.providers?.openai?.model_metadata_overrides?.['gpt-5.2']?.capabilities?.reasoning === false
    );
    expect(overrideCall).toBeTruthy();
  });

  it('reflects persisted capability overrides in the provider workbench toggles', async () => {
    const user = userEvent.setup();
    const overrideValue = {
      ...structuredClone(llmValue),
      providers: {
        ...structuredClone(llmValue.providers),
        glm: {
          ...structuredClone(llmValue.providers.glm),
          model_metadata_overrides: {
            'glm-5': {
              capabilities: {
                vision: true,
              },
            },
          },
        },
      },
    };

    render(
      <Form initialValues={{ llm: overrideValue }}>
        <LLMForm quickMode={false} surface="settings" view="providers" showSectionIntro={false} />
      </Form>
    );

    await user.click((await screen.findByText('Z.ai')).closest('button') as HTMLButtonElement);
    const modelList = await screen.findByTestId('llm-provider-model-list-pane');
    await user.click((within(modelList).getByText('GLM-5') as HTMLElement).closest('button') as HTMLButtonElement);

    const editor = screen.getByTestId('llm-provider-model-editor');
    expect((within(modelList).getByText('GLM-5') as HTMLElement).closest('button')).toHaveAttribute('aria-current', 'true');
    expect(within(editor).getByRole('switch', { name: 'llm.modelFields.vision' })).toHaveAttribute('aria-checked', 'true');
  });

  it('keeps the provider workbench focused on name, capabilities, and limits', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode={false} surface="settings" view="providers" showSectionIntro={false} />
      </Form>
    );

    const modelList = await screen.findByTestId('llm-provider-model-list-pane');
    await user.click((within(modelList).getByText('GPT-5.2') as HTMLElement).closest('button') as HTMLButtonElement);

    const editor = screen.getByTestId('llm-provider-model-editor');
    expect(within(editor).getByLabelText('llm.fields.displayName')).toBeInTheDocument();
    expect(within(editor).queryByLabelText('llm.modelFields.icon')).not.toBeInTheDocument();
    expect(within(editor).queryByLabelText('llm.modelFields.description')).not.toBeInTheDocument();
    expect(within(editor).queryByRole('switch', { name: 'llm.modelFields.hidden' })).not.toBeInTheDocument();
    expect(within(editor).queryByRole('switch', { name: 'llm.modelFields.preferred' })).not.toBeInTheDocument();
  });

  it('lets users remove a custom provider and falls back to builtin providers', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode />
      </Form>
    );

    await user.click(await screen.findByText('llm.actions.addCustomProvider'));
    expect(screen.getByDisplayValue('llm.customProviderDefaultName')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'llm.actions.removeProvider' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'llm.actions.removeProvider' }));

    await waitFor(() => {
      expect(screen.queryByDisplayValue('llm.customProviderDefaultName')).not.toBeInTheDocument();
    });
    expect(screen.getByLabelText('llm.fields.apiKey')).toHaveValue('sk-openai');
    expect(screen.queryByRole('button', { name: 'llm.actions.removeProvider' })).not.toBeInTheDocument();
  });

  it('uses a selectable default model instead of free text for custom providers', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode />
      </Form>
    );

    await user.click(await screen.findByText('llm.actions.addCustomProvider'));

    const defaultModelField = screen.getByLabelText('llm.fields.defaultModel');
    expect(defaultModelField.tagName).toBe('BUTTON');
    expect(defaultModelField).toBeDisabled();

    await user.type(screen.getByLabelText('llm.fields.modelManualEntry'), 'foo-1');
    await user.click(screen.getByRole('button', { name: 'llm.actions.addModel' }));

    expect(screen.getByLabelText('llm.fields.defaultModel').tagName).toBe('BUTTON');
    expect(screen.getByLabelText('llm.fields.defaultModel')).toHaveTextContent('foo-1');
  });

  it('shows default model before model entry and adds a model id placeholder for custom providers', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode={false} surface="settings" view="providers" showSectionIntro={false} />
      </Form>
    );

    await user.click(await screen.findByText('llm.actions.addCustomProvider'));

    const defaultModelField = screen.getByLabelText('llm.fields.defaultModel');
    const modelEntryField = screen.getByLabelText('llm.fields.modelManualEntry');

    expect(modelEntryField).toHaveAttribute('placeholder', 'llm.fields.modelManualEntryPlaceholder');
    expect(
      defaultModelField.compareDocumentPosition(modelEntryField) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  });

  it('removes the ambiguous custom api format option', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode />
      </Form>
    );

    await user.click(await screen.findByText('llm.actions.addCustomProvider'));

    const apiFormatSelect = screen.getByLabelText('llm.fields.apiFormat');
    await user.click(apiFormatSelect);

    expect(screen.queryByRole('button', { name: 'llm.apiFormatOptions.custom' })).not.toBeInTheDocument();
  });

  it('fetches custom provider models on demand', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode />
      </Form>
    );

    await user.click(await screen.findByText('llm.actions.addCustomProvider'));
    await user.type(screen.getByLabelText('llm.fields.baseUrl'), 'https://proxy.example.com/v1');
    await user.click(screen.getByRole('button', { name: 'llm.actions.fetchModels' }));

    await waitFor(() => {
      expect(screen.getAllByText('fetched-model-1').length).toBeGreaterThan(0);
    });
    expect(screen.getByLabelText('llm.fields.defaultModel')).toHaveTextContent('fetched-model-1');
    expect(configApi.discoverLLMProviderModels).toHaveBeenCalled();
  });

  it('tests the active provider with current draft credentials', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode />
      </Form>
    );

    await user.clear(await screen.findByLabelText('llm.fields.apiKey'));
    await user.type(screen.getByLabelText('llm.fields.apiKey'), 'sk-draft-openai');
    await user.click(screen.getByRole('button', { name: 'llm.actions.testConnection' }));
    const testMenu = await screen.findByTestId('llm-provider-test-model-menu');
    await user.click((within(testMenu).getByText('GPT-5.2') as HTMLElement).closest('button') as HTMLButtonElement);

    await waitFor(() => {
      expect(configApi.testLLMProviderConnection).toHaveBeenCalledWith({
        provider_id: 'openai',
        model: 'gpt-5.2',
        provider: expect.objectContaining({
          provider_type: 'openai',
          api_key: 'sk-draft-openai',
          base_url: 'https://api.openai.com/v1',
        }),
      });
    });

    expect(screen.getByText('llm.providerConfiguration.testSuccess')).toBeInTheDocument();
  });

  it('lets users choose which chat model to test', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode />
      </Form>
    );

    await user.click(await screen.findByRole('button', { name: 'llm.actions.testConnection' }));
    const testMenu = await screen.findByTestId('llm-provider-test-model-menu');
    await user.click((within(testMenu).getByText('GPT-4.1 Mini') as HTMLElement).closest('button') as HTMLButtonElement);

    await waitFor(() => {
      expect(configApi.testLLMProviderConnection).toHaveBeenCalledWith(
        expect.objectContaining({
          provider_id: 'openai',
          model: 'gpt-4.1-mini',
        })
      );
    });
  });

  it('lets users reveal and hide provider api keys locally', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode={false} surface="settings" view="providers" showSectionIntro={false} />
      </Form>
    );

    const apiKeyField = await screen.findByLabelText('llm.fields.apiKey');
    const fieldWrapper = apiKeyField.parentElement?.parentElement;

    expect(apiKeyField).toHaveAttribute('type', 'password');

    const toggleButton = within(fieldWrapper as HTMLElement).getByRole('button');
    await user.click(toggleButton);
    expect(apiKeyField).toHaveAttribute('type', 'text');

    await user.click(toggleButton);
    expect(apiKeyField).toHaveAttribute('type', 'password');
  });

  it('uses the registry default base url when testing a built-in provider with a blank field', async () => {
    const user = userEvent.setup();
    const glmWithoutBaseUrl = {
      ...llmValue,
      selections: {
        ...llmValue.selections,
        context_decider: {
          ...llmValue.selections.context_decider,
          provider_id: 'openai',
          model: 'gpt-5.2',
        },
        core: {
          ...llmValue.selections.core,
          provider_id: 'openai',
          model: 'gpt-5.2',
        },
        embedding: {
          ...llmValue.selections.embedding,
          provider_id: 'glm',
          model: 'embedding-3',
        },
      },
      providers: {
        ...llmValue.providers,
        glm: {
          ...llmValue.providers.glm,
          base_url: '',
        },
      },
    };

    render(
      <Form initialValues={{ llm: glmWithoutBaseUrl }}>
        <LLMForm quickMode />
      </Form>
    );

    const providerList = await screen.findByTestId('llm-provider-list-pane');
    await user.click((within(providerList).getByText('Z.ai') as HTMLElement).closest('button') as HTMLButtonElement);
    await user.click(screen.getByRole('button', { name: 'llm.actions.testConnection' }));
    const testMenu = await screen.findByTestId('llm-provider-test-model-menu');
    expect(within(testMenu).queryByText('Embedding-3')).not.toBeInTheDocument();
    await user.click((within(testMenu).getByText('GLM-5') as HTMLElement).closest('button') as HTMLButtonElement);

    await waitFor(() => {
      expect(configApi.testLLMProviderConnection).toHaveBeenCalledWith({
        provider_id: 'glm',
        model: 'glm-5',
        provider: expect.objectContaining({
          provider_type: 'glm',
          base_url: 'https://open.bigmodel.cn/api/paas/v4',
        }),
      });
    });
  });

  it('memory form renders L2/L3/L4 layer toggles', async () => {
    render(
      <Form
        initialValues={{
          memory: {
            retention_days: 90,
            history_behavior: 'delete',
            l0: { enabled: true, checkpoint_interval_seconds: 30 },
            l1: { enabled: true, vectors_enabled: true },
            l2: {
              enabled: true,
              batch_flush_interval_seconds: 60,
              auto_extract_relations: true,
              conflict_arbitration_enabled: true,
              conflict_arbitration_min_confidence: 0.85,
            },
            l3: {
              enabled: true,
              vectors_enabled: true,
              llm_summary_enabled: true,
              temporal_llm_timeout_seconds: 3.0,
              temporal_llm_min_event_count: 2,
              summary_interval_minutes: 60,
            },
            l4: { enabled: true, vectors_enabled: true },
          },
        }}
      >
        <MemoryForm />
      </Form>
    );
    expect(screen.getByRole('switch', { name: /settings\.memory\.fields\.enable_l2\.label/i })).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: /settings\.memory\.fields\.enable_l3\.label/i })).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: /settings\.memory\.fields\.enable_l4\.label/i })).toBeInTheDocument();
  });
});
