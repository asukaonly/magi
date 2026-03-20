/**
 * Chat domain types for Magi.
 */

import type { TraceSummaryData } from './websocket';

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
  turnId?: string;
  traceSummary?: NormalizedTraceSummary | null;
  traceAvailable?: boolean;
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
  role: ChatMessageRole;
  content: string;
  timestamp: number;
  turn_id?: string | null;
  kind?: ChatMessageKind | null;
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
  summary: TraceSummaryData;
  root: ExecutionTraceNodeRaw;
}
