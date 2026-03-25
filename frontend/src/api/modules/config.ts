/**
 * Config management API and type definitions.
 */
import { api } from '../client';
import type { PersonalityConfig } from './personality';
import { DEFAULT_PERSONALITY_CONFIG } from './personality';

export type UserMode = 'quick' | 'expert' | null;
export type LanguageCode = 'zh' | 'en';
export type LLMProvider =
  | 'openai'
  | 'anthropic'
  | 'glm'
  | 'gemini'
  | 'deepseek'
  | 'kimi'
  | 'minimax'
  | 'custom'
  | 'local';
export type ApiFormat = 'openai' | 'anthropic';
export type LLMScenario = 'context_decider' | 'core' | 'embedding';

export interface UserPreferences {
  onboarding_completed: boolean;
  user_mode: UserMode;
  language: LanguageCode;
  close_to_tray_enabled: boolean;
  default_chat_workspace_path: string | null;
}

export interface LLMProviderConfig {
  enabled: boolean;
  provider_type: LLMProvider;
  display_name: string;
  api_key?: string;
  base_url?: string;
  api_format?: ApiFormat;
  custom_models?: string[];
  custom_default_model?: string;
  model_metadata_overrides?: Record<string, LLMModelMetadataOverride>;
}

export interface LLMSelectionConfig {
  provider_id: string;
  model: string;
  embedding_dimension?: number | null;
  capability_override_enabled: boolean;
  capabilities: LLMCapabilities;
  limits: LLMLimits;
  provider_options: Record<string, any>;
}

export interface LLMConfig {
  providers: Record<string, LLMProviderConfig>;
  selections: Record<LLMScenario, LLMSelectionConfig>;
  model_runtime_overrides: Record<string, LLMConcurrencyOverrideConfig>;
}

export interface LLMCapabilities {
  vision: boolean;
  image_output: boolean;
  tool_calling: boolean;
  reasoning: boolean;
  embedding: boolean;
}

export interface LLMLimits {
  context_window?: number | null;
  max_output_tokens?: number | null;
}

export interface LLMRuntimeLimits extends LLMLimits {
  max_concurrency?: number | null;
}

export interface LLMCapabilityOverrides {
  vision?: boolean | null;
  image_output?: boolean | null;
  tool_calling?: boolean | null;
  reasoning?: boolean | null;
  embedding?: boolean | null;
}

export interface LLMLimitsOverride {
  context_window?: number | null;
  max_output_tokens?: number | null;
  max_concurrency?: number | null;
}

export interface LLMModelMetadataOverride {
  label?: string | null;
  description?: string | null;
  icon?: string | null;
  capabilities?: LLMCapabilityOverrides;
  limits?: LLMLimitsOverride;
  input_modalities?: string[] | null;
  output_modalities?: string[] | null;
  provider_options_example?: Record<string, any> | null;
  hidden?: boolean | null;
  preferred?: boolean | null;
  source_note?: string | null;
}

export interface LLMConcurrencyOverrideConfig {
  max_concurrency?: number | null;
}

export interface LLMProviderFieldConfig {
  visible: boolean;
  required: boolean;
  placeholder?: string;
  options?: string[];
}

export interface LLMProviderMeta {
  id: string;
  display_name?: string;
  description?: string;
  icon?: string;
  default_model?: string;
  default_classify_model?: string;
  default_base_url?: string;
  chat_models?: LLMChatModelMeta[];
  embedding_models?: LLMEmbeddingModelMeta[];
  image_generation_models?: LLMGenerationModelMeta[];
  audio_generation_models?: LLMGenerationModelMeta[];
  fields?: Record<string, LLMProviderFieldConfig>;
  resolved_chat_models?: LLMResolvedChatModelMeta[];
  resolved_embedding_models?: LLMResolvedEmbeddingModelMeta[];
}

export interface LLMCustomProviderMeta {
  enabled: boolean;
  display_name?: string;
  description?: string;
  icon?: string;
  fields?: Record<string, LLMProviderFieldConfig>;
  capabilities?: LLMCapabilities;
  limits?: LLMRuntimeLimits;
  provider_options_example?: Record<string, any>;
}

export interface LLMChatCapabilities {
  vision: boolean;
  image_output: boolean;
  tool_calling: boolean;
  reasoning: boolean;
}

export interface LLMChatModelMeta {
  id: string;
  label?: string;
  capabilities: LLMChatCapabilities;
  limits: LLMRuntimeLimits;
  provider_options_example?: Record<string, any>;
}

