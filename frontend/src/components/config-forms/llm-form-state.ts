import {
  DEFAULT_LLM_CAPABILITIES,
  DEFAULT_LLM_LIMITS,
  type LLMCapabilities,
  type LLMConcurrencyOverrideConfig,
  type LLMConfig,
  type LLMCustomProviderTemplateData,
  type LLMLimits,
  type LLMProviderConfig,
  type LLMProviderCatalog,
  type LLMProviderRegistry,
  type LLMScenario,
  type LLMSelectionConfig,
  resolveProviderModels,
} from '@/api/modules/config';

export const BUILTIN_SCENARIOS: LLMScenario[] = ['context_decider', 'core', 'memory_summarizer', 'embedding', 'image_generation'];

export interface ScenarioConcurrencyState {
  runtimeKey: string | null;
  effectiveMaxConcurrency: number | null;
  overrideMaxConcurrency: number | null;
  defaultMaxConcurrency: number | null;
  sharedScenarios: LLMScenario[];
}

const cloneCapabilities = (value?: Partial<LLMCapabilities>): LLMCapabilities => ({
  ...DEFAULT_LLM_CAPABILITIES,
  ...(value || {}),
});

const cloneLimits = (value?: Partial<LLMLimits>): LLMLimits => ({
  ...DEFAULT_LLM_LIMITS,
  ...(value || {}),
});

const cloneRuntimeOverride = (
  value?: Partial<LLMConcurrencyOverrideConfig>
): LLMConcurrencyOverrideConfig => ({
  max_concurrency: value?.max_concurrency ?? null,
});

export const cloneProvider = (value?: Partial<LLMProviderConfig>): LLMProviderConfig => ({
  enabled: Boolean(value?.enabled),
  provider_type: value?.provider_type || 'openai',
  display_name: value?.display_name || '',
  api_key: value?.api_key || '',
  base_url: value?.base_url || '',
  api_format: value?.api_format,
  custom_models: [...(value?.custom_models || [])],
  custom_default_model: value?.custom_default_model || '',
  model_metadata_overrides: Object.fromEntries(
    Object.entries(value?.model_metadata_overrides || {}).map(([modelId, override]) => [
      modelId,
      {
        ...(override || {}),
        capabilities: { ...(override?.capabilities || {}) },
        limits: { ...(override?.limits || {}) },
        input_modalities:
          override?.input_modalities === null
            ? null
            : override?.input_modalities
              ? [...override.input_modalities]
              : undefined,
        dimensions:
          override?.dimensions === null
            ? null
            : override?.dimensions
              ? [...override.dimensions]
              : undefined,
        output_modalities:
          override?.output_modalities === null
            ? null
            : override?.output_modalities
              ? [...override.output_modalities]
              : undefined,
        provider_options_example:
          override?.provider_options_example === null
            ? null
            : override?.provider_options_example
              ? { ...override.provider_options_example }
              : undefined,
      },
    ])
  ),
});

export const cloneSelection = (value?: Partial<LLMSelectionConfig>): LLMSelectionConfig => ({
  provider_id: value?.provider_id || '',
  model: value?.model || '',
  embedding_dimension: value?.embedding_dimension ?? null,
  capability_override_enabled: Boolean(value?.capability_override_enabled),
  capabilities: cloneCapabilities(value?.capabilities),
  limits: cloneLimits(value?.limits),
  provider_options: { ...(value?.provider_options || {}) },
});

export const cloneLLMConfig = (value?: LLMConfig): LLMConfig => ({
  providers: Object.fromEntries(
    Object.entries(value?.providers || {}).map(([providerId, provider]) => [providerId, cloneProvider(provider)])
  ),
  selections: {
    context_decider: cloneSelection(value?.selections?.context_decider),
    core: cloneSelection(value?.selections?.core),
    memory_summarizer: cloneSelection(value?.selections?.memory_summarizer ?? value?.selections?.core),
    embedding: cloneSelection(value?.selections?.embedding),
    image_generation: cloneSelection(value?.selections?.image_generation),
  },
  model_runtime_overrides: Object.fromEntries(
    Object.entries(value?.model_runtime_overrides || {}).map(([runtimeKey, limits]) => [
      runtimeKey,
      cloneRuntimeOverride(limits),
    ])
  ),
});

export const llmSignature = (value: LLMConfig): string => JSON.stringify(value);

export const buildRegistryFromCatalog = (
  catalog: LLMProviderCatalog,
  customTemplate: LLMCustomProviderTemplateData
): LLMProviderRegistry => ({
  providers: catalog.providers,
  custom_provider: customTemplate.template,
});

const getProviderMeta = (registry: LLMProviderRegistry, providerId?: string) =>
  registry.providers.find((provider) => provider.id === providerId);

