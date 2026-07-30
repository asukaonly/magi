/**
 * API modules barrel export.
 */
export { apiClient, api } from './client';
export type { ApiResponse, ApiError, PaginatedResponse } from './client';

export { messagesApi } from './modules/messages';
export type {
  ChatAttachment,
  ChatMessageLabel,
  ChatRunState,
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
  LayerModifierKey,
  LayerModifiers,
  PersonaSummary,
  PersonaDetail,
  SeedPreview,
  PersonalityConfig,
  IdentityCore,
  Idiolect,
  PersonaRegister,
  SignatureTrigger,
  QuietHour,
  PersonaLayerItem,
  AIGenerateRequest,
} from './modules/personas';

export { skillsApi } from './modules/skills';
export type { SkillItem } from './modules/skills';

export { hooksApi } from './modules/hooks';
export type { HookEntry, HooksListResponse } from './modules/hooks';

export { memoryApi } from './modules/memory';
export { historyImportsApi } from './modules/historyImports';
export type {
  HistoryImportDetectedKind,
  HistoryImportJob,
  HistoryImportParticipant,
  HistoryImportRecordPreview,
  HistoryImportSourceSummary,
  HistoryImportStatus,
} from './modules/historyImports';
export type {
  MemoryCorrectionCommandResponse,
  MemoryCorrectionHistoryResponse,
  MemoryCorrectionKind,
  MemoryCorrectionRecord,
  MemoryCorrectionRequest,
  MemoryCorrectionTarget,
  MemoryCorrectionTargetKind,
  ModelDownloadStatus,
} from './modules/memory';

export { profileApi } from './modules/profile';
export type { UserProfilePatch, UserProfileProjection } from './modules/profile';

export { sensorsApi } from './modules/sensors';
export type {
  SensorSourceAuthorizationResponse,
  SensorSourceStatusItem,
  SensorSourceStatusResponse,
  SensorTodaySummaryEntry,
  SensorTodaySummaryResponse,
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

export { schedulesApi } from './modules/schedules';
export type {
  CancelScheduleActivityResponse,
  ListScheduleActivityResponse,
  ListSchedulesResponse,
  RunScheduleResponse,
  ScheduleActivityDTO,
  ScheduleActivityStatus,
  ScheduleDTO,
  ScheduledExecutionResultDTO,
  ScheduleSettingsLinkDTO,
  ScheduleTargetStateDTO,
  ScheduleTargetType,
  ScheduleTriggerDTO,
  ScheduleTriggerType,
  UpdateScheduleRequest,
  UpdateScheduleResponse,
} from './modules/schedules';

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

export { mcpApi } from './modules/mcp';
export type {
  MCPHttpTransport,
  MCPResource,
  MCPRuntime,
  MCPServerCreatePayload,
  MCPServerLogs,
  MCPServerState,
  MCPServerStatus,
  MCPStdioTransport,
  MCPTransport,
  MCPTransportKind,
} from './modules/mcp';

export { commandsApi } from './modules/commands';
export type {
  CommandDescriptor,
  CommandParameter,
  CommandParameterType,
  ExpandSkillRequest,
  ExpandSkillResponse,
  RunCommandRequest,
  RunCommandResponse,
  RunSkillAsBackgroundRequest,
  RunSkillAsBackgroundResponse,
  SkillCommandDescriptor,
} from './modules/commands';