export type LLMResolvedModelSource = 'builtin' | 'manual';

export interface LLMResolvedChatModelMeta extends LLMChatModelMeta {
  description?: string;
  icon?: string;
  source: LLMResolvedModelSource;
  hidden: boolean;
  preferred: boolean;
  input_modalities: string[];
  output_modalities: string[];
}

export interface LLMEmbeddingModelMeta {
  id: string;
  label?: string;
  dimensions: number[];
  limits?: LLMRuntimeLimits;
  provider_options_example?: Record<string, any>;
}

export interface LLMResolvedEmbeddingModelMeta extends LLMEmbeddingModelMeta {
  description?: string;
  icon?: string;
  source: LLMResolvedModelSource;
  hidden: boolean;
  preferred: boolean;
  capabilities: LLMCapabilities;
  input_modalities: string[];
  output_modalities: string[];
}

export interface LLMGenerationModelMeta {
  id: string;
  label?: string;
  provider_options_example?: Record<string, any>;
}

export interface LLMProviderRegistry {
  providers: LLMProviderMeta[];
  custom_provider: LLMCustomProviderMeta;
}

export interface OnboardingTemplateData {
  config: SystemConfig;
  llm_providers: LLMProviderRegistry;
}

export interface DiscoverLLMProviderModelsRequest {
  provider_type: LLMProvider;
  base_url: string;
  api_key?: string;
  api_format?: ApiFormat;
}

export interface DiscoverLLMProviderModelsResponse {
  models: string[];
  default_model?: string | null;
}

export interface TestLLMProviderConnectionRequest {
  provider_id: string;
  provider: LLMProviderConfig;
  model: string;
}

export interface TestLLMProviderConnectionResponse {
  model: string;
  latency_ms: number;
  preview: string;
}

// Re-export PersonalityConfig from personality module
export type { PersonalityConfig };

export interface WeatherToolConfig {
  enabled: boolean;
  provider: 'openweather' | 'qweather';
  apiKey?: string;
  apiUrl?: string;
}

export interface WebSearchToolConfig {
  enabled: boolean;
  provider: 'duckduckgo' | 'brave' | 'perplexity' | 'tavily';
  apiKey?: string;
}

export interface WebFetchToolConfig {
  enabled: boolean;
  usePlaywright: boolean;
}

export interface ToolsConfig {
  builtIn: {
    weather: WeatherToolConfig;
    webSearch: WebSearchToolConfig;
    webFetch: WebFetchToolConfig;
  };
  skills: string[];
}

export interface MemoryEmbeddingConfig {
  backend: 'sqlite_vec' | 'openai';
}

export interface MemoryL0Config {
  enabled: boolean;
  checkpoint_interval_seconds: number;
  runtime_replay_include_l0_only: boolean;
}

export interface MemoryL1Config {
  enabled: boolean;
  retention_days: number;
  t1_importance_enabled: boolean;
  vectors_enabled: boolean;
}

export interface MemoryL2Config {
  enabled: boolean;
  vectors_enabled: boolean;
  batch_flush_interval_seconds: number;
  llm_extraction_enabled: boolean;
  auto_extract_relations: boolean;
  conflict_arbitration_enabled: boolean;
  conflict_arbitration_min_confidence: number;
}

export interface MemoryL3Config {
  enabled: boolean;
  vectors_enabled: boolean;
  llm_summary_enabled: boolean;
  temporal_llm_timeout_seconds: number;
  temporal_llm_min_event_count: number;
  summary_interval_minutes: number;
}

export interface MemoryL4Config {
  enabled: boolean;
  vectors_enabled: boolean;
  skill_extraction_enabled: boolean;
}

export interface MemoryConfig {
  db_path?: string;
  async_embeddings: boolean;
  embedding: MemoryEmbeddingConfig;
  l0: MemoryL0Config;
  l1: MemoryL1Config;
  l2: MemoryL2Config;
  l3: MemoryL3Config;
  l4: MemoryL4Config;
}

export type TimelineSyncMode = 'manual' | 'interval' | 'watch';
export type TimelineRetentionMode = 'retain_raw' | 'analyze_only';
export type TimelineStorageMode = 'managed' | 'external_reference';

export interface TimelineSourceConfig {
  enabled: boolean;
  sync_mode: TimelineSyncMode;
  sync_interval_minutes: number;
  default_retention_mode: TimelineRetentionMode;
  storage_mode: TimelineStorageMode;
  source_path?: string | null;
  fetch_page_content: boolean;
  edge_whitelist: string[];
}

