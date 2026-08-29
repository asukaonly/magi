import {
  resolveProviderModels,
  type LLMCapabilities,
  type LLMModelMetadataOverride,
  type LLMProviderConfig,
  type LLMProviderRegistry,
  type ModelVendor,
} from '@/api/modules/config';

export interface ProviderWorkbenchModelItem {
  id: string;
  label: string;
  source: 'builtin' | 'manual';
  vendor?: ModelVendor;
  capabilities: {
    vision: boolean;
    image_output: boolean;
    tool_calling: boolean;
    reasoning: boolean;
    embedding: boolean;
  };
  limits: {
    context_window?: number | null;
    max_output_tokens?: number | null;
    max_tool_schemas?: number | null;
    max_schema_tokens?: number | null;
  };
  kinds: Array<'chat' | 'embedding' | 'image'>;
  dimensions: number[];
}

const DEFAULT_CAPABILITIES: ProviderWorkbenchModelItem['capabilities'] = {
  vision: false,
  image_output: false,
  tool_calling: false,
  reasoning: false,
  embedding: false,
};

const DEFAULT_LIMITS: ProviderWorkbenchModelItem['limits'] = {
  context_window: null,
  max_output_tokens: null,
  max_tool_schemas: null,
  max_schema_tokens: null,
};

const mergeCapabilities = (
  base: ProviderWorkbenchModelItem['capabilities'],
  override?: LLMModelMetadataOverride
): ProviderWorkbenchModelItem['capabilities'] => {
  const next = { ...base };
  for (const key of Object.keys(next) as Array<keyof LLMCapabilities>) {
    const value = override?.capabilities?.[key];
    if (typeof value === 'boolean') {
      next[key] = value;
    }
  }
  return next;
};

const mergeLimits = (
  base: ProviderWorkbenchModelItem['limits'],
  override?: LLMModelMetadataOverride
): ProviderWorkbenchModelItem['limits'] => ({
  ...base,
  ...(override?.limits || {}),
});

const applyOverride = (
  model: ProviderWorkbenchModelItem,
  override?: LLMModelMetadataOverride
): ProviderWorkbenchModelItem => {
  if (!override) {
    return model;
  }

  return {
    ...model,
    label: override.label || model.label,
    vendor: override.vendor ?? model.vendor,
    capabilities: mergeCapabilities(model.capabilities, override),
    limits: mergeLimits(model.limits, override),
    dimensions: override.dimensions ?? model.dimensions,
  };
};

