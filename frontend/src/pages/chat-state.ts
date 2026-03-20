import type { ChatHistoryMessage, ExecutionTraceNode, ExecutionTraceSnapshot, ExecutionTraceSummary } from '@/api';

export type ChatMessageKind = 'user' | 'assistant' | 'status';

export interface ChatTimelineMessage {
  id: string;
  role: 'user' | 'assistant';
  kind: ChatMessageKind;
  content: string;
  timestamp: number;
  turnId?: string;
  traceSummary?: NormalizedExecutionTraceSummary | null;
  traceAvailable?: boolean;
}

export interface NormalizedExecutionTraceSummary {
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

export interface NormalizedExecutionTraceNode {
  id: string;
  kind: string;
  label: string;
  status: string;
  startedAt?: number | null;
  endedAt?: number | null;
  resultPreview?: string;
  error?: string | null;
  metadata: Record<string, unknown>;
  children: NormalizedExecutionTraceNode[];
}

export interface NormalizedExecutionTraceSnapshot {
  turnId: string;
  userId: string;
  sessionId: string;
  status: string;
  mode: string;
  orchestrationId?: string | null;
  startedAt?: number | null;
  endedAt?: number | null;
  summary: NormalizedExecutionTraceSummary;
  root: NormalizedExecutionTraceNode;
}

export const normalizeTraceSummary = (raw: unknown): NormalizedExecutionTraceSummary | null => {
  if (!raw || typeof raw !== 'object') return null;
  const summary = raw as ExecutionTraceSummary;
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
};

export const normalizeTraceNode = (raw: ExecutionTraceNode): NormalizedExecutionTraceNode => ({
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
});

export const flattenPlanningNodeForDisplay = (
  root: NormalizedExecutionTraceNode,
): NormalizedExecutionTraceNode => {
  if (root.kind !== 'root' || !Array.isArray(root.children)) {
    return root;
  }

  return {
    ...root,
    children: root.children.flatMap((child) => (
      child.kind === 'planning' ? child.children : [child]
    )),
  };
};

export const normalizeTraceSnapshot = (raw: ExecutionTraceSnapshot | null | undefined): NormalizedExecutionTraceSnapshot | null => {
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
};

export const normalizeHistoryMessages = (messages: ChatHistoryMessage[]): ChatTimelineMessage[] =>
  messages.map((message, index) => {
    const kind = (message.kind || message.role) as ChatMessageKind;
    const traceSummary = normalizeTraceSummary(message.trace_summary as ExecutionTraceSummary | undefined);
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

export const createPendingTurn = (input: string, turnId: string, timestamp: number, pendingLabel: string): ChatTimelineMessage[] => [
  {
    id: `${turnId}-user`,
    role: 'user',
    kind: 'user',
    content: input,
    timestamp,
    turnId,
  },
  {
    id: `${turnId}-status`,
    role: 'assistant',
    kind: 'status',
    content: pendingLabel,
    timestamp: timestamp + 1,
    turnId,
    traceAvailable: false,
  },
];

export const upsertTraceSummary = (
  messages: ChatTimelineMessage[],
  turnId: string,
  summary: NormalizedExecutionTraceSummary | null,
): ChatTimelineMessage[] => {
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

  return [
    ...messages,
    {
      id: `${turnId}-status`,
      role: 'assistant',
      kind: 'status',
      content: nextSummary?.headline || 'Thinking...',
      timestamp: Date.now(),
      turnId,
      traceSummary: nextSummary || null,
      traceAvailable: Boolean(nextSummary?.traceAvailable),
    },
  ];
};

export const applyAgentResponse = (
  messages: ChatTimelineMessage[],
  payload: {
    content: string;
    timestamp?: number;
    turnId?: string;
    traceSummary?: NormalizedExecutionTraceSummary | null;
    traceAvailable?: boolean;
  },
): ChatTimelineMessage[] => {
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
    const lastStatusIndex = [...messages].map((message) => message.kind).lastIndexOf('status');
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

  const fallbackStatusIndex = [...messages]
    .map((message, index) => ({ message, index }))
    .reverse()
    .find(({ message }) => message.kind === 'status')
    ?.index;

  if (fallbackStatusIndex !== undefined) {
    return messages.map((message, index) =>
      index === fallbackStatusIndex ? { ...buildAssistantMessage(turnId), id: `${turnId}-assistant`, turnId } : message
    );
  }

  return [...messages, { ...buildAssistantMessage(turnId), id: `${turnId}-assistant`, turnId }];
};
