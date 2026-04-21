/**
 * Chat domain types for Magi.
 */

// ============================================================================
// Event Data Types (shared between Tauri events and API responses)
// ============================================================================

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

// ============================================================================
// Chat Message Types
// ============================================================================

export type ChatMessageKind = 'user' | 'assistant' | 'status';
export type ChatMessageRole = 'user' | 'assistant';

export interface ChatTimelineMessage {
  id: string;
  role: ChatMessageRole;
  kind: ChatMessageKind;
  content: string;
  timestamp: number;
  messageId?: string;
  messageKind?: string | null;
  turnId?: string;
  traceSummary?: NormalizedTraceSummary | null;
  traceAvailable?: boolean;
  payload?: Record<string, unknown> | null;
}

// ============================================================================
// Normalized Types (frontend-optimized)
// ============================================================================

export interface NormalizedTraceSummary {
  turnId: string;
  mode: string;
  status: string;
  headline: string;
  activeSteps: number;
  completedSteps: number;
  failedSteps: number;
  durationSeconds: number;
  traceAvailable: boolean;
  orchestrationId?: string | null;
  planSummary?: {
    planner?: string | null;
    parallelMode: string;
    totalSteps: number;
    remainingSteps: number;
    steps: Array<{
      subtaskId?: string | null;
      label: string;
      status: string;
    }>;
  } | null;
  continuedFromTurnId?: string | null;
  continuedFromTraceId?: string | null;
  supersededByTurnId?: string | null;
  supersessionReason?: string | null;
}

export interface NormalizedTraceNode {
  id: string;
  kind: string;
  label: string;
  status: string;
  startedAt?: number | null;
  endedAt?: number | null;
  resultPreview?: string;
  error?: string | null;
  metadata: Record<string, unknown>;
  children: NormalizedTraceNode[];
}

export interface NormalizedTraceSnapshot {
  turnId: string;
  userId: string;
  sessionId: string;
  status: string;
  mode: string;
  orchestrationId?: string | null;
  startedAt?: number | null;
  endedAt?: number | null;
  continuedFromTurnId?: string | null;
  continuedFromTraceId?: string | null;
  supersededByTurnId?: string | null;
  supersessionReason?: string | null;
  summary: NormalizedTraceSummary;
  root: NormalizedTraceNode;
}

// ============================================================================
// Session Types
// ============================================================================

export interface ChatSession {
  sessionId: string;
  title: string;
  lastMessagePreview: string;
  lastTimestamp: number;
  messageCount: number;
}

export interface ChatSessionState {
  currentSessionId: string | null;
  orderedSessionIds: string[];
  sessionsById: Record<string, ChatSession>;
  messagesBySession: Record<string, ChatTimelineMessage[]>;
  unreadBySession: Record<string, number>;
}

// ============================================================================
// Payload Types (for store actions)
// ============================================================================

export interface AgentResponsePayload {
  sessionId: string;
  content: string;
  timestamp: number;
  messageId?: string;
  messageKind?: string | null;
  turnId?: string;
  traceSummary?: NormalizedTraceSummary | null;
  traceAvailable?: boolean;
}

export interface PendingTurnPayload {
  sessionId: string;
  input: string;
  turnId: string;
  timestamp: number;
  pendingLabel: string;
}

// ============================================================================
// API Response Types (raw from backend)
// ============================================================================

export interface ChatHistoryMessageRaw {
  message_id?: string | null;
  message_kind?: string | null;
  role: ChatMessageRole;
  content: string;
  timestamp: number;
  turn_id?: string | null;
  kind?: ChatMessageKind | null;
  trace_display_mode?: string | null;
  allow_trace_collapse?: boolean;
  trace_summary?: TraceSummaryData | null;
  trace_available?: boolean;
}

export interface ExecutionTraceNodeRaw {
  id: string;
  kind: string;
  label: string;
  status: string;
  started_at?: number | null;
  ended_at?: number | null;
  result_preview?: string;
  error?: string | null;
  metadata?: Record<string, unknown>;
  children: ExecutionTraceNodeRaw[];
}

export interface ExecutionTraceSnapshotRaw {
  turn_id: string;
  user_id: string;
  session_id: string;
  status: string;
  mode: string;
  orchestration_id?: string | null;
  started_at?: number | null;
  ended_at?: number | null;
  continued_from_turn_id?: string | null;
  continued_from_trace_id?: string | null;
  superseded_by_turn_id?: string | null;
  supersession_reason?: string | null;
  summary: TraceSummaryData;
  root: ExecutionTraceNodeRaw;
}