export interface TimelineConfig {
  enabled: boolean;
  expert_mode_edge_override: boolean;
  sources: {
    chat: TimelineSourceConfig;
    manual_journal: TimelineSourceConfig;
    browser_history: TimelineSourceConfig;
    photo_library: TimelineSourceConfig;
  };
}

export type OnboardingStep =
  | 'mode-selection'
  | 'language'
  | 'llm'
  | 'personality'
  | 'memory'
  | 'tools'
  | 'complete';

export interface OnboardingState {
  currentStep: OnboardingStep;
  mode: UserMode;
  completedSteps: OnboardingStep[];
}

export interface SystemConfig {
  agent: {
    name: string;
    description?: string;
  };
  llm: LLMConfig;
  memory: MemoryConfig;
  preferences: UserPreferences;
  personality: PersonalityConfig;
  tools: ToolsConfig;
  timeline: TimelineConfig;
}

export const DEFAULT_LLM_CAPABILITIES: LLMCapabilities = {
  vision: false,
  image_output: false,
  tool_calling: true,
  reasoning: true,
  embedding: false,
};

export const DEFAULT_LLM_LIMITS: LLMLimits = {
  context_window: null,
  max_output_tokens: null,
};

const cloneResolvedCapabilities = (
  base?: Partial<LLMCapabilities>,
  overrides?: LLMCapabilityOverrides
): LLMCapabilities => {
  const next: LLMCapabilities = {
    ...DEFAULT_LLM_CAPABILITIES,
    ...(base || {}),
  };

  for (const [key, value] of Object.entries(overrides || {})) {
    if (value !== null && value !== undefined) {
      next[key as keyof LLMCapabilities] = value as never;
    }
  }

  return next;
};

const cloneResolvedLimits = (
  base?: Partial<LLMRuntimeLimits>,
  overrides?: LLMLimitsOverride
): LLMRuntimeLimits => ({
  ...DEFAULT_LLM_LIMITS,
  ...(base || {}),
  ...(overrides || {}),
});

const defaultChatModalities = (capabilities: LLMCapabilities): { input: string[]; output: string[] } => {
  const input = ['text'];
  if (capabilities.vision) {
    input.push('image');
  }

  const output = ['text'];
  if (capabilities.image_output) {
    output.push('image');
  }
  if (capabilities.embedding) {
    output.push('embedding');
  }

  return { input, output };
};

const defaultEmbeddingModalities = (capabilities: LLMCapabilities): { input: string[]; output: string[] } => {
  const input = ['text'];
  if (capabilities.vision) {
    input.push('image');
  }

  const output = ['embedding'];
  if (capabilities.image_output) {
    output.push('image');
  }

  return { input, output };
};

export interface ResolvedProviderModels {
  chat_models: LLMResolvedChatModelMeta[];
  embedding_models: LLMResolvedEmbeddingModelMeta[];
}

