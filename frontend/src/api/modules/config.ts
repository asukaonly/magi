/**
 * Config management API and type definitions.
 */
import { api, unwrapGatewayPayload, type GatewayResponse } from '../client';
import type { PersonalityConfig } from './personas';
import { DEFAULT_PERSONALITY_CONFIG } from './personas';

export interface PersonalitySettingsConfig {
  state_memory_enabled: boolean;
  state_transition_enabled: boolean;
  deep_persona_enabled: boolean;
}

export const DEFAULT_PERSONALITY_SETTINGS_CONFIG: PersonalitySettingsConfig = {
  state_memory_enabled: true,
  state_transition_enabled: true,
  deep_persona_enabled: true,
};

export type UserMode = 'quick' | 'expert' | null;
export type LanguageCode = 'zh' | 'en';
export type ConversationRhythmMode = 'off' | 'natural' | 'expressive';
export type LLMProvider =
  | 'openai'
  | 'anthropic'
  | 'glm'
  | 'gemini'
  | 'grok'
  | 'deepseek'
  | 'dashscope'
  | 'kimi'
  | 'minimax'
  | 'xiaomimimo'
  | 'custom'
  | 'local';
export type ApiFormat = 'openai' | 'anthropic';
export type LLMScenario = 'auxiliary' | 'core' | 'memory_summarizer' | 'embedding' | 'image_generation';

export interface UserPreferences {
  onboarding_completed: boolean;
  first_conversation_completed: boolean;
  product_tour_completed: boolean;
  user_mode: UserMode;
  scenario?: string | null;
  language: LanguageCode;
  close_to_tray_enabled: boolean;
  desktop_notifications_enabled: boolean;
  desktop_notification_previews_enabled: boolean;
  auto_start_enabled: boolean;
  start_minimized: boolean;
  skip_quit_confirmation: boolean;
  default_chat_workspace_path: string | null;
  streaming_chat_enabled: boolean;
  conversation_rhythm_enabled: boolean;
  conversation_rhythm_mode: ConversationRhythmMode;
  allow_media_grounding_for_conversation: boolean;
  allow_interjection: boolean;
  allow_ask_in_background: boolean;
}

export interface AgentBackgroundTasksConfig {
  auto_detect_long_task: boolean;
}

export interface AgentConfig {
  name: string;
  description?: string;
  background_tasks: AgentBackgroundTasksConfig;
}

export type ProxyType = 'http' | 'socks5';

export interface NetworkProxyConfig {
  enabled: boolean;
  proxy_type: ProxyType;
  host: string;
  port: number;
  username: string;
  password: string;
}

export interface DiagnosticsConfig {
  full_content_logging_enabled: boolean;
}

export interface LLMProviderConfig {
  enabled: boolean;
  provider_type: LLMProvider;
  display_name: string;
  provider_plan?: string | null;
  api_key?: string;
  base_url?: string;
  services: LLMProviderServicesConfig;
  api_format?: ApiFormat;
  custom_models?: string[];
  custom_default_model?: string;
  model_metadata_overrides?: Record<string, LLMModelMetadataOverride>;
}

export interface LLMProviderConnectionConfig {
  enabled: boolean;
  api_key?: string;
  base_url?: string;
}

export interface LLMProviderImageGenerationConfig extends LLMProviderConnectionConfig {
  timeout?: number;
  native_protocol?: string | null;
}

export interface LLMProviderTTSConfig extends LLMProviderConnectionConfig {
  model?: string | null;
  voice?: string | null;
  response_format?: string | null;
}

export interface LLMProviderServicesConfig {
  chat: LLMProviderConnectionConfig;
  embedding: LLMProviderConnectionConfig;
  image_generation: LLMProviderImageGenerationConfig;
  tts: LLMProviderTTSConfig;
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
}

export interface LLMModelCost {
  currency: string;
  input_per_million_tokens?: number | null;
  cached_input_per_million_tokens?: number | null;
  cache_write_per_million_tokens?: number | null;
  output_per_million_tokens?: number | null;
  per_image?: number | null;
  source?: string | null;
  source_note?: string | null;
}