const getResolvedProviderModels = (
  registry: LLMProviderRegistry,
  providerId: string,
  provider?: LLMProviderConfig
) => resolveProviderModels(registry, providerId, provider);

export const resolveProviderActionBaseUrl = (
  registry: LLMProviderRegistry,
  providerId: string,
  provider: LLMProviderConfig | undefined
): string => {
  const configured = (provider?.base_url || '').trim();
  if (configured) {
    return configured;
  }
  return getProviderMeta(registry, providerId)?.default_base_url || '';
};

const normalizeBaseUrlHost = (value?: string): string | null => {
  const rawValue = (value || '').trim();
  if (!rawValue) {
    return null;
  }

  try {
    const parsed = new URL(rawValue.includes('://') ? rawValue : `https://${rawValue}`);
    return parsed.host.trim().toLowerCase() || null;
  } catch {
    return null;
  }
};

const detectOpenAICompatibleRuntimeProvider = (
  provider: LLMProviderConfig | undefined,
  selectedModel?: string | null
): string => {
  const hintValues = [
    provider?.display_name,
    provider?.base_url,
    provider?.custom_default_model,
    selectedModel,
  ];
  const normalizedHints = hintValues
    .map((value) => String(value || '').trim().toLowerCase())
    .filter(Boolean)
    .join(' ');

  const runtimeProviderHints: Array<[string, string[]]> = [
    ['glm', ['bigmodel.cn', 'z.ai', 'glm-', ' glm']],
    ['deepseek', ['deepseek']],
    ['kimi', ['moonshot', 'kimi']],
    ['minimax', ['minimax']],
    ['gemini', ['gemini', 'generativelanguage.googleapis.com']],
  ];
  for (const [runtimeProvider, markers] of runtimeProviderHints) {
    if (markers.some((marker) => normalizedHints.includes(marker))) {
      return runtimeProvider;
    }
  }
  return 'openai';
};

const resolveRuntimeProviderType = (
  provider: LLMProviderConfig | undefined,
  selectedModel?: string | null
): string => {
  const providerType = String(provider?.provider_type || '').trim().toLowerCase();
  if (providerType && providerType !== 'custom') {
    return providerType;
  }

  const apiFormat = String(provider?.api_format || 'openai').trim().toLowerCase();
  if (apiFormat === 'anthropic') {
    return 'anthropic';
  }
  return detectOpenAICompatibleRuntimeProvider(provider, selectedModel);
};

export const buildRuntimeOverrideKey = ({
  registry,
  providerId,
  provider,
  model,
  scenario,
}: {
  registry: LLMProviderRegistry;
  providerId: string;
  provider: LLMProviderConfig | undefined;
  model: string;
  scenario: LLMScenario;
}): string | null => {
  const normalizedModel = String(model || '').trim().toLowerCase();
  if (!providerId || !provider || !normalizedModel) {
    return null;
  }
  const runtimeProvider = resolveRuntimeProviderType(provider, normalizedModel);
  const baseUrl = resolveProviderActionBaseUrl(registry, providerId, provider);
  const host = normalizeBaseUrlHost(baseUrl) || runtimeProvider;
  const requestFamily = scenario === 'embedding' ? 'embedding' : 'chat';
  return `${runtimeProvider}::${host}::${normalizedModel}::${requestFamily}`;
};

export const resolveSelectionDefaultMaxConcurrency = ({
  registry,
  providerId,
  provider,
  model,
  scenario,
}: {
  registry: LLMProviderRegistry;
  providerId: string;
  provider: LLMProviderConfig | undefined;
  model: string;
  scenario: LLMScenario;
}): number | null => {
  if (!providerId || !provider) {
    return null;
  }

  const resolvedModels = getResolvedProviderModels(registry, providerId, provider);

  if (scenario === 'embedding') {
    const embeddingModel = resolvedModels.embedding_models.find((item) => item.id === model);
    return embeddingModel?.limits?.max_concurrency ?? null;
  }

  const chatModel = resolvedModels.chat_models.find((item) => item.id === model);
  return chatModel?.limits?.max_concurrency ?? null;
};

export const resolveProviderDefaultModel = (
  registry: LLMProviderRegistry,
  providerId: string,
  provider: LLMProviderConfig | undefined,
  scenario: LLMScenario
): string => {
  if (!provider) {
    return '';
  }
  const providerMeta =
    provider.provider_type === 'custom' ? undefined : getProviderMeta(registry, provider.provider_type);
  const resolvedModels = getResolvedProviderModels(registry, providerId, provider);

  if (scenario === 'embedding') {
    return resolvedModels.embedding_models.find((model) => !model.hidden)?.id || '';
  }
  if (scenario === 'image_generation') {
    const imageModels = resolvedModels.image_generation_models.filter((model) => !model.hidden);
    return imageModels[0]?.id || '';
  }
  if (scenario === 'context_decider') {
    return (
      providerMeta?.default_classify_model ||
      providerMeta?.default_model ||
      resolvedModels.chat_models.find((model) => !model.hidden)?.id ||
      ''
    );
  }
  return (
    providerMeta?.default_model ||
    resolvedModels.chat_models.find((model) => !model.hidden)?.id ||
    ''
  );
};