export const resolveProviderModels = (
  registry: LLMProviderRegistry,
  _providerId: string,
  provider?: LLMProviderConfig
): ResolvedProviderModels => {
  const providerMeta =
    provider?.provider_type && provider.provider_type !== 'custom'
      ? registry.providers.find((item) => item.id === provider.provider_type)
      : undefined;
  const overrides = provider?.model_metadata_overrides || {};
  const customModels = provider?.custom_models || [];

  const chatModels = new Map<string, LLMResolvedChatModelMeta>();
  const embeddingModels = new Map<string, LLMResolvedEmbeddingModelMeta>();

  for (const model of providerMeta?.chat_models || []) {
    const override = overrides[model.id];
    const capabilities = cloneResolvedCapabilities(model.capabilities, override?.capabilities);
    const modalities = defaultChatModalities(capabilities);
    chatModels.set(model.id, {
      id: model.id,
      label: override?.label || model.label || model.id,
      description: override?.description || undefined,
      icon: override?.icon || undefined,
      source: 'builtin',
      hidden: Boolean(override?.hidden),
      preferred: Boolean(override?.preferred),
      capabilities,
      limits: cloneResolvedLimits(model.limits, override?.limits),
      input_modalities: override?.input_modalities || modalities.input,
      output_modalities: override?.output_modalities || modalities.output,
      provider_options_example: override?.provider_options_example || model.provider_options_example || {},
    });
  }

  for (const model of providerMeta?.embedding_models || []) {
    const override = overrides[model.id];
    const capabilities = cloneResolvedCapabilities(
      {
        vision: false,
        image_output: false,
        tool_calling: false,
        reasoning: false,
        embedding: true,
      },
      override?.capabilities
    );
    const modalities = defaultEmbeddingModalities(capabilities);
    embeddingModels.set(model.id, {
      id: model.id,
      label: override?.label || model.label || model.id,
      description: override?.description || undefined,
      icon: override?.icon || undefined,
      source: 'builtin',
      hidden: Boolean(override?.hidden),
      preferred: Boolean(override?.preferred),
      capabilities,
      dimensions: model.dimensions || [],
      limits: cloneResolvedLimits(model.limits, override?.limits),
      input_modalities: override?.input_modalities || modalities.input,
      output_modalities: override?.output_modalities || modalities.output,
      provider_options_example: override?.provider_options_example || model.provider_options_example || {},
    });
  }

  const defaultCustomCapabilities =
    provider?.provider_type === 'custom'
      ? {
          ...DEFAULT_LLM_CAPABILITIES,
          ...(registry.custom_provider.capabilities || {}),
        }
      : DEFAULT_LLM_CAPABILITIES;
  const defaultCustomLimits =
    provider?.provider_type === 'custom'
      ? {
          ...DEFAULT_LLM_LIMITS,
          ...(registry.custom_provider.limits || {}),
        }
      : DEFAULT_LLM_LIMITS;
  const defaultCustomProviderOptions =
    provider?.provider_type === 'custom' ? registry.custom_provider.provider_options_example || {} : {};

  for (const modelId of customModels) {
    if (chatModels.has(modelId)) {
      continue;
    }
    const override = overrides[modelId];
    const capabilities = cloneResolvedCapabilities(defaultCustomCapabilities, override?.capabilities);
    const modalities = defaultChatModalities(capabilities);
    chatModels.set(modelId, {
      id: modelId,
      label: override?.label || modelId,
      description: override?.description || undefined,
      icon: override?.icon || undefined,
      source: 'manual',
      hidden: Boolean(override?.hidden),
      preferred: Boolean(override?.preferred),
      capabilities,
      limits: cloneResolvedLimits(defaultCustomLimits, override?.limits),
      input_modalities: override?.input_modalities || modalities.input,
      output_modalities: override?.output_modalities || modalities.output,
      provider_options_example: override?.provider_options_example || defaultCustomProviderOptions,
    });
  }

  for (const [modelId, override] of Object.entries(overrides)) {
    if (!chatModels.has(modelId) && !override?.capabilities?.embedding) {
      const capabilities = cloneResolvedCapabilities(defaultCustomCapabilities, override?.capabilities);
      const modalities = defaultChatModalities(capabilities);
      chatModels.set(modelId, {
        id: modelId,
        label: override?.label || modelId,
        description: override?.description || undefined,
        icon: override?.icon || undefined,
        source: 'manual',
        hidden: Boolean(override?.hidden),
        preferred: Boolean(override?.preferred),
        capabilities,
        limits: cloneResolvedLimits(defaultCustomLimits, override?.limits),
        input_modalities: override?.input_modalities || modalities.input,
        output_modalities: override?.output_modalities || modalities.output,
        provider_options_example: override?.provider_options_example || defaultCustomProviderOptions,
      });
    }

    if (override?.capabilities?.embedding && !embeddingModels.has(modelId)) {
      const baseChat = chatModels.get(modelId);
      const capabilities = cloneResolvedCapabilities(
        baseChat?.capabilities || {
          vision: false,
          image_output: false,
          tool_calling: false,
          reasoning: false,
          embedding: true,
        },
        override.capabilities
      );
      capabilities.embedding = true;
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
        limits: cloneResolvedLimits(baseChat?.limits, override?.limits),
        input_modalities: override?.input_modalities || modalities.input,
        output_modalities: override?.output_modalities || modalities.output,
        provider_options_example:
          override?.provider_options_example || baseChat?.provider_options_example || defaultCustomProviderOptions,
      });
    }
  }

  return {
    chat_models: Array.from(chatModels.values()),
    embedding_models: Array.from(embeddingModels.values()),
  };
};