export const buildProviderWorkbenchModels = (
  registry: LLMProviderRegistry,
  providerId: string,
  provider: LLMProviderConfig | undefined
): ProviderWorkbenchModelItem[] => {
  if (!provider) {
    return [];
  }

  const resolved = resolveProviderModels(registry, providerId, provider);
  const overrides = provider.model_metadata_overrides || {};
  const isCustomProvider = provider.provider_type === 'custom';
  const manualBaseCapabilities: ProviderWorkbenchModelItem['capabilities'] = isCustomProvider
    ? {
        ...DEFAULT_CAPABILITIES,
        ...(registry.custom_provider?.capabilities || {}),
      }
    : {
        ...DEFAULT_CAPABILITIES,
        tool_calling: true,
        reasoning: true,
      };
  const manualBaseLimits: ProviderWorkbenchModelItem['limits'] = isCustomProvider
    ? {
        ...DEFAULT_LIMITS,
        ...(registry.custom_provider?.limits || {}),
      }
    : { ...DEFAULT_LIMITS };
  const models = new Map<string, ProviderWorkbenchModelItem>();

  for (const model of resolved.chat_models) {
    models.set(model.id, applyOverride({
      id: model.id,
      label: model.label || model.id,
      source: model.source,
      vendor: model.vendor,
      capabilities: {
        vision: model.capabilities.vision,
        image_output: model.capabilities.image_output,
        tool_calling: model.capabilities.tool_calling,
        reasoning: model.capabilities.reasoning,
        embedding: false,
      },
      limits: model.limits || {},
      kinds: ['chat'],
      dimensions: [],
    }, overrides[model.id]));
  }

  for (const model of resolved.embedding_models) {
    const existing = models.get(model.id);
    if (existing) {
      models.set(model.id, applyOverride({
        ...existing,
        kinds: Array.from(new Set([...existing.kinds, 'embedding'])),
        capabilities: model.capabilities,
        limits: model.limits || {},
        dimensions: [...(model.dimensions || [])],
      }, overrides[model.id]));
      continue;
    }

    models.set(model.id, applyOverride({
      id: model.id,
      label: model.label || model.id,
      source: model.source,
      capabilities: model.capabilities,
      limits: model.limits || {},
      kinds: ['embedding'],
      dimensions: [...(model.dimensions || [])],
    }, overrides[model.id]));
  }

  for (const model of resolved.image_generation_models) {
    const existing = models.get(model.id);
    if (existing) {
      models.set(model.id, applyOverride({
        ...existing,
        kinds: Array.from(new Set([...existing.kinds, 'image'])),
        source: model.source,
        capabilities: model.capabilities,
        limits: model.limits || {},
      }, overrides[model.id]));
      continue;
    }
    models.set(model.id, applyOverride({
      id: model.id,
      label: model.label || model.id,
      source: model.source,
      capabilities: model.capabilities,
      limits: model.limits || {},
      kinds: ['image'],
      dimensions: [],
    }, overrides[model.id]));
  }

  for (const modelId of provider.custom_models || []) {
    if (models.has(modelId)) {
      continue;
    }

    models.set(modelId, applyOverride({
      id: modelId,
      label: modelId,
      source: 'manual',
      capabilities: { ...manualBaseCapabilities },
      limits: { ...manualBaseLimits },
      kinds: ['chat'],
      dimensions: [],
    }, overrides[modelId]));
  }

  for (const [modelId, override] of Object.entries(overrides)) {
    if (!models.has(modelId) && override?.capabilities?.embedding !== true && override?.capabilities?.image_output !== true) {
      models.set(modelId, applyOverride({
        id: modelId,
        label: modelId,
        source: 'manual',
        capabilities: { ...manualBaseCapabilities },
        limits: { ...manualBaseLimits },
        kinds: ['chat'],
        dimensions: [],
      }, override));
    }

    if (override?.capabilities?.image_output === true) {
      const existing = models.get(modelId);
      if (existing) {
        models.set(modelId, applyOverride({
          ...existing,
          kinds: Array.from(new Set([...existing.kinds, 'image'])),
          capabilities: {
            ...existing.capabilities,
            image_output: true,
          },
        }, override));
        continue;
      }

      models.set(modelId, applyOverride({
        id: modelId,
        label: modelId,
        source: 'manual',
        capabilities: {
          ...DEFAULT_CAPABILITIES,
          image_output: true,
        },
        limits: { ...DEFAULT_LIMITS },
        kinds: ['image'],
        dimensions: [],
      }, override));
    }

    if (override?.capabilities?.embedding === true) {
      const existing = models.get(modelId);
      if (existing) {
        models.set(modelId, applyOverride({
          ...existing,
          kinds: Array.from(new Set([...existing.kinds, 'embedding'])),
          capabilities: {
            ...existing.capabilities,
            embedding: true,
          },
          dimensions: override.dimensions ?? existing.dimensions,
        }, override));
        continue;
      }

      models.set(modelId, applyOverride({
        id: modelId,
        label: modelId,
        source: 'manual',
        capabilities: {
          ...DEFAULT_CAPABILITIES,
          embedding: true,
        },
        limits: { ...DEFAULT_LIMITS },
        kinds: ['embedding'],
        dimensions: override.dimensions ?? [],
      }, override));
    }
  }

  return Array.from(models.values()).sort((left, right) => {
    if (left.source !== right.source) {
      return left.source === 'builtin' ? -1 : 1;
    }
    return left.label.localeCompare(right.label, 'en');
  });
};


export const cloneModelOverride = (value?: LLMModelMetadataOverride): LLMModelMetadataOverride => ({
  ...(value || {}),
  capabilities: { ...(value?.capabilities || {}) },
  limits: { ...(value?.limits || {}) },
  input_modalities:
    value?.input_modalities === null ? null : value?.input_modalities ? [...value.input_modalities] : undefined,
  output_modalities:
    value?.output_modalities === null ? null : value?.output_modalities ? [...value.output_modalities] : undefined,
  provider_options_example:
    value?.provider_options_example === null
      ? null
      : value?.provider_options_example
        ? { ...value.provider_options_example }
        : undefined,
  cost: value?.cost === null ? null : value?.cost ? { ...value.cost } : undefined,
  dimensions:
    value?.dimensions === null ? null : value?.dimensions ? [...value.dimensions] : undefined,
});

export const isModelOverrideEmpty = (value: LLMModelMetadataOverride): boolean => {
  const capabilities = Object.values(value.capabilities || {}).every((item) => item === null || item === undefined);
  const limits = Object.values(value.limits || {}).every((item) => item === null || item === undefined);

  return !value.label &&
    capabilities &&
    limits &&
    (value.input_modalities === undefined || value.input_modalities === null) &&
    (value.output_modalities === undefined || value.output_modalities === null) &&
    (value.provider_options_example === undefined || value.provider_options_example === null) &&
    (value.cost === undefined || value.cost === null) &&
    (value.dimensions === undefined || value.dimensions === null) &&
    !value.source_note;
};
