/**
 * Central type exports for Magi frontend.
 */

// API types
export type {
  ApiResponse,
  ApiError,
  ApiClientError,
  PaginatedResponse,
  ApiRequestConfig,
  ApiPaginationParams,
} from './api';
export { isApiError, isApiClientError, isNetworkError } from './api';

// Chat types
export type {
  ChatMessageKind,
  ChatMessageRole,
  ChatTimelineMessage,
  NormalizedTraceSummary,
  NormalizedTraceNode,
  NormalizedTraceSnapshot,
  ChatSession,
  ChatSessionState,
  AgentResponsePayload,
  PendingTurnPayload,
  ChatHistoryMessageRaw,
  ExecutionTraceNodeRaw,
  ExecutionTraceSnapshotRaw,
} from './chat';

// WebSocket types
export type {
  WSConnectionStatus,
  WSStatus,
  WSSubscribedMessage,
  WSHistoryMessage,
  WSPersonalityInfoMessage,
  WSMessageSentMessage,
  WSExecutionTraceUpdateMessage,
  WSAgentResponseMessage,
  WSErrorMessage,
  ChatHistoryMessageData,
  TraceSummaryData,
  ExecutionTraceUpdateData,
  AgentResponseData,
  WSSubscribeMessage,
  WSGetHistoryMessage,
  WSGetPersonalityMessage,
  WSSendUserMessage,
  WSClientMessage,
  WSServerMessage,
  WSMessageLegacy,
} from './websocket';

// Re-export from realtime client
export type { RealtimeMessage } from '@/realtime/client';

// Re-export API types for convenience
export type { ExecutionTraceSummary } from './api';

// Common types
export type {
  ThemeMode,
  LanguageCode,
  User,
  AsyncStatus,
  AsyncState,
  Result,
  Success,
  Failure,
} from './common';
export {
  SUPPORTED_LANGUAGES,
  createInitialAsyncState,
  success,
  failure,
} from './common';