export const applySelectionDefaults = (
  selection: LLMSelectionConfig,
  registry: LLMProviderRegistry,
  providerId: string,
  provider: LLMProviderConfig | undefined,
  scenario?: LLMScenario
) => {
  if (!provider) {
    return;
  }

  const resolvedModels = getResolvedProviderModels(registry, providerId, provider);

  if (scenario === 'embedding') {
    const embeddingModels = resolvedModels.embedding_models.filter((model) => !model.hidden);
    if (embeddingModels.length === 0) {
      selection.provider_id = '';
      selection.model = '';
      selection.embedding_dimension = null;
      return;
    }

    const preferredModelId = selection.model || resolveProviderDefaultModel(registry, providerId, provider, scenario);
    const matchedModel = embeddingModels.find((model) => model.id === preferredModelId);
    const fallbackModel = matchedModel || embeddingModels[0];
    if (fallbackModel) {
      selection.model = fallbackModel.id;
      if (!fallbackModel.dimensions.includes(selection.embedding_dimension || -1)) {
        selection.embedding_dimension = fallbackModel.dimensions[0] ?? null;
      }
      if (!selection.capability_override_enabled) {
        selection.capabilities = cloneCapabilities({
          vision: false,
          image_output: false,
          tool_calling: false,
          reasoning: false,
          embedding: true,
        });
        selection.limits = cloneLimits(selection.limits);
        selection.provider_options = { ...(fallbackModel.provider_options_example || {}) };
      }
    }
    return;
  }

  if (scenario === 'image_generation') {
    const imageModels = resolvedModels.image_generation_models.filter((model) => !model.hidden);
    const preferredModelId = selection.model || resolveProviderDefaultModel(registry, providerId, provider, scenario);
    const matchedModel = imageModels.find((model) => model.id === preferredModelId);
    const fallbackModel = matchedModel || imageModels[0];
    if (fallbackModel) {
      selection.model = fallbackModel.id;
      selection.embedding_dimension = null;
      if (!selection.capability_override_enabled) {
        selection.capabilities = cloneCapabilities({
          vision: fallbackModel.capabilities.vision,
          image_output: true,
          tool_calling: fallbackModel.capabilities.tool_calling,
          reasoning: fallbackModel.capabilities.reasoning,
          embedding: false,
        });
        selection.limits = cloneLimits(fallbackModel.limits);
        selection.provider_options = { ...(fallbackModel.provider_options_example || {}) };
      }
      return;
    }
    if (!selection.capability_override_enabled) {
      selection.capabilities = cloneCapabilities({
        vision: false,
        image_output: true,
        tool_calling: false,
        reasoning: false,
        embedding: false,
      });
      selection.limits = cloneLimits(selection.limits);
    }
    return;
  }

  if (provider.provider_type === 'custom') {
    const models = resolvedModels.chat_models.filter((model) => !model.hidden);
    const preferredModelId = selection.model || resolveProviderDefaultModel(registry, providerId, provider, scenario || 'core');
    const matchedModel = models.find((model) => model.id === preferredModelId);
    const fallbackModel = matchedModel || models[0];
    if (fallbackModel) {
      selection.model = fallbackModel.id;
      selection.embedding_dimension = null;
      if (!selection.capability_override_enabled) {
        selection.capabilities = cloneCapabilities(fallbackModel.capabilities);
        selection.limits = cloneLimits(fallbackModel.limits);
        selection.provider_options = { ...(fallbackModel.provider_options_example || {}) };
      }
    } else {
      selection.model = preferredModelId;
      if (!selection.capability_override_enabled) {
        selection.capabilities = cloneCapabilities(registry.custom_provider.capabilities);
        selection.limits = cloneLimits(registry.custom_provider.limits);
        selection.provider_options = { ...(registry.custom_provider.provider_options_example || {}) };
      }
    }
    return;
  }

  const models = resolvedModels.chat_models.filter((model) => !model.hidden);
  const preferredModelId = selection.model || resolveProviderDefaultModel(registry, providerId, provider, scenario || 'core');
  const matchedModel = models.find((model) => model.id === preferredModelId);
  const fallbackModel = matchedModel || models[0];
  if (fallbackModel) {
    selection.model = fallbackModel.id;
    selection.embedding_dimension = null;
    if (!selection.capability_override_enabled) {
      selection.capabilities = cloneCapabilities({
        vision: fallbackModel.capabilities.vision,
        image_output: fallbackModel.capabilities.image_output,
        tool_calling: fallbackModel.capabilities.tool_calling,
        reasoning: fallbackModel.capabilities.reasoning,
        embedding: false,
      });
      selection.limits = cloneLimits(fallbackModel.limits);
      selection.provider_options = { ...(fallbackModel.provider_options_example || {}) };
    }
  }
};