export const DEFAULT_SYSTEM_CONFIG: SystemConfig = {
  agent: { name: 'magi-agent', description: 'Magi AI Agent Framework' },
  llm: {
    providers: {
      openai: {
        enabled: false,
        provider_type: 'openai',
        display_name: 'OpenAI',
        api_key: '',
        base_url: '',
      },
    },
    selections: {
      context_decider: {
        provider_id: '',
        model: '',
        embedding_dimension: null,
        capability_override_enabled: false,
        capabilities: DEFAULT_LLM_CAPABILITIES,
        limits: DEFAULT_LLM_LIMITS,
        provider_options: {},
      },
      core: {
        provider_id: '',
        model: '',
        embedding_dimension: null,
        capability_override_enabled: false,
        capabilities: DEFAULT_LLM_CAPABILITIES,
        limits: DEFAULT_LLM_LIMITS,
        provider_options: {},
      },
      embedding: {
        provider_id: '',
        model: '',
        embedding_dimension: null,
        capability_override_enabled: false,
        capabilities: { ...DEFAULT_LLM_CAPABILITIES, embedding: true },
        limits: DEFAULT_LLM_LIMITS,
        provider_options: {},
      },
    },
    model_runtime_overrides: {},
  },
  memory: {
    db_path: '~/.magi/data/memories',
    async_embeddings: true,
    embedding: {
      backend: 'sqlite_vec',
    },
    l0: {
      enabled: true,
      checkpoint_interval_seconds: 30,
      runtime_replay_include_l0_only: false,
    },
    l1: {
      enabled: true,
      retention_days: 7,
      t1_importance_enabled: true,
      vectors_enabled: true,
    },
    l2: {
      enabled: true,
      vectors_enabled: true,
      batch_flush_interval_seconds: 60,
      llm_extraction_enabled: true,
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
    l4: {
      enabled: true,
      vectors_enabled: true,
      skill_extraction_enabled: true,
    },
  },
  preferences: {
    onboarding_completed: false,
    user_mode: null,
    language: 'zh',
    close_to_tray_enabled: true,
    default_chat_workspace_path: null,
  },
  personality: DEFAULT_PERSONALITY_CONFIG,
  tools: {
    builtIn: {
      weather: { enabled: true, provider: 'qweather' },
      webSearch: { enabled: true, provider: 'duckduckgo' },
      webFetch: { enabled: true, usePlaywright: false },
    },
    skills: [],
  },
  timeline: {
    enabled: true,
    expert_mode_edge_override: true,
    sources: {
      chat: {
        enabled: true,
        sync_mode: 'watch',
        sync_interval_minutes: 1,
        default_retention_mode: 'analyze_only',
        storage_mode: 'managed',
        fetch_page_content: false,
        edge_whitelist: ['MENTIONED', 'CARES_ABOUT', 'LIKES', 'DISLIKES', 'INTERACTED_WITH'],
      },
      manual_journal: {
        enabled: true,
        sync_mode: 'manual',
        sync_interval_minutes: 1,
        default_retention_mode: 'retain_raw',
        storage_mode: 'managed',
        fetch_page_content: false,
        edge_whitelist: ['MENTIONED', 'CARES_ABOUT', 'LIKES', 'DISLIKES', 'CREATED', 'RELATED_TO'],
      },
      browser_history: {
        enabled: true,
        sync_mode: 'interval',
        sync_interval_minutes: 30,
        default_retention_mode: 'analyze_only',
        storage_mode: 'managed',
        fetch_page_content: false,
        edge_whitelist: ['VIEWED', 'VISITED', 'CARES_ABOUT', 'LIKES'],
      },
      photo_library: {
        enabled: true,
        sync_mode: 'interval',
        sync_interval_minutes: 60,
        default_retention_mode: 'retain_raw',
        storage_mode: 'external_reference',
        fetch_page_content: false,
        edge_whitelist: ['CAPTURED', 'RELATED_TO', 'INTERACTED_WITH', 'CREATED'],
      },
    },
  },
};

export const configApi = {
  get: () => api.get<SystemConfig>('/config'),
  update: (config: Partial<SystemConfig>) => api.put<SystemConfig>('/config', config),
  getTemplate: () => api.get<SystemConfig>('/config/template'),
  test: (config: Partial<SystemConfig>) => api.post<SystemConfig>('/config/test', config),
  getLLMProviders: () => api.get<LLMProviderRegistry>('/config/llm-providers'),
  discoverLLMProviderModels: (payload: DiscoverLLMProviderModelsRequest) =>
    api.post<DiscoverLLMProviderModelsResponse>('/config/llm/providers/discover-models', payload),
  testLLMProviderConnection: (payload: TestLLMProviderConnectionRequest) =>
    api.post<TestLLMProviderConnectionResponse>('/config/llm/providers/test', payload),
  getOnboardingTemplate: () => api.get<OnboardingTemplateData>('/config/onboarding-template'),
  completeOnboarding: (config: SystemConfig) => api.post<SystemConfig>('/config/onboarding-complete', config),
};

export default configApi;
