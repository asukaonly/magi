import {
  DEFAULT_LLM_CUSTOM_PROVIDER_META,
  DEFAULT_LLM_CAPABILITIES,
  DEFAULT_LLM_LIMITS,
  type LLMCapabilities,
  type LLMConcurrencyOverrideConfig,
  type LLMConfig,
  type LLMCustomProviderMeta,
  type LLMCustomProviderTemplateData,
  type LLMLimits,
  type LLMProviderFieldConfig,
  type LLMProviderConfig,
  type LLMProviderCatalog,
  type LLMProviderRegistry,
  type LLMScenario,
  type LLMSelectionConfig,
  resolveProviderModels,
} from '@/api/modules/config';

export const BUILTIN_SCENARIOS: LLMScenario[] = ['auxiliary', 'core', 'memory_summarizer', 'embedding', 'image_generation'];

export type LLMProviderServiceName = 'chat' | 'embedding' | 'image_generation';

export type LLMValidationIssueCode =
  | 'customServiceModelRequired'
  | 'customScenarioModelMissing'
  | 'pluginModelRequired'
  | 'pluginProviderUnavailable';

export interface LLMValidationIssue {
  code: LLMValidationIssueCode;
  providerId: string;
  providerName: string;
  serviceName: LLMProviderServiceName;
  scenario?: LLMScenario;
  model?: string;
}

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

const cloneConnectionConfig = (
  value?: Partial<LLMProviderConfig['services']['chat']>,
  defaultEnabled = true
): LLMProviderConfig['services']['chat'] => ({
  enabled: value?.enabled ?? defaultEnabled,
  api_key: value?.api_key || '',
  base_url: value?.base_url || '',
});

const cloneImageGenerationConfig = (
  value?: Partial<LLMProviderConfig['services']['image_generation']>
): LLMProviderConfig['services']['image_generation'] => ({
  ...cloneConnectionConfig(value, false),
  timeout: value?.timeout ?? 180,
  native_protocol: value?.native_protocol ?? null,
});

const cloneTTSConfig = (
  value?: Partial<LLMProviderConfig['services']['tts']>
): LLMProviderConfig['services']['tts'] => ({
  ...cloneConnectionConfig(value, false),
  model: value?.model || '',
  voice: value?.voice || '',
  response_format: value?.response_format || '',
});

const cloneServices = (
  value?: Partial<LLMProviderConfig['services']>
): LLMProviderConfig['services'] => ({
  chat: cloneConnectionConfig(value?.chat, true),
  embedding: cloneConnectionConfig(value?.embedding, true),
  image_generation: cloneImageGenerationConfig(value?.image_generation),
  tts: cloneTTSConfig(value?.tts),
});