export const normalizeLLMConfig = (value: LLMConfig, registry: LLMProviderRegistry): LLMConfig => {
  const next = cloneLLMConfig(value);

  for (const providerMeta of registry.providers.filter((provider) => provider.source !== 'custom')) {
    if (!next.providers[providerMeta.id]) {
      next.providers[providerMeta.id] = {
        enabled: false,
        provider_type: (providerMeta.provider_type || providerMeta.id) as LLMProviderConfig['provider_type'],
        display_name: providerMeta.display_name || providerMeta.id,
        api_key: '',
        base_url: '',
        model_metadata_overrides: {},
      };
    } else {
      next.providers[providerMeta.id] = {
        ...cloneProvider(next.providers[providerMeta.id]),
        provider_type: (providerMeta.provider_type || providerMeta.id) as LLMProviderConfig['provider_type'],
        display_name: next.providers[providerMeta.id].display_name || providerMeta.display_name || providerMeta.id,
      };
    }
  }

  const firstEnabledProviderId = Object.entries(next.providers).find(([, provider]) => provider.enabled)?.[0] || '';
  const firstEnabledEmbeddingProviderId =
    Object.entries(next.providers).find(([providerId, provider]) => {
      if (!provider.enabled) {
        return false;
      }
      return Boolean(getResolvedProviderModels(registry, providerId, provider).embedding_models.length);
    })?.[0] || '';
  const firstEnabledImageProviderId =
    Object.entries(next.providers).find(([providerId, provider]) => {
      if (!provider.enabled) {
        return false;
      }
      return Boolean(getResolvedProviderModels(registry, providerId, provider).image_generation_models.length);
    })?.[0] || '';

  for (const scenario of BUILTIN_SCENARIOS) {
    if (scenario === 'image_generation') {
      if (!next.selections[scenario]) {
        next.selections[scenario] = {
          provider_id: '',
          model: '',
          embedding_dimension: null,
          capability_override_enabled: false,
          capabilities: cloneCapabilities({
            vision: false,
            image_output: true,
            tool_calling: false,
            reasoning: false,
            embedding: false,
          }),
          limits: cloneLimits(),
          provider_options: {},
        };
      }
    }

    const selection = cloneSelection(next.selections[scenario]);
    const hasEnabledSelection =
      Boolean(selection.provider_id) &&
      Boolean(next.providers[selection.provider_id]?.enabled);
    const hasEnabledScenarioSelection =
      scenario === 'embedding'
        ? (hasEnabledSelection &&
            Boolean(
              getResolvedProviderModels(
                registry,
                selection.provider_id,
                next.providers[selection.provider_id]
              ).embedding_models.length
            ))
        : scenario === 'image_generation'
          ? (hasEnabledSelection &&
              Boolean(
                getResolvedProviderModels(
                  registry,
                  selection.provider_id,
                  next.providers[selection.provider_id]
                ).image_generation_models.length
              ))
          : hasEnabledSelection;

    const firstAvailableProviderId =
      scenario === 'embedding'
        ? firstEnabledEmbeddingProviderId
        : scenario === 'image_generation'
          ? firstEnabledImageProviderId
          : firstEnabledProviderId;

    if (!firstAvailableProviderId) {
      selection.provider_id = '';
      selection.model = '';
      selection.embedding_dimension = null;
      if (!selection.capability_override_enabled) {
        selection.capabilities = cloneCapabilities(
          scenario === 'embedding'
            ? {
                vision: false,
                image_output: false,
                tool_calling: false,
                reasoning: false,
                embedding: true,
              }
            : scenario === 'image_generation'
              ? {
                  vision: false,
                  image_output: true,
                  tool_calling: false,
                  reasoning: false,
                  embedding: false,
                }
            : undefined
        );
        selection.limits = cloneLimits();
        selection.provider_options = {};
      }
      next.selections[scenario] = selection;
      continue;
    }

    const selectedProvider = hasEnabledScenarioSelection
      ? next.providers[selection.provider_id]
      : next.providers[firstAvailableProviderId];

    selection.provider_id = hasEnabledScenarioSelection
      ? selection.provider_id
      : firstAvailableProviderId;

    applySelectionDefaults(selection, registry, selection.provider_id, selectedProvider, scenario);
    next.selections[scenario] = selection;
  }

  return next;
};
