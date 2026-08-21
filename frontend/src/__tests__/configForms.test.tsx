import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import { configApi, type LLMConfig } from '../api/modules/config';
import { SimpleForm as Form } from '../components/onboarding/simple-form';
import LLMForm from '../components/config-forms/LLMForm';
import { buildRegistryFromCatalog, normalizeLLMConfig } from '../components/config-forms/llm-form-state';
import { LLMRerankerModelPanel } from '../components/config-forms/LLMRerankerModelPanel';

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
        image_generation_models: [
          {
            id: 'gpt-image-1',
            label: 'GPT Image 1',
            supported_sizes: ['1024x1024'],
            supported_qualities: ['standard'],
            supports_seed: false,
            supports_negative_prompt: false,
            supports_reference: true,
            max_n: 4,
            native_protocol: 'openai_images',
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
        plans: [
          {
            id: 'codeplan',
            display_name: 'Z.ai CodePlan',
            default_model: 'glm-5',
            default_classify_model: 'glm-5-code',
            default_base_url: 'https://open.bigmodel.cn/api/coding/paas/v4',
            allowed_scenarios: ['context_compact', 'context_decider', 'core'],
            endpoints: [
              {
                id: 'china',
                label: 'China',
                country: 'China',
                base_url: 'https://open.bigmodel.cn/api/coding/paas/v4',
                api_format: 'openai',
              },
              {
                id: 'global',
                label: 'Global',
                base_url: 'https://api.z.ai/api/coding/paas/v4',
                api_format: 'openai',
              },
            ],
            embedding_models: [],
            image_generation_models: [],
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
              {
                id: 'glm-5-code',
                label: 'GLM-5 Code',
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
        id: 'grok',
        display_name: 'xAI Grok',
        description: 'OpenAI-compatible Grok models from xAI',
        icon: 'grok',
        default_model: 'grok-4.3',
        default_base_url: 'https://api.x.ai/v1',
        chat_models: [
          {
            id: 'grok-4.3',
            label: 'Grok 4.3',
            capabilities: {
              vision: true,
              image_output: false,
              tool_calling: true,
              reasoning: true,
              embedding: false,
            },
            limits: {
              context_window: 1000000,
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
        default_model: 'deepseek-v4-flash',
        default_base_url: 'https://api.deepseek.com',
        chat_models: [
          {
            id: 'deepseek-v4-flash',
            label: 'DeepSeek V4 Flash',
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
    services: {
      chat: { enabled: true, api_key: '', base_url: '' },
      embedding: { enabled: false, api_key: '', base_url: '' },
      image_generation: { enabled: false, api_key: '', base_url: '', timeout: 180, native_protocol: null },
      tts: { enabled: false, api_key: '', base_url: '', model: '', voice: '', response_format: '' },
    },
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

  const detectVendorForTest = (modelId?: string, baseUrl?: string): string => {
    const needleModel = (modelId || '').trim().toLowerCase();
    const needleUrl = (baseUrl || '').trim().toLowerCase();

    if (needleModel.includes('glm-') || needleModel.includes('glm4') || needleModel.includes('glm_') || needleModel.includes('chatglm') || needleModel.includes('codegeex')) {
      return 'glm';
    }
    if (needleModel.includes('qwen') || needleModel.includes('qwq') || needleModel.includes('qvq')) {
      return 'dashscope';
    }
    if (needleModel.includes('claude-')) {
      return 'anthropic';
    }
    if (needleModel.includes('grok-') || needleModel.includes('grok_')) {
      return 'grok';
    }
    if (needleModel.includes('deepseek')) {
      return 'deepseek';
    }
    if (needleModel.includes('gpt-') || needleModel.includes('o1-') || needleModel.includes('o3-') || needleModel.includes('o4-')) {
      return 'openai';
    }

    if (needleUrl.includes('bigmodel.cn') || needleUrl.includes('z.ai') || needleUrl.includes('codeplan')) {
      return 'glm';
    }
    if (needleUrl.includes('dashscope.aliyuncs.com') || needleUrl.includes('dashscope-intl.aliyuncs.com')) {
      return 'dashscope';
    }
    if (needleUrl.includes('api.anthropic.com')) {
      return 'anthropic';
    }
    if (needleUrl.includes('api.x.ai') || needleUrl.includes('x.ai')) {
      return 'grok';
    }
    if (needleUrl.includes('api.deepseek.com')) {
      return 'deepseek';
    }
    if (needleUrl.includes('api.openai.com')) {
      return 'openai';
    }

    return 'generic';
  };

  const builtinProviderVendor: Record<string, string> = {
    openai: 'openai',
    deepseek: 'deepseek',
    local: 'openai',
    anthropic: 'anthropic',
    glm: 'glm',
    dashscope: 'dashscope',
    grok: 'grok',
    gemini: 'generic',
    kimi: 'generic',
    minimax: 'generic',
  };

  const resolveProviderModelsForTest = (provider: Record<string, any>) => {
    const baseBuiltinMeta =
      provider.provider_type === 'custom'
        ? undefined
        : providerRegistry.providers.find((item: any) => item.id === provider.provider_type);
    const selectedPlan = baseBuiltinMeta?.plans?.find((plan: any) => plan.id === provider.provider_plan);
    const builtinMeta = selectedPlan
      ? {
          ...baseBuiltinMeta,
          default_model: selectedPlan.default_model || baseBuiltinMeta.default_model,
          default_classify_model: selectedPlan.default_classify_model || baseBuiltinMeta.default_classify_model,
          default_base_url: selectedPlan.default_base_url || baseBuiltinMeta.default_base_url,
          chat_models: selectedPlan.chat_models ?? baseBuiltinMeta.chat_models,
          embedding_models: selectedPlan.embedding_models ?? baseBuiltinMeta.embedding_models,
          image_generation_models: selectedPlan.image_generation_models ?? baseBuiltinMeta.image_generation_models,
        }
      : baseBuiltinMeta;
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
        vendor: override?.vendor || model.vendor || builtinProviderVendor[builtinMeta?.id || provider.provider_type] || 'generic',
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
        vendor: override?.vendor || detectVendorForTest(modelId, provider.services?.chat?.base_url || provider.base_url),
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
          vendor: override?.vendor || detectVendorForTest(modelId, provider.services?.chat?.base_url || provider.base_url),
          hidden: Boolean(override?.hidden),
          preferred: Boolean(override?.preferred),
          capabilities,
          limits: { ...customBaseLimits, ...(override?.limits || {}) },
          input_modalities: override?.input_modalities || modalities.input,
          output_modalities: override?.output_modalities || modalities.output,
          provider_options_example: override?.provider_options_example || customProviderOptions,
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
    const baseBuiltinMeta =
      provider.provider_type === 'custom'
        ? undefined
        : providerRegistry.providers.find((item: any) => item.id === provider.provider_type);
    const selectedPlan = baseBuiltinMeta?.plans?.find((plan: any) => plan.id === provider.provider_plan);
    const builtinMeta = selectedPlan
      ? {
          ...baseBuiltinMeta,
          default_model: selectedPlan.default_model || baseBuiltinMeta.default_model,
          default_classify_model: selectedPlan.default_classify_model || baseBuiltinMeta.default_classify_model,
          default_base_url: selectedPlan.default_base_url || baseBuiltinMeta.default_base_url,
          chat_models: selectedPlan.chat_models ?? baseBuiltinMeta.chat_models,
          embedding_models: selectedPlan.embedding_models ?? baseBuiltinMeta.embedding_models,
          image_generation_models: selectedPlan.image_generation_models ?? baseBuiltinMeta.image_generation_models,
        }
      : baseBuiltinMeta;
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
      default_base_url: provider.services?.chat?.base_url || builtinMeta?.default_base_url || '',
      provider_plan: provider.provider_plan || null,
      plans: baseBuiltinMeta?.plans || [],
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
        services: providers[providerMeta.id]?.services || {
          chat: { enabled: true, api_key: '', base_url: providerMeta.default_base_url || '' },
          embedding: { enabled: Boolean(providerMeta.embedding_models?.length), api_key: '', base_url: providerMeta.default_base_url || '' },
          image_generation: {
            enabled: Boolean(providerMeta.image_generation_models?.length),
            api_key: '',
            base_url: providerMeta.default_base_url || '',
            timeout: 180,
            native_protocol: null,
          },
          tts: { enabled: false, api_key: '', base_url: providerMeta.default_base_url || '', model: '', voice: '', response_format: '' },
        },
        api_format: providers[providerMeta.id]?.api_format,
        provider_plan: providers[providerMeta.id]?.provider_plan || null,
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
        services: {
          chat: { enabled: true, api_key: 'sk-openai', base_url: 'https://api.openai.com/v1' },
          embedding: { enabled: true, api_key: 'sk-openai', base_url: 'https://api.openai.com/v1' },
          image_generation: { enabled: true, api_key: 'sk-image-openai', base_url: 'https://api.openai.com/v1', timeout: 180, native_protocol: 'openai_images' },
          tts: { enabled: false, api_key: '', base_url: 'https://api.openai.com/v1', model: '', voice: '', response_format: '' },
        },
      },
      anthropic: {
        enabled: false,
        provider_type: 'anthropic',
        display_name: 'Anthropic',
        api_key: '',
        base_url: 'https://api.anthropic.com/v1',
        services: {
          chat: { enabled: true, api_key: '', base_url: 'https://api.anthropic.com/v1' },
          embedding: { enabled: false, api_key: '', base_url: 'https://api.anthropic.com/v1' },
          image_generation: { enabled: false, api_key: '', base_url: 'https://api.anthropic.com/v1', timeout: 180, native_protocol: null },
          tts: { enabled: false, api_key: '', base_url: 'https://api.anthropic.com/v1', model: '', voice: '', response_format: '' },
        },
      },
      glm: {
        enabled: true,
        provider_type: 'glm',
        display_name: 'Z.ai',
        api_key: 'sk-glm',
        base_url: 'https://open.bigmodel.cn/api/paas/v4',
        services: {
          chat: { enabled: true, api_key: 'sk-glm', base_url: 'https://open.bigmodel.cn/api/paas/v4' },
          embedding: { enabled: true, api_key: 'sk-glm', base_url: 'https://open.bigmodel.cn/api/paas/v4' },
          image_generation: { enabled: false, api_key: '', base_url: 'https://open.bigmodel.cn/api/paas/v4', timeout: 180, native_protocol: null },
          tts: { enabled: false, api_key: '', base_url: 'https://open.bigmodel.cn/api/paas/v4', model: '', voice: '', response_format: '' },
        },
      },
      grok: {
        enabled: false,
        provider_type: 'grok',
        display_name: 'xAI Grok',
        api_key: '',
        base_url: 'https://api.x.ai/v1',
        services: {
          chat: { enabled: true, api_key: '', base_url: 'https://api.x.ai/v1' },
          embedding: { enabled: false, api_key: '', base_url: 'https://api.x.ai/v1' },
          image_generation: { enabled: false, api_key: '', base_url: 'https://api.x.ai/v1', timeout: 180, native_protocol: null },
          tts: { enabled: false, api_key: '', base_url: 'https://api.x.ai/v1', model: '', voice: '', response_format: '' },
        },
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
      memory_summarizer: {
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
      image_generation: {
        provider_id: 'openai',
        model: 'gpt-image-1',
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

  it('renders the configured builtin providers with local icons in the provider list', async () => {
    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode={false} surface="settings" view="providers" showSectionIntro={false} />
      </Form>
    );

    const providerList = await screen.findByTestId('llm-provider-list-pane');

    expect(within(providerList).getByTestId('llm-provider-row-openai')).toHaveTextContent('OpenAI');
    expect(within(providerList).getByTestId('llm-provider-row-anthropic')).toHaveTextContent('Anthropic');
    expect(within(providerList).getByTestId('llm-provider-row-glm')).toHaveTextContent('Z.ai');
    expect(within(providerList).getByTestId('llm-provider-row-grok')).toHaveTextContent('xAI Grok');
    expect(within(providerList).getByTestId('llm-provider-icon-openai')).toBeInTheDocument();
    expect(within(providerList).getByTestId('llm-provider-icon-anthropic')).toBeInTheDocument();
    expect(within(providerList).getByTestId('llm-provider-icon-zai')).toBeInTheDocument();
    expect(within(providerList).getByTestId('llm-provider-icon-grok')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'llm.providerConfiguration.addProvider' })).toBeInTheDocument();
  });

  it('does not show provider type subtitles in the settings provider list', async () => {
    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode={false} surface="settings" view="providers" showSectionIntro={false} />
      </Form>
    );

    const providerList = await screen.findByTestId('llm-provider-list-pane');
    const openAiRow = within(providerList).getByTestId('llm-provider-row-openai');

    expect(openAiRow).toHaveTextContent('OpenAI');
    expect(openAiRow.textContent?.match(/OpenAI/g) ?? []).toHaveLength(1);
  });

  it('normalizes custom providers when custom provider metadata is absent', () => {
    const registry = buildRegistryFromCatalog({ providers: [] }, {} as any);
    const customValue = structuredClone(llmValue) as LLMConfig;
    customValue.providers = {
      custom_proxy: {
        ...structuredClone(llmValue.providers.openai),
        provider_type: 'custom',
        display_name: 'Custom Proxy',
        custom_models: [],
        custom_default_model: 'manual-model',
        api_format: 'openai',
        model_metadata_overrides: {},
      },
    };
    customValue.selections.context_decider = {
      ...structuredClone(llmValue.selections.context_decider),
      provider_id: 'custom_proxy',
      model: 'manual-model',
    };
    customValue.selections.core = {
      ...structuredClone(llmValue.selections.core),
      provider_id: 'custom_proxy',
      model: 'manual-model',
    };
    customValue.selections.memory_summarizer = {
      ...structuredClone(llmValue.selections.memory_summarizer),
      provider_id: 'custom_proxy',
      model: 'manual-model',
    };

    const normalized = normalizeLLMConfig(customValue, registry);

    expect(normalized.selections.core.capabilities.tool_calling).toBe(true);
    expect(normalized.selections.core.capabilities.reasoning).toBe(true);
  });

  it('keeps chat plans out of background model assignments', async () => {
    const planValue = structuredClone(llmValue) as LLMConfig;
    planValue.providers.glm.provider_plan = 'codeplan';
    planValue.selections.core = {
      ...structuredClone(planValue.selections.core),
      provider_id: 'glm',
      model: 'glm-5',
    };
    planValue.selections.memory_summarizer = {
      ...structuredClone(planValue.selections.memory_summarizer),
      provider_id: 'glm',
      model: 'glm-5',
    };
    const catalog = await configApi.resolveLLMProviderCatalog({ providers: planValue.providers });
    const registry = buildRegistryFromCatalog(catalog, null);

    const normalized = normalizeLLMConfig(planValue, registry);

    expect(normalized.selections.core.provider_id).toBe('glm');
    expect(normalized.selections.memory_summarizer.provider_id).toBe('openai');
  });

  it('pins enabled providers above disabled providers in the settings provider list', async () => {
    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode={false} surface="settings" view="providers" showSectionIntro={false} />
      </Form>
    );

    const providerList = await screen.findByTestId('llm-provider-list-pane');
    const openAiButton = within(providerList).getByTestId('llm-provider-row-openai');
    const zaiButton = within(providerList).getByTestId('llm-provider-row-glm');
    const anthropicButton = within(providerList).getByTestId('llm-provider-row-anthropic');

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

  it('uses a switch control for provider enablement in the provider list', async () => {
    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode />
      </Form>
    );

    const providerRow = await screen.findByTestId('llm-provider-row-openai');

    expect(within(providerRow).getByRole('switch', { name: 'llm.fields.enabled' })).toBeInTheDocument();
  });

  it('does not prefill default base url for inactive built-in providers', async () => {
    const user = userEvent.setup();
    const valueWithoutAnthropicBaseUrl = {
      ...llmValue,
      providers: {
        ...llmValue.providers,
        anthropic: {
          ...llmValue.providers.anthropic,
          services: {
            ...llmValue.providers.anthropic.services,
            chat: {
              ...llmValue.providers.anthropic.services.chat,
              base_url: '',
            },
          },
        },
      },
    };

    render(
      <Form initialValues={{ llm: valueWithoutAnthropicBaseUrl }}>
        <LLMForm quickMode />
      </Form>
    );

    const providerRow = await screen.findByTestId('llm-provider-row-anthropic');
    await user.click(within(providerRow).getByRole('button', { name: 'llm.providerConfiguration.editProvider' }));
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: /llm.providerConfiguration.serviceLabels.chat/ }));

    expect(within(dialog).getByLabelText('llm.providerConfiguration.serviceLabels.chat llm.fields.baseUrl')).toHaveValue('');
  });

  it('shows image generation connection fields in the provider editor', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode={false} surface="settings" view="providers" showSectionIntro={false} />
      </Form>
    );

    const providerRow = await screen.findByTestId('llm-provider-row-openai');
    await user.click(within(providerRow).getByRole('button', { name: 'llm.providerConfiguration.editProvider' }));
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: /llm.providerConfiguration.serviceLabels.image_generation/ }));

    expect(within(dialog).getByLabelText('llm.providerConfiguration.serviceLabels.image_generation llm.fields.apiKey')).toBeInTheDocument();
    expect(within(dialog).getByLabelText('llm.providerConfiguration.serviceLabels.image_generation llm.fields.baseUrl')).toBeInTheDocument();
    expect(within(dialog).getByLabelText('llm.imageGenerationConnection.timeout')).toHaveValue(180);
  });

  it('keeps expanded service configuration visible when the service is disabled', async () => {
    const user = userEvent.setup();
    const valueWithDisabledEmbedding = {
      ...llmValue,
      providers: {
        ...llmValue.providers,
        openai: {
          ...llmValue.providers.openai,
          services: {
            ...llmValue.providers.openai.services,
            embedding: {
              ...llmValue.providers.openai.services.embedding,
              enabled: false,
            },
          },
        },
      },
    };

    render(
      <Form initialValues={{ llm: valueWithDisabledEmbedding }}>
        <LLMForm quickMode={false} surface="settings" view="providers" showSectionIntro={false} />
      </Form>
    );

    const providerRow = await screen.findByTestId('llm-provider-row-openai');
    await user.click(within(providerRow).getByRole('button', { name: 'llm.providerConfiguration.editProvider' }));
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: /llm.providerConfiguration.serviceLabels.embedding/ }));

    expect(within(dialog).getByRole('switch', { name: 'llm.providerConfiguration.serviceLabels.embedding' })).not.toBeChecked();
    expect(within(dialog).getByLabelText('llm.providerConfiguration.serviceLabels.embedding llm.fields.apiKey')).toBeInTheDocument();
    expect(within(dialog).getByLabelText('llm.providerConfiguration.serviceLabels.embedding llm.fields.baseUrl')).toBeInTheDocument();
    expect(within(dialog).getAllByText('Text Embedding 3 Small').length).toBeGreaterThan(0);
    expect(within(dialog).getByTestId('llm-provider-model-editor')).toBeInTheDocument();
  });

  it('shows provider-level connection defaults, inherited service placeholders, models, and test controls', async () => {
    const user = userEvent.setup();
    const inheritedConnectionValue = {
      ...llmValue,
      providers: {
        ...llmValue.providers,
        openai: {
          ...llmValue.providers.openai,
          services: {
            ...llmValue.providers.openai.services,
            chat: {
              ...llmValue.providers.openai.services.chat,
              api_key: '',
              base_url: '',
            },
          },
        },
      },
    };

    render(
      <Form initialValues={{ llm: inheritedConnectionValue }}>
        <LLMForm quickMode={false} surface="settings" view="providers" showSectionIntro={false} />
      </Form>
    );

    const providerRow = await screen.findByTestId('llm-provider-row-openai');
    await user.click(within(providerRow).getByRole('button', { name: 'llm.providerConfiguration.editProvider' }));
    const dialog = screen.getByRole('dialog');

    const providerApiKeyField = within(dialog)
      .getAllByLabelText(/llm.fields.apiKey/)
      .find((field) => field.getAttribute('aria-label') === 'llm.fields.apiKey');
    const providerBaseUrlField = within(dialog)
      .getAllByLabelText(/llm.fields.baseUrl/)
      .find((field) => field.getAttribute('aria-label') === 'llm.fields.baseUrl');

    expect(providerApiKeyField).toHaveValue('sk-openai');
    expect(providerBaseUrlField).toHaveValue('https://api.openai.com/v1');
    expect(within(dialog).queryByLabelText('llm.providerConfiguration.serviceLabels.chat llm.fields.apiKey')).not.toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: /llm.providerConfiguration.serviceLabels.chat/ }));

    expect(within(dialog).getByLabelText('llm.providerConfiguration.serviceLabels.chat llm.fields.apiKey')).toHaveAttribute(
      'placeholder',
      'llm.providerConfiguration.inheritApiKeyPlaceholder'
    );
    expect(within(dialog).getByLabelText('llm.providerConfiguration.serviceLabels.chat llm.fields.baseUrl')).toHaveAttribute(
      'placeholder',
      'llm.providerConfiguration.inheritBaseUrlPlaceholder'
    );
    expect(within(dialog).queryByText('llm.providerConfiguration.serviceLabels.tts')).not.toBeInTheDocument();
    expect(within(dialog).getByTestId('llm-provider-model-list-pane')).toBeInTheDocument();
    expect(within(dialog).getByTestId('llm-provider-model-editor')).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: 'llm.actions.testConnection' }));
    expect(within(dialog).getByText('llm.providerConfiguration.testTitle')).toBeInTheDocument();
    expect(within(dialog).getByLabelText('llm.providerConfiguration.testModelLabel')).toBeInTheDocument();

    await user.click(within(dialog).getByText('llm.providerConfiguration.servicesTitle'));
    expect(within(dialog).queryByText('llm.providerConfiguration.testTitle')).not.toBeInTheDocument();
  });

  it('refreshes service model content after switching provider templates in the add dialog', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode={false} surface="settings" view="providers" showSectionIntro={false} />
      </Form>
    );

    await user.click(await screen.findByRole('button', { name: 'llm.providerConfiguration.addProvider' }));
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Z.ai' }));
    await user.click(within(dialog).getByRole('button', { name: /llm.providerConfiguration.serviceLabels.chat/ }));

    const providerBaseUrlField = within(dialog)
      .getAllByLabelText(/llm.fields.baseUrl/)
      .find((field) => field.getAttribute('aria-label') === 'llm.fields.baseUrl');

    expect(providerBaseUrlField).toHaveValue('https://open.bigmodel.cn/api/paas/v4');
    expect(within(dialog).getByLabelText('llm.providerConfiguration.serviceLabels.chat llm.fields.baseUrl')).toHaveAttribute(
      'placeholder',
      'llm.providerConfiguration.inheritBaseUrlPlaceholder'
    );
    expect(within(dialog).getAllByText('GLM-5').length).toBeGreaterThan(0);
    expect(within(dialog).queryByText('GPT-5')).not.toBeInTheDocument();
  });

  it('defaults image generation to disabled when adding a template provider', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode={false} surface="settings" view="providers" showSectionIntro={false} />
      </Form>
    );

    await user.click(await screen.findByRole('button', { name: 'llm.providerConfiguration.addProvider' }));
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'OpenAI' }));

    expect(within(dialog).getByRole('switch', { name: 'llm.providerConfiguration.serviceLabels.chat' })).toBeChecked();
    expect(within(dialog).getByRole('switch', { name: 'llm.providerConfiguration.serviceLabels.embedding' })).toBeChecked();
    expect(within(dialog).getByRole('switch', { name: 'llm.providerConfiguration.serviceLabels.image_generation' })).not.toBeChecked();
  });

  it('renders fetched draft models immediately after discover succeeds', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode={false} surface="settings" view="providers" showSectionIntro={false} />
      </Form>
    );

    await user.click(await screen.findByRole('button', { name: 'llm.providerConfiguration.addProvider' }));
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'llm.providerConfiguration.providerKinds.custom' }));
    await user.click(within(dialog).getByRole('button', { name: 'llm.actions.fetchModels' }));

    await waitFor(() => {
      expect(within(dialog).getByRole('button', { name: /fetched-model-1/ })).toBeInTheDocument();
      expect(within(dialog).getByRole('button', { name: /fetched-model-2/ })).toBeInTheDocument();
    });
  });

  it('previews inferred vendor for draft models before the provider is saved', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode={false} surface="settings" view="providers" showSectionIntro={false} />
      </Form>
    );

    await user.click(await screen.findByRole('button', { name: 'llm.providerConfiguration.addProvider' }));
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'llm.providerConfiguration.providerKinds.custom' }));

    const customModelsField = within(dialog).getByLabelText('llm.providerConfiguration.serviceLabels.chat llm.fields.modelManualEntry');
    await user.type(customModelsField, 'claude-sonnet-4-6');
    await user.click(within(dialog).getByRole('button', { name: 'llm.actions.addModel' }));

    await waitFor(() => {
      expect(within(dialog).getByLabelText('llm.modelFields.vendor')).toHaveTextContent('llm.modelFields.vendorOptions.anthropic');
    });
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

  it('shows a memory summarizer tab for expert onboarding model selection', async () => {
    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode={false} view="models" showSectionIntro={false} />
      </Form>
    );

    expect(
      await screen.findByRole('tab', { name: 'llm.scenarios.memory_summarizer.title' })
    ).toBeInTheDocument();
  });

  it('keeps the memory summarizer tab hidden for quick onboarding model selection', async () => {
    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode view="models" showSectionIntro={false} />
      </Form>
    );

    await screen.findByTestId('llm-scenario-core');

    expect(screen.queryByRole('tab', { name: 'llm.scenarios.memory_summarizer.title' })).not.toBeInTheDocument();
  });

  it('uses an off local mode selector for reranker model selection', async () => {
    const user = userEvent.setup();

    const rerankerModels = [
      {
        id: 'bge-reranker-v2',
        label: 'BGE Reranker v2',
        repo: 'BAAI/bge-reranker-v2-m3',
        max_tokens: 512,
        size_mb: 438,
        languages: ['zh', 'en'],
        recommended: true,
        description: 'Managed local reranker model.',
        downloaded: false,
        download_in_progress: false,
        download_progress_pct: null,
        variants: [],
        default_variant: null,
      },
    ];

    const RerankerPanelHarness = () => {
      const [config, setConfig] = React.useState({ enabled: false, managed_model_id: null as string | null, variant: null as string | null });

      return (
        <LLMRerankerModelPanel
          crossEncoderConfig={config}
          onCrossEncoderConfigChange={(updater) => setConfig((current) => {
            const next = { ...current };
            updater(next);
            return next;
          })}
          inputClassName="h-11"
          rerankerModels={rerankerModels}
          rerankerDownloadingId={null}
          rerankerDownloadProgress={null}
          rerankerDownloadError={null}
          onRerankerDownload={vi.fn()}
          onRerankerDelete={vi.fn()}
        />
      );
    };

    render(<RerankerPanelHarness />);

    expect(screen.queryByLabelText('settings.memory.fields.reranker_model.label')).not.toBeInTheDocument();

    await user.click(screen.getByLabelText('settings.memory.fields.reranker_mode.label'));
    expect(screen.queryByRole('button', { name: 'settings.options.remote' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'settings.options.local' }));

    expect(screen.getByLabelText('settings.memory.fields.reranker_model.label')).toBeInTheDocument();
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
          services: {
            chat: { enabled: true, api_key: 'sk-proxy', base_url: 'https://proxy.example.com/v1' },
            embedding: { enabled: false, api_key: '', base_url: 'https://proxy.example.com/v1' },
            image_generation: { enabled: false, api_key: '', base_url: 'https://proxy.example.com/v1', timeout: 180, native_protocol: null },
            tts: { enabled: false, api_key: '', base_url: 'https://proxy.example.com/v1', model: '', voice: '', response_format: '' },
          },
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
          services: {
            chat: { enabled: true, api_key: 'sk-zen', base_url: 'https://proxy.example.com/v1' },
            embedding: { enabled: false, api_key: '', base_url: 'https://proxy.example.com/v1' },
            image_generation: { enabled: false, api_key: '', base_url: 'https://proxy.example.com/v1', timeout: 180, native_protocol: null },
            tts: { enabled: false, api_key: '', base_url: 'https://proxy.example.com/v1', model: '', voice: '', response_format: '' },
          },
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
        services: {
          chat: { enabled: true, api_key: '', base_url: '' },
          embedding: { enabled: false, api_key: '', base_url: '' },
          image_generation: { enabled: false, api_key: '', base_url: '', timeout: 180, native_protocol: null },
          tts: { enabled: false, api_key: '', base_url: '', model: '', voice: '', response_format: '' },
        },
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
          services: {
            chat: { enabled: true, api_key: 'sk-openai', base_url: 'https://api.openai.com/v1' },
            embedding: { enabled: false, api_key: '', base_url: 'https://api.openai.com/v1' },
            image_generation: { enabled: false, api_key: '', base_url: 'https://api.openai.com/v1', timeout: 180, native_protocol: null },
            tts: { enabled: false, api_key: '', base_url: 'https://api.openai.com/v1', model: '', voice: '', response_format: '' },
          },
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
    fireEvent.change(maxConcurrencyField, { target: { value: '9' } });

    await waitFor(() => {
      const savedOverrides = onChange.mock.calls.flatMap(([nextValue]) =>
        Object.entries(nextValue?.model_runtime_overrides ?? {})
      );
      expect(savedOverrides).toContainEqual([
        'openai::openai::api::api.openai.com::gpt-5.2::chat',
        { max_concurrency: 9 },
      ]);
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

    expect(await screen.findByText('llm.providerConfiguration.title')).toBeInTheDocument();
    expect(screen.getByText('llm.providerConfiguration.emptyTitle')).toBeInTheDocument();

    const latest = onChange.mock.calls[onChange.mock.calls.length - 1]?.[0] ?? blankValue;

    expect(latest.providers).toEqual({});
    expect(latest.selections.context_decider.provider_id).toBe('');
    expect(latest.selections.context_decider.model).toBe('');
    expect(latest.selections.core.provider_id).toBe('');
    expect(latest.selections.core.model).toBe('');
  });

  it('adds a provider instance from a built-in template', async () => {
    const user = userEvent.setup();
    let latestValue: LLMConfig | null = null;

    function ControlledSettingsLlmForm() {
      const [value, setValue] = React.useState({ providers: {}, selections: llmValue.selections, model_runtime_overrides: {} } as unknown as LLMConfig);
      return (
        <LLMForm
          quickMode={false}
          surface="settings"
          view="providers"
          showSectionIntro={false}
          value={value}
          onChange={(nextValue) => {
            latestValue = nextValue;
            setValue(nextValue);
          }}
        />
      );
    }

    render(<ControlledSettingsLlmForm />);

    await user.click(await screen.findByRole('button', { name: 'llm.providerConfiguration.addProvider' }));
    const dialog = screen.getByRole('dialog');
    await user.type(within(dialog).getByLabelText('llm.fields.apiKey'), 'sk-new-openai');
    await user.click(screen.getByRole('button', { name: 'llm.providerConfiguration.saveProvider' }));

    await waitFor(() => {
      expect(Object.values(latestValue?.providers || {}).some(
        (provider) => provider.provider_type === 'openai' && provider.api_key === 'sk-new-openai'
      )).toBe(true);
    });
  });

  it('adds a custom provider with chat models from the provider dialog', async () => {
    const user = userEvent.setup();
    let latestValue: LLMConfig | null = null;

    function ControlledSettingsLlmForm() {
      const [value, setValue] = React.useState({ providers: {}, selections: llmValue.selections, model_runtime_overrides: {} } as unknown as LLMConfig);
      return (
        <LLMForm
          quickMode={false}
          surface="settings"
          view="providers"
          showSectionIntro={false}
          value={value}
          onChange={(nextValue) => {
            latestValue = nextValue;
            setValue(nextValue);
          }}
        />
      );
    }

    render(<ControlledSettingsLlmForm />);

    await user.click(await screen.findByRole('button', { name: 'llm.providerConfiguration.addProvider' }));
    await user.click(screen.getByRole('button', { name: 'llm.providerConfiguration.providerKinds.custom' }));
    const dialog = screen.getByRole('dialog');
    await user.clear(screen.getByLabelText('llm.fields.displayName'));
    await user.type(screen.getByLabelText('llm.fields.displayName'), 'Proxy');
    const providerApiKeyField = within(dialog)
      .getAllByLabelText(/llm.fields.apiKey/)
      .find((field) => field.getAttribute('aria-label') === 'llm.fields.apiKey');
    await user.type(providerApiKeyField!, 'sk-proxy');
    const providerBaseUrlField = within(dialog)
      .getAllByLabelText(/llm.fields.baseUrl/)
      .find((field) => field.getAttribute('aria-label') === 'llm.fields.baseUrl');
    await user.type(providerBaseUrlField!, 'https://proxy.example.com/v1');
    const customModelsField = within(dialog).getByLabelText('llm.providerConfiguration.serviceLabels.chat llm.fields.modelManualEntry');
    await user.type(customModelsField, 'foo-1');
    await user.click(within(dialog).getByRole('button', { name: 'llm.actions.addModel' }));
    await user.type(customModelsField, 'foo-2');
    await user.click(within(dialog).getByRole('button', { name: 'llm.actions.addModel' }));
    await user.click(screen.getByRole('button', { name: 'llm.providerConfiguration.saveProvider' }));

    await waitFor(() => {
      expect(Object.values(latestValue?.providers || {}).some(
        (provider) =>
          provider.provider_type === 'custom' &&
          provider.display_name === 'Proxy' &&
          provider.base_url === 'https://proxy.example.com/v1' &&
          provider.custom_models?.includes('foo-1') &&
          provider.custom_models?.includes('foo-2')
      )).toBe(true);
    });
  });

  it('disables custom provider save until enabled services have models', async () => {
    const user = userEvent.setup();

    function ControlledSettingsLlmForm() {
      const [value, setValue] = React.useState({ providers: {}, selections: llmValue.selections, model_runtime_overrides: {} } as unknown as LLMConfig);
      return (
        <LLMForm
          quickMode={false}
          surface="settings"
          view="providers"
          showSectionIntro={false}
          value={value}
          onChange={setValue}
        />
      );
    }

    render(<ControlledSettingsLlmForm />);

    await user.click(await screen.findByRole('button', { name: 'llm.providerConfiguration.addProvider' }));
    await user.click(screen.getByRole('button', { name: 'llm.providerConfiguration.providerKinds.custom' }));
    const dialog = screen.getByRole('dialog');
    const saveButton = within(dialog).getByRole('button', { name: 'llm.providerConfiguration.saveProvider' });

    expect(saveButton).toBeDisabled();
    expect(within(dialog).getAllByText('llm.validation.customServiceModelRequired').length).toBeGreaterThan(0);

    const customModelsField = within(dialog).getByLabelText('llm.providerConfiguration.serviceLabels.chat llm.fields.modelManualEntry');
    await user.type(customModelsField, 'foo-1');
    await user.click(within(dialog).getByRole('button', { name: 'llm.actions.addModel' }));

    await waitFor(() => {
      expect(saveButton).toBeEnabled();
    });
  });

  it('lets custom providers add manual image generation models', async () => {
    const user = userEvent.setup();
    let latestValue: LLMConfig | null = null;

    function ControlledSettingsLlmForm() {
      const [value, setValue] = React.useState({ providers: {}, selections: llmValue.selections, model_runtime_overrides: {} } as unknown as LLMConfig);
      return (
        <LLMForm
          quickMode={false}
          surface="settings"
          view="providers"
          showSectionIntro={false}
          value={value}
          onChange={(nextValue) => {
            latestValue = nextValue;
            setValue(nextValue);
          }}
        />
      );
    }

    render(<ControlledSettingsLlmForm />);

    await user.click(await screen.findByRole('button', { name: 'llm.providerConfiguration.addProvider' }));
    await user.click(screen.getByRole('button', { name: 'llm.providerConfiguration.providerKinds.custom' }));
    const dialog = screen.getByRole('dialog');
    await user.type(within(dialog).getByLabelText('llm.providerConfiguration.serviceLabels.chat llm.fields.modelManualEntry'), 'foo-chat');
    await user.click(within(dialog).getByRole('button', { name: 'llm.actions.addModel' }));

    await user.click(within(dialog).getByRole('switch', { name: 'llm.providerConfiguration.serviceLabels.image_generation' }));
    const saveButton = within(dialog).getByRole('button', { name: 'llm.providerConfiguration.saveProvider' });
    expect(saveButton).toBeDisabled();

    const imageModelField = within(dialog).getByLabelText('llm.providerConfiguration.serviceLabels.image_generation llm.fields.modelManualEntry');
    await user.type(imageModelField, 'foo-image');
    const addModelButtons = within(dialog).getAllByRole('button', { name: 'llm.actions.addModel' });
    await user.click(addModelButtons[addModelButtons.length - 1]);
    await waitFor(() => {
      expect(saveButton).toBeEnabled();
    });
    await user.click(saveButton);

    await waitFor(() => {
      const provider = Object.values(latestValue?.providers || {}).find((item) => item.provider_type === 'custom');
      expect(provider?.model_metadata_overrides?.['foo-image']?.capabilities?.image_output).toBe(true);
    });
  });

  it('uses provider-native image models without a manual image model entry', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode={false} surface="settings" view="models" showSectionIntro={false} />
      </Form>
    );

    await user.click(await screen.findByRole('tab', { name: 'llm.scenarios.image_generation.title' }));
    const imagePanel = screen.getByTestId('llm-scenario-image_generation');
    expect(within(imagePanel).getByLabelText('llm.fields.provider')).toHaveTextContent('OpenAI');
    expect(within(imagePanel).getByLabelText('llm.fields.model')).toHaveTextContent('GPT Image 1');
    expect(screen.queryByLabelText('llm.fields.modelManualEntry')).not.toBeInTheDocument();
  });

  it('lets users reveal and hide provider api keys locally', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode={false} surface="settings" view="providers" showSectionIntro={false} />
      </Form>
    );

    const providerRow = await screen.findByTestId('llm-provider-row-openai');
    await user.click(within(providerRow).getByRole('button', { name: 'llm.providerConfiguration.editProvider' }));

    const dialog = screen.getByRole('dialog');
    const apiKeyField = await within(dialog).findByLabelText('llm.fields.apiKey');
    const fieldWrapper = apiKeyField.parentElement?.parentElement;

    expect(apiKeyField).toHaveAttribute('type', 'password');

    const toggleButton = within(fieldWrapper as HTMLElement).getByRole('button');
    await user.click(toggleButton);
    expect(apiKeyField).toHaveAttribute('type', 'text');

    await user.click(toggleButton);
    expect(apiKeyField).toHaveAttribute('type', 'password');
  });

  it('shows the registry default base url as the placeholder for a blank built-in provider service', async () => {
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
          services: {
            ...llmValue.providers.glm.services,
            chat: {
              ...llmValue.providers.glm.services.chat,
              base_url: '',
            },
          },
        },
      },
    };

    render(
      <Form initialValues={{ llm: glmWithoutBaseUrl }}>
        <LLMForm quickMode />
      </Form>
    );

    const providerList = await screen.findByTestId('llm-provider-list-pane');
    const providerRow = within(providerList).getByTestId('llm-provider-row-glm');
    await user.click(within(providerRow).getByRole('button', { name: 'llm.providerConfiguration.editProvider' }));
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: /llm.providerConfiguration.serviceLabels.chat/ }));

    expect(within(dialog).getByLabelText('llm.providerConfiguration.serviceLabels.chat llm.fields.baseUrl')).toHaveAttribute(
      'placeholder',
      'llm.providerConfiguration.inheritBaseUrlPlaceholder'
    );
  });

  it('fills and switches provider plan endpoint base urls in settings', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode={false} surface="settings" view="providers" showSectionIntro={false} />
      </Form>
    );

    const providerRow = await screen.findByTestId('llm-provider-row-glm');
    await user.click(within(providerRow).getByRole('button', { name: 'llm.providerConfiguration.editProvider' }));

    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByText('llm.providerPlans.default'));
    fireEvent.click(await screen.findByRole('button', { name: 'Z.ai CodePlan' }));
    expect(within(dialog).getByText('llm.providerPlans.backgroundNotice')).toBeInTheDocument();
    expect(within(dialog).getByLabelText('llm.fields.baseUrl')).toHaveValue(
      'https://open.bigmodel.cn/api/coding/paas/v4'
    );

    await user.click(within(dialog).getByText('China'));
    fireEvent.click(await screen.findByRole('button', { name: 'Global' }));
    expect(within(dialog).getByLabelText('llm.fields.baseUrl')).toHaveValue(
      'https://api.z.ai/api/coding/paas/v4'
    );
  });

});