export const cloneProvider = (value?: Partial<LLMProviderConfig>): LLMProviderConfig => ({
  enabled: Boolean(value?.enabled),
  provider_type: value?.provider_type || 'openai',
  display_name: value?.display_name || '',
  provider_plan: value?.provider_plan || null,
  api_key: value?.api_key || '',
  base_url: value?.base_url || '',
  services: cloneServices(value?.services),
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
        cost: override?.cost === null ? null : override?.cost ? { ...override.cost } : undefined,
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
    auxiliary: cloneSelection(value?.selections?.auxiliary),
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

export const getCustomProviderServiceModelIds = (
  provider: LLMProviderConfig | undefined,
  serviceName: LLMProviderServiceName
): string[] => {
  if (!provider || provider.provider_type !== 'custom') {
    return [];
  }

  if (serviceName === 'chat') {
    return [...(provider.custom_models || [])].filter(Boolean);
  }

  return Object.entries(provider.model_metadata_overrides || {})
    .filter(([, override]) => {
      if (serviceName === 'embedding') {
        return override?.capabilities?.embedding === true;
      }
      return override?.capabilities?.image_output === true;
    })
    .map(([modelId]) => modelId)
    .filter(Boolean);
};

const scenarioServiceName = (scenario: LLMScenario): LLMProviderServiceName => {
  if (scenario === 'embedding') {
    return 'embedding';
  }
  if (scenario === 'image_generation') {
    return 'image_generation';
  }
  return 'chat';
};

export const validateCustomProviderServices = (
  provider: LLMProviderConfig | undefined,
  providerId: string
): LLMValidationIssue[] => {
  if (!provider || provider.provider_type !== 'custom' || !provider.enabled) {
    return [];
  }

  const providerName = provider.display_name || providerId;
  const serviceNames: LLMProviderServiceName[] = ['chat', 'embedding', 'image_generation'];
  return serviceNames.flatMap((serviceName) => {
    if (!provider.services?.[serviceName]?.enabled) {
      return [];
    }
    if (getCustomProviderServiceModelIds(provider, serviceName).length > 0) {
      return [];
    }
    return [{ code: 'customServiceModelRequired', providerId, providerName, serviceName } satisfies LLMValidationIssue];
  });
};

export const validateLLMCustomProviderReadiness = (value?: LLMConfig): LLMValidationIssue[] => {
  if (!value) {
    return [];
  }

  const issues: LLMValidationIssue[] = [];

  for (const [providerId, provider] of Object.entries(value.providers || {})) {
    issues.push(...validateCustomProviderServices(provider, providerId));
  }

  for (const [scenario, selection] of Object.entries(value.selections || {}) as [LLMScenario, LLMSelectionConfig][]) {
    if (!selection?.provider_id || !selection.model) {
      continue;
    }
    const provider = value.providers?.[selection.provider_id];
    if (!provider || provider.provider_type !== 'custom' || !provider.enabled) {
      continue;
    }
    const serviceName = scenarioServiceName(scenario);
    if (!provider.services?.[serviceName]?.enabled) {
      continue;
    }
    const models = getCustomProviderServiceModelIds(provider, serviceName);
    if (models.length > 0 && !models.includes(selection.model)) {
      issues.push({
        code: 'customScenarioModelMissing',
        providerId: selection.provider_id,
        providerName: provider.display_name || selection.provider_id,
        serviceName,
        scenario,
        model: selection.model,
      });
    }
  }

  return issues;
};

export const llmSignature = (value: LLMConfig): string => JSON.stringify(value);

const cloneProviderField = (
  value?: Partial<LLMProviderFieldConfig>,
  fallback?: Partial<LLMProviderFieldConfig>
): LLMProviderFieldConfig => {
  const next: LLMProviderFieldConfig = {
    visible: value?.visible ?? fallback?.visible ?? true,
    required: value?.required ?? fallback?.required ?? false,
  };
  const placeholder = value?.placeholder ?? fallback?.placeholder;
  if (placeholder !== undefined) {
    next.placeholder = placeholder;
  }
  const options = value?.options ?? fallback?.options;
  if (options) {
    next.options = [...options];
  }
  return next;
};

const cloneProviderFields = (
  value?: LLMCustomProviderMeta['fields'],
  fallback?: LLMCustomProviderMeta['fields']
): Record<string, LLMProviderFieldConfig> => {
  const keys = new Set([...Object.keys(fallback || {}), ...Object.keys(value || {})]);
  return Object.fromEntries(
    [...keys].map((key) => [key, cloneProviderField(value?.[key], fallback?.[key])])
  );
};

const cloneRuntimeLimits = (value?: Partial<LLMLimits>, fallback?: Partial<LLMLimits>): LLMLimits => ({
  ...(fallback || {}),
  ...(value || {}),
});

const cloneCustomProviderMeta = (value?: Partial<LLMCustomProviderMeta> | null): LLMCustomProviderMeta => ({
  enabled: value?.enabled ?? DEFAULT_LLM_CUSTOM_PROVIDER_META.enabled,
  display_name: value?.display_name ?? DEFAULT_LLM_CUSTOM_PROVIDER_META.display_name,
  description: value?.description ?? DEFAULT_LLM_CUSTOM_PROVIDER_META.description,
  icon: value?.icon ?? DEFAULT_LLM_CUSTOM_PROVIDER_META.icon,
  fields: cloneProviderFields(value?.fields, DEFAULT_LLM_CUSTOM_PROVIDER_META.fields),
  capabilities: cloneCapabilities(value?.capabilities || DEFAULT_LLM_CUSTOM_PROVIDER_META.capabilities),
  limits: cloneRuntimeLimits(value?.limits, DEFAULT_LLM_CUSTOM_PROVIDER_META.limits),
  provider_options_example: {
    ...(DEFAULT_LLM_CUSTOM_PROVIDER_META.provider_options_example || {}),
    ...(value?.provider_options_example || {}),
  },
});

export const buildRegistryFromCatalog = (
  catalog: Partial<LLMProviderCatalog> | null | undefined,
  customTemplate: Partial<LLMCustomProviderTemplateData> | null | undefined
): LLMProviderRegistry => ({
  providers: [...(catalog?.providers || [])],
  custom_provider: cloneCustomProviderMeta(customTemplate?.template),
  plugin_providers: [...(catalog?.plugin_providers || [])],
});

export const isPluginModelSelection = (value: LLMConfig, providerId: string): boolean =>
  !value.providers[providerId] && providerId.includes(':');

export const validatePluginModelSelections = (value: LLMConfig, registry: LLMProviderRegistry): LLMValidationIssue[] =>
  (['core', 'auxiliary', 'memory_summarizer'] as const).flatMap((scenario) => {
    const selection = value.selections[scenario];
    if (!isPluginModelSelection(value, selection.provider_id)) return [];
    const provider = registry.plugin_providers?.find((entry) => entry.provider_id === selection.provider_id);
    const code = !provider ? 'pluginProviderUnavailable' : !selection.model.trim() ? 'pluginModelRequired' : null;
    return code ? [{
      code,
      providerId: selection.provider_id,
      providerName: provider?.display_name || selection.provider_id,
      serviceName: 'chat',
      scenario,
    } satisfies LLMValidationIssue] : [];
  });

const getProviderMeta = (registry: LLMProviderRegistry, providerId?: string) =>
  registry.providers.find((provider) => provider.id === providerId);

const getProviderTemplateMeta = (registry: LLMProviderRegistry, provider?: LLMProviderConfig) => {
  if (!provider) return undefined;
  return registry.providers.find((item) => item.id === provider.provider_type);
};

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
  const configured = (provider?.services?.chat?.base_url || provider?.base_url || '').trim();
  if (configured) {
    return configured;
  }
  return getProviderMeta(registry, providerId)?.default_base_url || getProviderTemplateMeta(registry, provider)?.default_base_url || '';
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

const resolveRuntimeProviderType = (
  provider: LLMProviderConfig | undefined
): string => {
  const providerType = String(provider?.provider_type || '').trim().toLowerCase();
  if (providerType && providerType !== 'custom') {
    return providerType;
  }

  const apiFormat = String(provider?.api_format || 'openai').trim().toLowerCase();
  if (apiFormat === 'anthropic') {
    return 'anthropic';
  }
  return 'custom';
};

export const isProviderAllowedForScenario = (
  registry: LLMProviderRegistry,
  provider: LLMProviderConfig | undefined,
  scenario: LLMScenario
): boolean => {
  const planId = String(provider?.provider_plan || '').trim();
  if (!planId) {
    return true;
  }
  const providerMeta = getProviderTemplateMeta(registry, provider);
  const plan = providerMeta?.plans?.find((item) => item.id === planId);
  if (!plan) {
    return false;
  }
  return !plan.allowed_scenarios || plan.allowed_scenarios.includes(scenario);
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
  const runtimeProvider = resolveRuntimeProviderType(provider);
  const serviceBaseUrl = scenario === 'embedding'
    ? provider.services?.embedding?.base_url
    : scenario === 'image_generation'
      ? provider.services?.image_generation?.base_url
      : provider.services?.chat?.base_url;
  const baseUrl = serviceBaseUrl || provider.base_url || resolveProviderActionBaseUrl(registry, providerId, provider);
  const host = normalizeBaseUrlHost(baseUrl) || runtimeProvider;
  const normalizedProviderId = String(providerId).trim().toLowerCase() || runtimeProvider;
  const providerPlan = String(provider.provider_plan || '').trim().toLowerCase() || 'api';
  const requestFamily = scenario === 'embedding' ? 'embedding' : scenario === 'image_generation' ? 'image_generation' : 'chat';
  return `${runtimeProvider}::${normalizedProviderId}::${providerPlan}::${host}::${normalizedModel}::${requestFamily}`;
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

  return buildRuntimeOverrideKey({ registry, providerId, provider, model, scenario }) ? 4 : null;
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
  if (!isProviderAllowedForScenario(registry, provider, scenario)) {
    return '';
  }
  const providerMeta = getProviderTemplateMeta(registry, provider);
  const resolvedModels = getResolvedProviderModels(registry, providerId, provider);

  if (scenario === 'embedding') {
    return resolvedModels.embedding_models.find((model) => !model.hidden)?.id || '';
  }
  if (scenario === 'image_generation') {
    const imageModels = resolvedModels.image_generation_models.filter((model) => !model.hidden);
    return imageModels[0]?.id || '';
  }
  if (scenario === 'auxiliary') {
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
  if (scenario && !isProviderAllowedForScenario(registry, provider, scenario)) {
    selection.provider_id = '';
    selection.model = '';
    selection.embedding_dimension = null;
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
        selection.capabilities = cloneCapabilities(registry.custom_provider?.capabilities);
        selection.limits = cloneLimits(registry.custom_provider?.limits);
        selection.provider_options = { ...(registry.custom_provider?.provider_options_example || {}) };
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

  for (const providerId of Object.keys(next.providers)) {
    const provider = next.providers[providerId];
    const providerMeta = getProviderTemplateMeta(registry, provider);
    next.providers[providerId] = {
      ...cloneProvider(provider),
      display_name: provider.display_name || providerMeta?.display_name || providerId,
    };
  }

  const firstEnabledChatProviderId = (scenario: LLMScenario) =>
    Object.entries(next.providers).find(
      ([, provider]) =>
        provider.enabled &&
        Boolean(provider.services?.chat?.enabled) &&
        isProviderAllowedForScenario(registry, provider, scenario)
    )?.[0] || '';
  const firstEnabledEmbeddingProviderId =
    Object.entries(next.providers).find(([providerId, provider]) => {
      if (!provider.enabled) {
        return false;
      }
      if (!provider.services?.embedding?.enabled) {
        return false;
      }
      return Boolean(getResolvedProviderModels(registry, providerId, provider).embedding_models.length);
    })?.[0] || '';
  const firstEnabledImageProviderId =
    Object.entries(next.providers).find(([providerId, provider]) => {
      if (!provider.enabled) {
        return false;
      }
      if (!provider.services?.image_generation?.enabled) {
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
    // Preserve the user's plugin selection even when its connection is offline.
    // Availability is validated by the host; never silently switch providers.
    if (
      scenario !== 'embedding' && scenario !== 'image_generation'
      && isPluginModelSelection(next, selection.provider_id)
    ) {
      next.selections[scenario] = selection;
      continue;
    }
    const hasEnabledSelection =
      Boolean(selection.provider_id) &&
      Boolean(next.providers[selection.provider_id]?.enabled);
    const hasEnabledScenarioSelection =
      scenario === 'embedding'
        ? (hasEnabledSelection &&
            Boolean(next.providers[selection.provider_id]?.services?.embedding?.enabled) &&
            Boolean(
              getResolvedProviderModels(
                registry,
                selection.provider_id,
                next.providers[selection.provider_id]
              ).embedding_models.length
            ))
        : scenario === 'image_generation'
          ? (hasEnabledSelection &&
              Boolean(next.providers[selection.provider_id]?.services?.image_generation?.enabled) &&
              Boolean(
                getResolvedProviderModels(
                  registry,
                  selection.provider_id,
                  next.providers[selection.provider_id]
                ).image_generation_models.length
              ))
          : hasEnabledSelection &&
            Boolean(next.providers[selection.provider_id]?.services?.chat?.enabled) &&
            isProviderAllowedForScenario(
              registry,
              next.providers[selection.provider_id],
              scenario
            );

    const firstAvailableProviderId =
      scenario === 'embedding'
        ? firstEnabledEmbeddingProviderId
        : scenario === 'image_generation'
          ? firstEnabledImageProviderId
          : firstEnabledChatProviderId(scenario);

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
