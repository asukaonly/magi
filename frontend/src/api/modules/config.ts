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
}

export interface LLMCustomProviderMeta {
  enabled: boolean;
  display_name?: string;
  description?: string;
  icon?: string;
  fields?: Record<string, LLMProviderFieldConfig>;
  capabilities?: LLMCapabilities;
  limits?: LLMLimits;
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
  limits: LLMLimits;
  provider_options_example?: Record<string, any>;
}

export interface LLMEmbeddingModelMeta {
  id: string;
  label?: string;
  dimensions: number[];
  provider_options_example?: Record<string, any>;
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
  log: {
    level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR';
    path?: string;
  };
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
  log: { level: 'INFO' },
  preferences: { onboarding_completed: false, user_mode: null, language: 'zh' },
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
  reset: () => api.post<SystemConfig>('/config/reset', {}),
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
