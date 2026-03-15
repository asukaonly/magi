/**
 * WebSocket message types for Magi real-time communication.
 */

// ============================================================================
// Base Types
// ============================================================================

export type WSConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'reconnecting';

export interface WSStatus {
  connected: boolean;
  reconnectAttempts: number;
  lastError: string | null;
}

// ============================================================================
// Message Types (Server -> Client)
// ============================================================================

export interface WSSubscribedMessage {
  type: 'subscribed';
  channel?: string;
  sid?: string;
}

export interface WSCurrentSessionMessage {
  type: 'current_session';
  data: {
    session_id: string;
  };
}

export interface WSHistoryMessage {
  type: 'history';
  data: {
    session_id: string;
    messages: ChatHistoryMessageData[];
  };
}

export interface WSPersonalityInfoMessage {
  type: 'personality_info';
  data: {
    name: string;
    avatar?: string;
    greeting?: string;
  };
}

export interface WSMessageSentMessage {
  type: 'message_sent';
  data: {
    session_id: string;
    turn_id?: string;
  };
}

export interface WSExecutionTraceUpdateMessage {
  type: 'execution_trace_update';
  data: ExecutionTraceUpdateData;
}

export interface WSAgentResponseMessage {
  type: 'agent_response';
  data: AgentResponseData;
}

export interface WSErrorMessage {
  type: 'error';
  message: string;
  code?: string;
  data?: unknown;
}

// ============================================================================
// Message Data Types
// ============================================================================

export interface ChatHistoryMessageData {
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  turn_id?: string | null;
  kind?: 'user' | 'assistant' | 'status' | null;
  trace_summary?: TraceSummaryData | null;
  trace_available?: boolean;
}

export interface TraceSummaryData {
  turn_id: string;
  mode: string;
  status: string;
  headline: string;
  active_steps: number;
  completed_steps: number;
  failed_steps: number;
  duration_seconds: number;
  trace_available: boolean;
  orchestration_id?: string | null;
}

export interface ExecutionTraceUpdateData {
  session_id?: string;
  turn_id: string;
  trace_summary?: TraceSummaryData;
}

export interface AgentResponseData {
  turn_id?: string;
  response?: string;
  trace_summary?: TraceSummaryData;
}

// ============================================================================
// Client Message Types (Client -> Server)
// ============================================================================

export interface WSSubscribeMessage {
  type: 'subscribe';
  channel: string;
}

export interface WSGetHistoryMessage {
  type: 'get_history';
  session_id: string;
}

export interface WSGetCurrentSessionMessage {
  type: 'get_current_session';
}

export interface WSGetPersonalityMessage {
  type: 'get_personality';
}

export interface WSSendUserMessage {
  type: 'send_message';
  user_id: string;
  session_id: string | null;
  message: string;
  client_turn_id: string;
}

// ============================================================================
// Union Types
// ============================================================================

export type WSClientMessage =
  | WSSubscribeMessage
  | WSGetHistoryMessage
  | WSGetCurrentSessionMessage
  | WSGetPersonalityMessage
  | WSSendUserMessage;

export type WSServerMessage =
  | WSSubscribedMessage
  | WSCurrentSessionMessage
  | WSHistoryMessage
  | WSPersonalityInfoMessage
  | WSMessageSentMessage
  | WSExecutionTraceUpdateMessage
  | WSAgentResponseMessage
  | WSErrorMessage;

// Legacy compatibility type (to be removed after migration)
export interface WSMessageLegacy {
  type?: string;
  data?: unknown;
  event?: string;
  channel?: string;
  sid?: string;
  message?: string;
  [key: string]: unknown;
}
