/**
 * Chat domain normalizers and transformers.
 * These functions convert API responses to frontend-friendly types.
 */

import type {
  ChatTimelineMessage,
  NormalizedTraceSummary,
  NormalizedTraceNode,
  NormalizedTraceSnapshot,
  ChatHistoryMessageRaw,
  TraceSummaryData,
  ExecutionTraceNodeRaw,
  ExecutionTraceSnapshotRaw,
} from '@/types';

// ============================================================================
// ID Generation
// ============================================================================

/**
 * Create a unique client turn ID.
 */
export function createClientTurnId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `turn_${crypto.randomUUID()}`;
  }
  return `turn_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

// ============================================================================
// Trace Normalizers
// ============================================================================

/**
 * Normalize a trace summary from API response.
 */
export function normalizeTraceSummary(raw: unknown): NormalizedTraceSummary | null {
  if (!raw || typeof raw !== 'object') return null;

  const summary = raw as TraceSummaryData;
  const turnId = String(summary.turn_id || '').trim();
  if (!turnId) return null;

  return {
    turnId,
    mode: String(summary.mode || 'function_calling'),
    status: String(summary.status || 'running'),
    headline: String(summary.headline || ''),
    activeSteps: Number(summary.active_steps || 0),
    completedSteps: Number(summary.completed_steps || 0),
    failedSteps: Number(summary.failed_steps || 0),
    durationSeconds: Number(summary.duration_seconds || 0),
    traceAvailable: Boolean(summary.trace_available),
    orchestrationId: summary.orchestration_id || null,
  };
}

/**
 * Normalize a trace node from API response.
 */
export function normalizeTraceNode(raw: ExecutionTraceNodeRaw): NormalizedTraceNode {
  return {
    id: raw.id,
    kind: raw.kind,
    label: raw.label,
    status: raw.status,
    startedAt: raw.started_at ?? null,
    endedAt: raw.ended_at ?? null,
    resultPreview: raw.result_preview || '',
    error: raw.error || null,
    metadata: (raw.metadata || {}) as Record<string, unknown>,
    children: Array.isArray(raw.children) ? raw.children.map(normalizeTraceNode) : [],
  };
}

/**
 * Flatten planning nodes for display purposes.
 */
export function flattenPlanningNodeForDisplay(
  root: NormalizedTraceNode
): NormalizedTraceNode {
  if (root.kind !== 'root' || !Array.isArray(root.children)) {
    return root;
  }

  return {
    ...root,
    children: root.children.flatMap((child) =>
      child.kind === 'planning' ? child.children : [child]
    ),
  };
}

/**
 * Normalize a complete trace snapshot from API response.
 */
export function normalizeTraceSnapshot(
  raw: ExecutionTraceSnapshotRaw | null | undefined
): NormalizedTraceSnapshot | null {
  if (!raw) return null;

  const summary = normalizeTraceSummary(raw.summary);
  if (!summary) return null;

  return {
    turnId: raw.turn_id,
    userId: raw.user_id,
    sessionId: raw.session_id,
    status: raw.status,
    mode: raw.mode,
    orchestrationId: raw.orchestration_id || null,
    startedAt: raw.started_at ?? null,
    endedAt: raw.ended_at ?? null,
    summary,
    root: normalizeTraceNode(raw.root),
  };
}

// ============================================================================
// Message Normalizers
// ============================================================================

/**
 * Normalize history messages from API response.
 */
export function normalizeHistoryMessages(
  messages: ChatHistoryMessageRaw[]
): ChatTimelineMessage[] {
  return messages.map((message, index) => {
    const kind = (message.kind || message.role) as ChatTimelineMessage['kind'];
    const traceSummary = normalizeTraceSummary(message.trace_summary);

    return {
      id: `${message.turn_id || 'history'}-${index}-${kind}`,
      role: message.role === 'user' ? 'user' : 'assistant',
      kind,
      content: message.content,
      timestamp: Number(message.timestamp || Date.now()),
      turnId: message.turn_id || undefined,
      traceSummary,
      traceAvailable: Boolean(message.trace_available || traceSummary?.traceAvailable),
    };
  });
}

// ============================================================================
// Message Builders
// ============================================================================

/**
 * Create a pending turn (user message + status placeholder).
 */
export function createPendingTurn(
  input: string,
  turnId: string,
  timestamp: number,
  pendingLabel: string
): ChatTimelineMessage[] {
  return [
    {
      id: `${turnId}-user`,
      role: 'user' as const,
      kind: 'user' as const,
      content: input,
      timestamp,
      turnId,
    },
    {
      id: `${turnId}-status`,
      role: 'assistant' as const,
      kind: 'status' as const,
      content: pendingLabel,
      timestamp: timestamp + 1,
      turnId,
      traceAvailable: false,
    },
  ];
}

/**
 * Upsert trace summary into messages array.
 */
export function upsertTraceSummary(
  messages: ChatTimelineMessage[],
  turnId: string,
  summary: NormalizedTraceSummary | null
): ChatTimelineMessage[] {
  if (!turnId) return messages;

  const nextSummary = summary || undefined;
  let updated = false;

  const nextMessages = messages.map((message) => {
    if (message.turnId !== turnId) return message;

    if (message.kind === 'assistant') {
      updated = true;
      return {
        ...message,
        traceSummary: nextSummary || null,
        traceAvailable: Boolean(nextSummary?.traceAvailable),
      };
    }

    if (message.kind === 'status') {
      updated = true;
      return {
        ...message,
        content: nextSummary?.headline || message.content,
        traceSummary: nextSummary || null,
        traceAvailable: Boolean(nextSummary?.traceAvailable),
      };
    }

    return message;
  });

  if (updated) return nextMessages;

  // If no message was updated, append a new status message
  return [
    ...messages,
    {
      id: `${turnId}-status`,
      role: 'assistant' as const,
      kind: 'status' as const,
      content: nextSummary?.headline || 'Thinking...',
      timestamp: Date.now(),
      turnId,
      traceSummary: nextSummary || null,
      traceAvailable: Boolean(nextSummary?.traceAvailable),
    },
  ];
}

/**
 * Apply agent response to messages array.
 */
export function applyAgentResponse(
  messages: ChatTimelineMessage[],
  payload: {
    content: string;
    timestamp?: number;
    turnId?: string;
    traceSummary?: NormalizedTraceSummary | null;
    traceAvailable?: boolean;
  }
): ChatTimelineMessage[] {
  const turnId = String(payload.turnId || '').trim();
  const timestamp = Number(payload.timestamp || Date.now());
  const traceSummary = payload.traceSummary || null;
  const traceAvailable = Boolean(payload.traceAvailable || traceSummary?.traceAvailable);

  const buildAssistantMessage = (resolvedTurnId?: string): ChatTimelineMessage => ({
    id: `${resolvedTurnId || turnId || 'assistant'}-assistant-${timestamp}`,
    role: 'assistant',
    kind: 'assistant',
    content: payload.content,
    timestamp,
    turnId: resolvedTurnId || turnId || undefined,
    traceSummary,
    traceAvailable,
  });

  if (!turnId) {
    // Try to find and replace the last status message
    const lastStatusIndex = [...messages].map((m) => m.kind).lastIndexOf('status');
    if (lastStatusIndex >= 0) {
      const fallbackTurnId = messages[lastStatusIndex]?.turnId;
      return messages.map((message, index) =>
        index === lastStatusIndex ? buildAssistantMessage(fallbackTurnId) : message
      );
    }
    return [...messages, buildAssistantMessage()];
  }

  let replaced = false;
  const nextMessages = messages.map((message) => {
    if (message.turnId !== turnId) return message;

    if (message.kind === 'status' || message.kind === 'assistant') {
      replaced = true;
      return { ...buildAssistantMessage(turnId), id: `${turnId}-assistant`, turnId };
    }

    return message;
  });

  if (replaced) return nextMessages;

  // Fallback: find any status message to replace
  const fallbackStatusIndex = [...messages]
    .map((message, index) => ({ message, index }))
    .reverse()
    .find(({ message }) => message.kind === 'status')
    ?.index;

  if (fallbackStatusIndex !== undefined) {
    return messages.map((message, index) =>
      index === fallbackStatusIndex
        ? { ...buildAssistantMessage(turnId), id: `${turnId}-assistant`, turnId }
        : message
    );
  }

  return [...messages, { ...buildAssistantMessage(turnId), id: `${turnId}-assistant`, turnId }];
}
