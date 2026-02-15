/**
 * API模块统一导出
 */
export { apiClient, api } from './client';
export type { ApiResponse, ApiError, PaginatedResponse } from './client';

export { messagesApi } from './modules/messages';
export type { UserMessageRequest, MessageData, SensorStatus, ConversationHistory, ChatHistoryMessage } from './modules/messages';

export { configApi } from './modules/config';
export type { SystemConfig } from './modules/config';

export { personalityApi, DEFAULT_PERSONALITY_CONFIG } from './modules/personality';
export type {
  PersonalityConfig,
  Meta,
  VoiceStyle,
  PsychologicalProfile,
  CoreIdentity,
  SocialProtocols,
  OperationalBehavior,
  CachedPhrases,
  AIGenerateRequest,
  PersonalityResponse,
  PersonalityCompareResponse,
  PersonalityDiff,
} from './modules/personality';
