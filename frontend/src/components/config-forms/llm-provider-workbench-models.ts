import {
  resolveProviderModels,
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
    max_concurrency?: number | null;
  };
  kinds: Array<'chat' | 'embedding' | 'image'>;
  dimensions: number[];
}

export const buildProviderWorkbenchModels = (
  registry: LLMProviderRegistry,
  providerId: string,
  provider: LLMProviderConfig | undefined
): ProviderWorkbenchModelItem[] => {
  if (!provider) {
    return [];
  }

  const resolved = resolveProviderModels(registry, providerId, provider);
  const models = new Map<string, ProviderWorkbenchModelItem>();

  for (const model of resolved.chat_models) {
    models.set(model.id, {
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
    });
  }

  for (const model of resolved.embedding_models) {
    const existing = models.get(model.id);
    if (existing) {
      existing.kinds = Array.from(new Set([...existing.kinds, 'embedding']));
      existing.capabilities = model.capabilities;
      existing.limits = model.limits || {};
      existing.dimensions = [...(model.dimensions || [])];
      continue;
    }

    models.set(model.id, {
      id: model.id,
      label: model.label || model.id,
      source: model.source,
      capabilities: model.capabilities,
      limits: model.limits || {},
      kinds: ['embedding'],
      dimensions: [...(model.dimensions || [])],
    });
  }

  for (const model of resolved.image_generation_models) {
    const existing = models.get(model.id);
    if (existing) {
      existing.kinds = Array.from(new Set([...existing.kinds, 'image']));
      existing.source = model.source;
      existing.capabilities = model.capabilities;
      existing.limits = model.limits || {};
      continue;
    }
    models.set(model.id, {
      id: model.id,
      label: model.label || model.id,
      source: model.source,
      capabilities: model.capabilities,
      limits: model.limits || {},
      kinds: ['image'],
      dimensions: [],
    });
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