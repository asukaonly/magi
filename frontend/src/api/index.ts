/**
 * API modules barrel export.
 */
export { apiClient, api } from './client';
export type { ApiResponse, ApiError, PaginatedResponse } from './client';

export { messagesApi } from './modules/messages';
export type {
  ChatAttachment,
  ChatMessageLabel,
  ChatReplyPreview,
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

export { personasApi, DEFAULT_PERSONALITY_CONFIG } from './modules/personas';
export type {
  PersonaSummary,
  PersonaDetail,
  SeedPreview,
  PersonalityConfig,
  BasicProfile,
  CoreIdentity,
  PersonaEntity,
  StateTransitionProtocolItem,
  AIGenerateRequest,
} from './modules/personas';

export { skillsApi } from './modules/skills';
export type { SkillItem } from './modules/skills';

export { memoryApi } from './modules/memory';
export type { ModelDownloadStatus } from './modules/memory';

export { sensorsApi } from './modules/sensors';
export type {
  SensorSourceAuthorizationResponse,
  SensorSourceStatusItem,
  SensorSourceStatusResponse,
} from './modules/sensors';

export { timelineApi } from './modules/timeline';
export type {
  TimelineClusterBlock,
  TimelineContextBundle,
  TimelineOverview,
  TimelineRawEvent,
  TimelineReflectionWindow,
  TimelineSourceMixItem,
  TimelineStateChange,
  TimelineStateBand,
  TimelineStateMarker,
  TimelineStateSummary,
  TimelineAnchor,
  TimelineThemeCard,
  TimelineViewportResponse,
} from './modules/timeline';

export { backgroundTasksApi } from './modules/backgroundTasks';
export type {
  BackgroundTaskDTO,
  BackgroundTaskEventDTO,
  BackgroundTaskSpecDTO,
  BackgroundTaskStatus,
  BackgroundTaskTriggerSource,
  CancelBackgroundTaskResponse,
  DismissBackgroundTaskResponse,
  GetBackgroundTaskResponse,
  ListBackgroundTasksParams,
  ListBackgroundTasksResponse,
  RetryBackgroundTaskResponse,
} from './modules/backgroundTasks';

export * as controlApi from './modules/control';
export type {
  AskStateDTO,
  ControlSettingsDTO,
  PendingPermissionDTO,
  PermissionMode,
  PermissionOutcome,
  PermissionRespondInput,
  PermissionRuleDTO,
  PermissionScope,
  PlanStateDTO,
  SessionControlOverrideDTO,
  SessionSettingsBundleDTO,
  SessionSettingsUpdateInput,
  TodoItemDTO,
  TodoStatus,
} from './modules/control';
