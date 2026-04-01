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

export interface WSTurnExecutionControlMessage {
  type: 'turn_execution_control';
  data: TurnExecutionControlData;
}

export interface WSContextUsageMessage {
  type: 'context_usage';
  data: ContextUsageData;
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
  message_id?: string | null;
  message_kind?: string | null;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  turn_id?: string | null;
  kind?: 'user' | 'assistant' | 'status' | null;
  trace_display_mode?: string | null;
  allow_trace_collapse?: boolean;
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
  plan_summary?: {
    planner?: string | null;
    parallel_mode: string;
    total_steps: number;
    remaining_steps: number;
    steps: Array<{
      subtask_id?: string | null;
      label: string;
      status: string;
    }>;
  } | null;
}

export interface ExecutionTraceUpdateData {
  session_id?: string;
  turn_id: string;
  trace_summary?: TraceSummaryData;
  trace_available?: boolean;
}

export interface AgentResponseData {
  message_id?: string | null;
  message_kind?: string | null;
  turn_id?: string;
  content: string;
  trace_summary?: TraceSummaryData;
  trace_available?: boolean;
}

export interface TurnExecutionControlData {
  session_id?: string;
  turn_id: string;
  run_id?: string | null;
  orchestration_id?: string | null;
  state: string;
  can_cancel: boolean;
  label?: string | null;
}

export interface ContextUsageData {
  session_id?: string;
  turn_id?: string;
  used_tokens: number;
  window_size: number;
  threshold: number;
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

export interface WSGetPersonalityMessage {
  type: 'get_personality';
}

export interface WSSendUserMessage {
  type: 'send_message';
  user_id: string;
  session_id: string;
  message: string;
  client_turn_id: string;
}

// ============================================================================
// Union Types
// ============================================================================

export type WSClientMessage =
  | WSSubscribeMessage
  | WSGetHistoryMessage
  | WSGetPersonalityMessage
  | WSSendUserMessage;

export type WSServerMessage =
  | WSSubscribedMessage
  | WSHistoryMessage
  | WSPersonalityInfoMessage
  | WSMessageSentMessage
  | WSExecutionTraceUpdateMessage
  | WSTurnExecutionControlMessage
  | WSContextUsageMessage
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