export type ModelVendor =
  | 'openai'
  | 'deepseek'
  | 'anthropic'
  | 'glm'
  | 'dashscope'
  | 'grok'
  | 'kimi'
  | 'minimax'
  | 'generic';

export interface LLMModelMetadataOverride {
  label?: string | null;
  description?: string | null;
  icon?: string | null;
  vendor?: ModelVendor | null;
  capabilities?: LLMCapabilityOverrides;
  limits?: LLMLimitsOverride;
  input_modalities?: string[] | null;
  output_modalities?: string[] | null;
  provider_options_example?: Record<string, any> | null;
  cost?: LLMModelCost | null;
  hidden?: boolean | null;
  preferred?: boolean | null;
  source_note?: string | null;
  dimensions?: number[] | null;
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
  provider_plan?: string | null;
  plans?: LLMProviderPlanMeta[];
  api_format?: ApiFormat;
  chat_models?: LLMChatModelMeta[];
  embedding_models?: LLMEmbeddingModelMeta[];
  image_generation_models?: LLMGenerationModelMeta[];
  audio_generation_models?: LLMGenerationModelMeta[];
  fields?: Record<string, LLMProviderFieldConfig>;
  resolved_chat_models?: LLMResolvedChatModelMeta[];
  resolved_embedding_models?: LLMResolvedEmbeddingModelMeta[];
  resolved_image_generation_models?: LLMResolvedImageGenerationModelMeta[];
}

export interface LLMProviderPlanMeta {
  id: string;
  display_name?: string | null;
  description?: string | null;
  icon?: string | null;
  default_model?: string | null;
  default_classify_model?: string | null;
  default_base_url?: string | null;
  allowed_scenarios?: string[] | null;
  endpoints?: LLMProviderPlanEndpointMeta[];
  chat_models?: LLMChatModelMeta[] | null;
  embedding_models?: LLMEmbeddingModelMeta[] | null;
  image_generation_models?: LLMGenerationModelMeta[] | null;
  audio_generation_models?: LLMGenerationModelMeta[] | null;
  fields?: Record<string, LLMProviderFieldConfig> | null;
}

