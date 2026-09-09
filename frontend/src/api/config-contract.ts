import { z } from 'zod';
import { resolveInitialLanguage } from '@/utils/language';
import { readDevicePreferences } from '@/runtime/device-preferences';
import type { ApiResponse } from './client';
import type { components } from './generated/config-types';
import {
  validateConfigResponse,
  validateOnboardingStatusResponse,
  validateOnboardingTemplateResponse,
} from './generated/config-validators';
import type { OnboardingStatus, OnboardingTemplateData, SystemConfig, TimelineSourceConfig } from './modules/config';

type Wire = components['schemas'];

export class ApiContractError extends Error {
  readonly code = 'INVALID_API_RESPONSE';

  constructor(contract: string) {
    // Do not include response content: configuration responses can contain credentials.
    super(`Invalid ${contract} response`);
    this.name = 'ApiContractError';
  }
}

export function requireConfiguration(response: ApiResponse<SystemConfig>): SystemConfig {
  if (!response.success) throw new Error(response.message || 'Configuration request failed');
  if (!response.data) throw new ApiContractError('configuration');
  return response.data;
}

const layerModifiers = z.strictObject({
  behavior_shifts: z.array(z.string()).optional(),
  memory_behavior: z.string().optional(),
  protective_bias: z.string().optional(),
  voice_unlocks: z.array(z.string()).optional(),
  humor_delta: z.number().optional(),
  directness_delta: z.number().optional(),
  register_unlocks: z.array(z.string()).optional(),
  trigger_threshold_shifts: z.record(z.string(), z.number()).optional(),
  sarcasm_bounds: z.string().optional(),
});

function connection(value: Wire['LLMProviderConnectionConfigModel']) {
  return { ...value, api_key: value.api_key ?? undefined, base_url: value.base_url ?? undefined };
}

function source(value: Wire['TimelineSourceConfigModel']): TimelineSourceConfig {
  return {
    ...value,
    sync_mode: z.enum(['manual', 'interval', 'watch']).parse(value.sync_mode),
    default_retention_mode: z.enum(['retain_raw', 'analyze_only']).parse(value.default_retention_mode),
    storage_mode: z.enum(['managed', 'external_reference']).parse(value.storage_mode),
  };
}

/** Convert the generated wire model to the editable UI model without response defaults. */
export function toSystemConfig(value: Wire['SystemConfigModel']): SystemConfig {
  const providers = Object.fromEntries(Object.entries(value.llm.providers).map(([id, provider]) => [id, {
    ...provider,
    provider_type: z.enum(['openai', 'anthropic', 'glm', 'gemini', 'grok', 'deepseek', 'dashscope', 'kimi', 'minimax', 'xiaomimimo', 'custom', 'local']).parse(provider.provider_type),
    api_format: z.enum(['openai', 'anthropic']).nullable().parse(provider.api_format) ?? undefined,
    api_key: provider.api_key ?? undefined,
    base_url: provider.base_url ?? undefined,
    custom_default_model: provider.custom_default_model ?? undefined,
    services: {
      chat: connection(provider.services.chat),
      embedding: connection(provider.services.embedding),
      image_generation: { ...provider.services.image_generation, ...connection(provider.services.image_generation) },
      tts: { ...provider.services.tts, ...connection(provider.services.tts) },
    },
  }]));
  const selections = value.llm.selections;
  for (const scenario of ['auxiliary', 'core', 'memory_summarizer', 'embedding', 'image_generation']) {
    if (!selections[scenario]) throw new ApiContractError('configuration selections');
  }
  return {
    ...value,
    agent: { ...value.agent, description: value.agent.description ?? undefined },
    llm: {
      ...value.llm, providers,
      selections: { auxiliary: selections.auxiliary, core: selections.core, memory_summarizer: selections.memory_summarizer, embedding: selections.embedding, image_generation: selections.image_generation },
    },
    preferences: {
      ...value.preferences,
      ...readDevicePreferences(),
      user_mode: z.enum(['quick', 'expert']).nullable().parse(value.preferences.user_mode),
      language: resolveInitialLanguage(),
    },
    network: { ...value.network, proxy_type: z.enum(['http', 'socks5']).parse(value.network.proxy_type) },
    memory: {
      ...value.memory,
      db_path: value.memory.db_path ?? undefined,
      history_behavior: z.enum(['delete', 'archive']).parse(value.memory.history_behavior),
      embedding: {
        ...value.memory.embedding,
        mode: z.enum(['off', 'remote', 'local']).parse(value.memory.embedding.mode),
        local: { ...value.memory.embedding.local, model_source: z.enum(['managed', 'external']).parse(value.memory.embedding.local.model_source) },
      },
    },
    personality: { ...value.personality, persona_layers: value.personality.persona_layers.map(layer => ({ ...layer, modifiers: layerModifiers.parse(layer.modifiers) })) },
    timeline: { sources: {
      photo_library: source(value.timeline.sources.photo_library),
      ...Object.fromEntries(Object.entries(value.timeline.sources).filter((entry): entry is [string, Wire['TimelineSourceConfigModel']] => entry[1] !== null).map(([key, item]) => [key, source(item)])),
    } },
  };
}

function mapContract<T>(name: string, map: () => T): T {
  try {
    return map();
  } catch {
    throw new ApiContractError(name);
  }
}

export function parseConfigResponse(value: unknown): ApiResponse<SystemConfig> {
  if (!validateConfigResponse(value) || (value.success && !value.data)) throw new ApiContractError('configuration');
  return mapContract('configuration', () => ({ ...value, data: value.data ? toSystemConfig(value.data) : undefined }));
}

export function parseOnboardingStatusResponse(value: unknown): ApiResponse<OnboardingStatus> {
  if (!validateOnboardingStatusResponse(value)) throw new ApiContractError('onboarding status');
  return value;
}

export function parseOnboardingTemplateResponse(value: unknown): ApiResponse<OnboardingTemplateData> {
  if (!validateOnboardingTemplateResponse(value) || (value.success && !value.data)) throw new ApiContractError('onboarding template');
  return mapContract('onboarding template', () => ({ ...value, data: value.data ? { config: toSystemConfig(value.data.config) } : undefined }));
}
