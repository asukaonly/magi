/**
 * API modules barrel export.
 */
export { apiClient, api } from './client';
export type { ApiResponse, ApiError, PaginatedResponse } from './client';

export { messagesApi } from './modules/messages';
export type {
  ChatAttachment,
  UserMessageRequest,
  MessageData,
  ConversationHistory,
  ChatHistoryMessage,
  ChatSessionListItem,
  SessionListResponse,
  ExecutionTraceSummary,
  ExecutionTraceNode,
  ExecutionTraceSnapshot,
} from './modules/messages';

export { configApi } from './modules/config';
export type {
  SystemConfig,
  UserPreferences,
  LLMConfig,
  PersonalityConfig as RuntimePersonalityConfig,
  ToolsConfig,
  MemoryConfig,
  TimelineConfig,
  OnboardingStep,
  OnboardingState,
} from './modules/config';

export { personalityApi, DEFAULT_PERSONALITY_CONFIG } from './modules/personality';
export type {
  PersonalityConfig,
  BasicProfile,
  PsychologicalTraits,
  SocialResponses,
  BehavioralStrategies,
  PersonaEntity,
  CachedPhrases,
  StateTransitionProtocolItem,
  AIGenerateRequest,
  PersonalityResponse,
  PersonalityCompareResponse,
  PersonalityDiff,
} from './modules/personality';

export { personalitiesApi } from './modules/personalities';
export type { PersonalityPreset } from './modules/personalities';

export { skillsApi } from './modules/skills';
export type { SkillItem } from './modules/skills';

export { memoryApi } from './modules/memory';
export type { ModelDownloadStatus } from './modules/memory';

export { timelineApi } from './modules/timeline';
export type {
  TimelineContentBlock,
  TimelineEntity,
  TimelineEventDetail,
  TimelineEventRecord,
  TimelineGraphEvidence,
  TimelineManualEntryRequest,
  TimelineProjectionItem,
  TimelineProjectionListResponse,
  TimelineRetentionInfo,
  TimelineSourceStatusItem,
  TimelineSourceStatusResponse,
} from './modules/timeline';