export interface LLMProviderPlanEndpointMeta {
  id: string;
  label: string;
  country?: string | null;
  base_url: string;
  api_format?: ApiFormat | string | null;
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
  vendor?: ModelVendor;
  capabilities: LLMChatCapabilities;
  limits: LLMLimits;
  cost?: LLMModelCost | null;
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

export interface LLMResolvedImageGenerationModelMeta {
  id: string;
  label?: string;
  description?: string;
  icon?: string;
  source: LLMResolvedModelSource;
  hidden: boolean;
  preferred: boolean;
  capabilities: LLMCapabilities;
  limits: LLMLimits;
  input_modalities: string[];
  output_modalities: string[];
  provider_options_example?: Record<string, any>;
  cost?: LLMModelCost | null;
  supported_sizes?: string[];
  supported_qualities?: string[];
  supports_seed?: boolean;
  supports_negative_prompt?: boolean;
  supports_reference?: boolean;
  max_n?: number;
  native_protocol?: string;
}

export interface LLMEmbeddingModelMeta {
  id: string;
  label?: string;
  dimensions: number[];
  limits?: LLMLimits;
  cost?: LLMModelCost | null;
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
  cost?: LLMModelCost | null;
  provider_options_example?: Record<string, any>;
  supported_sizes?: string[];
  supported_qualities?: string[];
  supports_seed?: boolean;
  supports_negative_prompt?: boolean;
  supports_reference?: boolean;
  max_n?: number;
  native_protocol?: string;
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
  provider: 'openmeteo' | 'qweather';
  apiKey?: string;
  apiUrl?: string;
}

export interface WebSearchToolConfig {
  enabled: boolean;
  provider: 'duckduckgo' | 'brave' | 'perplexity' | 'searxng' | 'tavily';
  apiKey?: string;
  apiUrl?: string;
}

export interface WebFetchToolConfig {
  enabled: boolean;
  allowRfc2544BenchmarkRange: boolean;
  allowPrivateNetworkFetch?: boolean;
  privateNetworkAllowlist?: string[];
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
  attention_update_turn_threshold: number;
  attention_update_idle_seconds: number;
  attention_update_max_delay_seconds: number;
}

export interface MemoryL1Config {
  enabled: boolean;
  retention_days: number;
  vectors_enabled: boolean;
}

export interface MemoryL2Config {
  enabled: boolean;
  vectors_enabled: boolean;
  batch_flush_interval_seconds: number;
  auto_extract_relations: boolean;
  shadow_conflict_notification_enabled: boolean;
  portrait_projection_refresh_delay_seconds: number;
}

export interface MemoryL3Config {
  enabled: boolean;
  retention_days: number;
  vectors_enabled: boolean;
  llm_summary_enabled: boolean;
  temporal_llm_timeout_seconds: number;
  temporal_llm_min_event_count: number;
  summary_interval_minutes: number;
}

export interface MemoryL4Config {
  enabled: boolean;
  vectors_enabled: boolean;
  inactive_skill_retention_days: number;
  inactive_skill_min_attempts: number;
}

export interface CrossEncoderConfig {
  enabled: boolean;
  managed_model_id: string | null;
  variant: string | null;
}

export interface MemoryRerankerConfig {
  top_k: number;
  cross_encoder: CrossEncoderConfig;
}

export interface QueryExpansionConfig {
  enabled: boolean;
  max_expansions: number;
}

export interface GraphSpreadingConfig {
  enabled: boolean;
}

export type EmbeddingMode = 'off' | 'remote' | 'local';
export type LocalEmbeddingModelSource = 'managed' | 'external';

export interface LocalEmbeddingConfig {
  model_source: LocalEmbeddingModelSource;
  managed_model_id: string | null;
  model_dir_path: string | null;
  idle_timeout_seconds: number;
  variant: string | null;
}

export interface EmbeddingConfig {
  mode: EmbeddingMode;
  local: LocalEmbeddingConfig;
}

export interface MemoryConfig {
  db_path?: string;
  retention_days: number;
  history_behavior: 'delete' | 'archive';
  archive_path?: string | null;
  embedding: EmbeddingConfig;
  reranker: MemoryRerankerConfig;
  query_expansion: QueryExpansionConfig;
  graph_spreading: GraphSpreadingConfig;
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
    calendar?: TimelineSourceConfig;
    chrome_history?: TimelineSourceConfig;
    git_activity?: TimelineSourceConfig;
    screen_time?: TimelineSourceConfig;
    terminal_history?: TimelineSourceConfig;
    netease_music?: TimelineSourceConfig;
    [key: string]: TimelineSourceConfig | undefined;
  };
}

export interface SystemConfig {
  agent: AgentConfig;
  llm: LLMConfig;
  memory: MemoryConfig;
  preferences: UserPreferences;
  network: NetworkProxyConfig;
  diagnostics: DiagnosticsConfig;
  personality: PersonalityConfig;
  personalitySettings: PersonalitySettingsConfig;
  tools: ToolsConfig;
  timeline: TimelineConfig;
}

export type VectorLayerId = 'l1' | 'l2_entities' | 'l2_edges' | 'l3' | 'l4';
export type EmbeddingPreflightSeverity = 'none' | 'soft' | 'strong';

export interface EmbeddingVectorIdentity {
  layer: VectorLayerId;
  mode: EmbeddingMode;
  text_builder_version: string;
  hard_key: string;
  label: string;
  dimension: number | null;
  identity_known: boolean;
  provenance: Record<string, string | number | null>;
}

export interface EmbeddingConfigPreflightWarning {
  layer: VectorLayerId;
  severity: 'soft' | 'strong';
  reason: 'hard_identity_changed' | 'remote_provider_changed' | 'vector_availability_changed' | string;
  ready_count: number;
  current: EmbeddingVectorIdentity | null;
  proposed: EmbeddingVectorIdentity | null;
}

