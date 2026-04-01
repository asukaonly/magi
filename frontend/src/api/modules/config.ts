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
  provider_type?: LLMProvider | string;
  source?: 'builtin' | 'custom';
  display_name?: string;
  description?: string;
  icon?: string;
  default_model?: string;
  default_classify_model?: string;
  default_base_url?: string;
  api_format?: ApiFormat;
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

export interface LLMProviderCatalog {
  providers: LLMProviderMeta[];
}

export interface LLMProviderCatalogResolveRequest {
  providers: Record<string, LLMProviderConfig>;
}

export interface LLMCustomProviderTemplateData {
  template: LLMCustomProviderMeta;
  defaults: LLMProviderConfig;
}

export interface OnboardingTemplateData {
  config: SystemConfig;
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

export type MemoryRerankerBackend = 'heuristic' | 'llm';
export type MemoryRerankerMode = 'local' | 'remote';
export type MemoryRerankerLayer = 'L1' | 'L3' | 'L4';
export type MemoryRerankerLocalModelSource = 'managed' | 'external';

export interface MemoryRerankerLocalConfig {
  model_source: MemoryRerankerLocalModelSource;
  managed_model_id: string | null;
  model_file_path: string | null;
  max_context_tokens: number;
}

export interface MemoryRerankerRemoteConfig {
  provider_id: string;
  model: string;
}

export interface MemoryRerankerConfig {
  enabled: boolean;
  backend: MemoryRerankerBackend;
  mode: MemoryRerankerMode;
  layers: MemoryRerankerLayer[];
  top_k: number;
  timeout_seconds: number;
  candidate_max_chars: number;
  local: MemoryRerankerLocalConfig;
  remote: MemoryRerankerRemoteConfig;
}

export type EmbeddingMode = 'remote' | 'local';
export type LocalEmbeddingModelSource = 'managed' | 'external';

export interface LocalEmbeddingConfig {
  model_source: LocalEmbeddingModelSource;
  managed_model_id: string | null;
  model_dir_path: string | null;
  idle_timeout_seconds: number;
}

export interface EmbeddingConfig {
  mode: EmbeddingMode;
  local: LocalEmbeddingConfig;
}

export interface MemoryConfig {
  db_path?: string;
  embedding: EmbeddingConfig;
  reranker: MemoryRerankerConfig;
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
  sources: {
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

export interface ResolvedProviderModels {
  chat_models: LLMResolvedChatModelMeta[];
  embedding_models: LLMResolvedEmbeddingModelMeta[];
}

export const resolveProviderModels = (
  registry: LLMProviderRegistry,
  providerId: string,
  _provider?: LLMProviderConfig
): ResolvedProviderModels => {
  const resolvedProviderMeta = registry.providers.find((item) => item.id === providerId);
  return {
    chat_models: [...(resolvedProviderMeta?.resolved_chat_models || [])],
    embedding_models: [...(resolvedProviderMeta?.resolved_embedding_models || [])],
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
    embedding: {
      mode: 'remote',
      local: {
        model_source: 'managed',
        managed_model_id: null,
        model_dir_path: null,
        idle_timeout_seconds: 1800,
      },
    },
    reranker: {
      enabled: false,
      backend: 'heuristic',
      mode: 'local',
      layers: ['L1', 'L3'],
      top_k: 8,
      timeout_seconds: 0.8,
      candidate_max_chars: 500,
      local: {
        model_source: 'managed',
        managed_model_id: null,
        model_file_path: null,
        max_context_tokens: 2048,
      },
      remote: {
        provider_id: '',
        model: '',
      },
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
    default_chat_workspace_path: '~/.magi/chat-workspace',
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
    sources: {
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
  getLLMProviderCatalog: () => api.get<LLMProviderCatalog>('/llm/providers/catalog'),
  resolveLLMProviderCatalog: (payload: LLMProviderCatalogResolveRequest) =>
    api.post<LLMProviderCatalog>('/llm/providers/catalog', payload),
  getLLMCustomProviderTemplate: () => api.get<LLMCustomProviderTemplateData>('/llm/providers/custom-template'),
  discoverLLMProviderModels: (payload: DiscoverLLMProviderModelsRequest) =>
    api.post<DiscoverLLMProviderModelsResponse>('/llm/providers/discover-models', payload),
  testLLMProviderConnection: (payload: TestLLMProviderConnectionRequest) =>
    api.post<TestLLMProviderConnectionResponse>('/llm/providers/test', payload),
  getOnboardingTemplate: () => api.get<OnboardingTemplateData>('/config/onboarding-template'),
  completeOnboarding: (config: SystemConfig) => api.post<SystemConfig>('/config/onboarding-complete', config),
};

export default configApi;