export interface EmbeddingConfigPreflight {
  severity: EmbeddingPreflightSeverity;
  requires_rebuild: boolean;
  ready_counts: Record<VectorLayerId, number>;
  ready_total: number;
  warnings: EmbeddingConfigPreflightWarning[];
  current_identities: Record<VectorLayerId, EmbeddingVectorIdentity | null>;
  proposed_identities: Record<VectorLayerId, EmbeddingVectorIdentity | null>;
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

export interface OnboardingConfigUpdate {
  language: LanguageCode;
  llm: LLMConfig;
}

export interface OnboardingStatus {
  completed: boolean;
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

export const DEFAULT_LLM_CUSTOM_PROVIDER_META: LLMCustomProviderMeta = {
  enabled: true,
  display_name: 'Custom Provider',
  fields: {
    custom_name: { visible: true, required: true },
    api_format: { visible: true, required: true, options: ['openai', 'anthropic'] },
    model: { visible: true, required: true },
    api_key: { visible: true, required: true },
    base_url: { visible: true, required: false },
  },
  capabilities: DEFAULT_LLM_CAPABILITIES,
  limits: DEFAULT_LLM_LIMITS,
  provider_options_example: {},
};

export interface ResolvedProviderModels {
  chat_models: LLMResolvedChatModelMeta[];
  embedding_models: LLMResolvedEmbeddingModelMeta[];
  image_generation_models: LLMResolvedImageGenerationModelMeta[];
}

export const resolveProviderModels = (
  registry: LLMProviderRegistry,
  providerId: string,
  provider?: LLMProviderConfig
): ResolvedProviderModels => {
  const resolvedProviderMeta =
    registry.providers.find((item) => item.id === providerId) ||
    registry.providers.find((item) => item.id === provider?.provider_type);
  return {
    chat_models: [...(resolvedProviderMeta?.resolved_chat_models || [])],
    embedding_models: [...(resolvedProviderMeta?.resolved_embedding_models || [])],
    image_generation_models: [...(resolvedProviderMeta?.resolved_image_generation_models || [])],
  };
};

const unwrapConfigResponse = <T>(response: GatewayResponse<T>): T => unwrapGatewayPayload<T>(response);

export const DEFAULT_SYSTEM_CONFIG: SystemConfig = {
  agent: {
    name: 'magi-agent',
    description: 'Magi AI Agent Framework',
    background_tasks: {
      auto_detect_long_task: false,
    },
  },
  llm: {
    providers: {},
    selections: {
      auxiliary: {
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
      memory_summarizer: {
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
      image_generation: {
        provider_id: '',
        model: '',
        embedding_dimension: null,
        capability_override_enabled: false,
        capabilities: { ...DEFAULT_LLM_CAPABILITIES, image_output: true },
        limits: DEFAULT_LLM_LIMITS,
        provider_options: {},
      },
    },
    model_runtime_overrides: {},
  },
  memory: {
    db_path: '~/.magi/data/memories',
    embedding: {
      mode: 'off',
      local: {
        model_source: 'managed',
        managed_model_id: null,
        model_dir_path: null,
        idle_timeout_seconds: 1800,
        variant: null,
      },
    },
    reranker: {
      top_k: 8,
      cross_encoder: {
        enabled: false,
        managed_model_id: null,
        variant: null,
      },
    },
    query_expansion: {
      enabled: true,
      max_expansions: 2,
    },
    graph_spreading: {
      enabled: true,
    },
    retention_days: 90,
    history_behavior: 'delete',
    archive_path: '~/.magi/data/memory/archive',
    l0: {
      enabled: true,
      checkpoint_interval_seconds: 30,
      attention_update_turn_threshold: 3,
      attention_update_idle_seconds: 30,
      attention_update_max_delay_seconds: 90,
    },
    l1: {
      enabled: true,
      retention_days: 30,
      vectors_enabled: true,
    },
    l2: {
      enabled: true,
      vectors_enabled: true,
      batch_flush_interval_seconds: 60,
      auto_extract_relations: true,
      shadow_conflict_notification_enabled: true,
      portrait_projection_refresh_delay_seconds: 120,
    },
    l3: {
      enabled: true,
      retention_days: 180,
      vectors_enabled: true,
      llm_summary_enabled: true,
      temporal_llm_timeout_seconds: 3.0,
      temporal_llm_min_event_count: 2,
      summary_interval_minutes: 60,
    },
    l4: {
      enabled: true,
      vectors_enabled: true,
      inactive_skill_retention_days: 30,
      inactive_skill_min_attempts: 5,
    },
  },
  preferences: {
    onboarding_completed: false,
    first_conversation_completed: false,
    product_tour_completed: false,
    user_mode: null,
    scenario: null,
    language: 'zh',
    close_to_tray_enabled: true,
    desktop_notifications_enabled: true,
    desktop_notification_previews_enabled: true,
    auto_start_enabled: false,
    start_minimized: false,
    skip_quit_confirmation: false,
    default_chat_workspace_path: '~/.magi/chat-workspace',
    streaming_chat_enabled: false,
    conversation_rhythm_enabled: true,
    conversation_rhythm_mode: 'natural',
    allow_media_grounding_for_conversation: true,
    allow_interjection: false,
    allow_ask_in_background: false,
  },
  network: {
    enabled: false,
    proxy_type: 'http',
    host: '127.0.0.1',
    port: 7890,
    username: '',
    password: '',
  },
  diagnostics: {
    full_content_logging_enabled: true,
  },
  personality: DEFAULT_PERSONALITY_CONFIG,
  personalitySettings: DEFAULT_PERSONALITY_SETTINGS_CONFIG,
  tools: {
    builtIn: {
      weather: { enabled: true, provider: 'openmeteo' },
      webSearch: { enabled: true, provider: 'duckduckgo' },
      webFetch: {
        enabled: true,
        allowRfc2544BenchmarkRange: true,
        allowPrivateNetworkFetch: false,
        privateNetworkAllowlist: [],
      },
    },
    skills: [],
  },
  timeline: {
    sources: {
      photo_library: {
        enabled: false,
        sync_mode: 'manual',
        sync_interval_minutes: 60,
        default_retention_mode: 'analyze_only',
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
  updateLanguagePreference: (language: LanguageCode) =>
    api.put<SystemConfig>('/config/preferences/language', { language }),
  embeddingPreflight: async (config: Partial<SystemConfig>): Promise<EmbeddingConfigPreflight> =>
    unwrapConfigResponse(await api.post<EmbeddingConfigPreflight>('/config/embedding-preflight', config)),
  getTemplate: () => api.get<SystemConfig>('/config/template'),
  test: (config: Partial<SystemConfig>) => api.post<SystemConfig>('/config/test', config),
  getLLMProviderCatalog: async (): Promise<LLMProviderCatalog> =>
    unwrapConfigResponse(await api.get<LLMProviderCatalog>('/llm/providers/catalog')),
  resolveLLMProviderCatalog: async (payload: LLMProviderCatalogResolveRequest): Promise<LLMProviderCatalog> =>
    unwrapConfigResponse(await api.post<LLMProviderCatalog>('/llm/providers/catalog', payload)),
  getLLMCustomProviderTemplate: async (): Promise<LLMCustomProviderTemplateData> =>
    unwrapConfigResponse(await api.get<LLMCustomProviderTemplateData>('/llm/providers/custom-template')),
  discoverLLMProviderModels: async (payload: DiscoverLLMProviderModelsRequest): Promise<DiscoverLLMProviderModelsResponse> =>
    unwrapConfigResponse(await api.post<DiscoverLLMProviderModelsResponse>('/llm/providers/discover-models', payload)),
  testLLMProviderConnection: async (payload: TestLLMProviderConnectionRequest): Promise<TestLLMProviderConnectionResponse> =>
    unwrapConfigResponse(await api.post<TestLLMProviderConnectionResponse>('/llm/providers/test', payload)),
  getOnboardingStatus: () => api.get<OnboardingStatus>('/config/onboarding-status'),
  getOnboardingTemplate: () => api.get<OnboardingTemplateData>('/config/onboarding-template'),
  updateOnboardingDraft: (config: OnboardingConfigUpdate) =>
    api.put<SystemConfig>('/config/onboarding-draft', config),
  completeOnboarding: (config: OnboardingConfigUpdate) =>
    api.post<SystemConfig>('/config/onboarding-complete', config),
  testTelegramConnection: (payload: { bot_token: string; proxy?: string }) =>
    api.post<{ success: boolean; message: string; bot_username?: string; bot_id?: number }>(
      '/config/channels/telegram/test',
      payload,
    ),
};

export default configApi;
