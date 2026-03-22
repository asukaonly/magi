import type { ChatHistoryMessage, ExecutionTraceNode, ExecutionTraceSnapshot, ExecutionTraceSummary } from '@/api';

export type ChatMessageKind = 'user' | 'assistant' | 'status';

export interface ChatTimelineMessage {
  id: string;
  role: 'user' | 'assistant';
  kind: ChatMessageKind;
  content: string;
  timestamp: number;
  messageId?: string;
  messageKind?: string | null;
  turnId?: string;
  reaction?: string | null;
  traceDisplayMode?: string | null;
  allowTraceCollapse?: boolean;
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

export interface NormalizedTurnUxPlan {
  assistantSurfaceMode: string;
  thinkingIndicator?: string | null;
  traceDisplayMode?: string | null;
  allowTraceCollapse?: boolean;
  interimText?: string | null;
  reactionStyle?: string | null;
}

type ApplyTurnUxPlanOptions = {
  pendingLabel?: string;
};

const REACTION_EMOJI_BY_STYLE: Record<string, string> = {
  acknowledge: '👌',
};

const applyUxMetadata = (
  message: ChatTimelineMessage,
  plan: NormalizedTurnUxPlan,
): ChatTimelineMessage => ({
  ...message,
  traceDisplayMode: plan.traceDisplayMode ?? message.traceDisplayMode ?? null,
  allowTraceCollapse: typeof plan.allowTraceCollapse === 'boolean'
    ? plan.allowTraceCollapse
    : Boolean(message.allowTraceCollapse),
});

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

export const normalizeTurnUxPlan = (raw: unknown): NormalizedTurnUxPlan | null => {
  if (!raw || typeof raw !== 'object') return null;
  const plan = raw as Record<string, unknown>;
  const assistantSurfaceMode = String(
    plan.assistantSurfaceMode || plan.assistant_surface_mode || ''
  ).trim();
  if (!assistantSurfaceMode) return null;

  const interimTextRaw = plan.interimText ?? plan.interim_text;
  const thinkingIndicatorRaw = plan.thinkingIndicator ?? plan.thinking_indicator;
  const traceDisplayModeRaw = plan.traceDisplayMode ?? plan.trace_display_mode;
  const reactionStyleRaw = plan.reactionStyle ?? plan.reaction_style;
  const allowTraceCollapseRaw = plan.allowTraceCollapse ?? plan.allow_trace_collapse;

  return {
    assistantSurfaceMode,
    thinkingIndicator: thinkingIndicatorRaw == null ? null : String(thinkingIndicatorRaw),
    traceDisplayMode: traceDisplayModeRaw == null ? null : String(traceDisplayModeRaw),
    allowTraceCollapse: Boolean(allowTraceCollapseRaw),
    interimText: interimTextRaw == null ? null : String(interimTextRaw),
    reactionStyle: reactionStyleRaw == null ? null : String(reactionStyleRaw),
  };
};

export const normalizeHistoryMessages = (messages: ChatHistoryMessage[]): ChatTimelineMessage[] => {
  const normalizedMessages: ChatTimelineMessage[] = [];

  messages.forEach((message, index) => {
    const rawMessageKind = String(message.message_kind || '').trim();
    const kind = (message.kind || message.role) as ChatMessageKind;
    const traceSummary = normalizeTraceSummary(message.trace_summary as ExecutionTraceSummary | undefined);
    const normalizedMessage: ChatTimelineMessage = {
      id: String(message.message_id || `${message.turn_id || 'history'}-${index}-${kind}`),
      role: message.role === 'user' ? 'user' : 'assistant',
      kind,
      content: message.content,
      timestamp: Number(message.timestamp || Date.now()),
      messageId: message.message_id || undefined,
      messageKind: message.message_kind || null,
      turnId: message.turn_id || undefined,
      traceDisplayMode: message.trace_display_mode || null,
      allowTraceCollapse: Boolean(message.allow_trace_collapse),
      traceSummary,
      traceAvailable: Boolean(message.trace_available || traceSummary?.traceAvailable),
    };

    if (rawMessageKind === 'assistant_reaction') {
      const turnId = String(normalizedMessage.turnId || '').trim();
      const targetIndex = [...normalizedMessages]
        .map((item, itemIndex) => ({ item, itemIndex }))
        .reverse()
        .find(({ item }) => item.role === 'user' && String(item.turnId || '').trim() === turnId)
        ?.itemIndex;
      if (targetIndex !== undefined) {
        normalizedMessages[targetIndex] = {
          ...normalizedMessages[targetIndex],
          reaction: normalizedMessage.content,
        };
        return;
      }
    }

    normalizedMessages.push(normalizedMessage);
  });

  return normalizedMessages;
};

export const mergeHistoryMessages = (
  existingMessages: ChatTimelineMessage[],
  incomingMessages: ChatTimelineMessage[],
): ChatTimelineMessage[] => {
  if (existingMessages.length === 0 || incomingMessages.length === 0) {
    return incomingMessages;
  }

  const localAssistantByTurn = new Map<string, ChatTimelineMessage>();
  for (const message of existingMessages) {
    if (message.kind !== 'assistant') continue;
    const turnId = String(message.turnId || '').trim();
    if (!turnId) continue;
    localAssistantByTurn.set(turnId, message);
  }

  return incomingMessages.map((message) => {
    if (message.kind !== 'status') return message;
    const turnId = String(message.turnId || '').trim();
    if (!turnId) return message;

    const localAssistant = localAssistantByTurn.get(turnId);
    if (!localAssistant) return message;

    return {
      ...localAssistant,
      traceDisplayMode: message.traceDisplayMode ?? localAssistant.traceDisplayMode ?? null,
      allowTraceCollapse: Boolean(message.allowTraceCollapse || localAssistant.allowTraceCollapse),
      traceSummary: message.traceSummary ?? localAssistant.traceSummary ?? null,
      traceAvailable: Boolean(message.traceAvailable || localAssistant.traceAvailable),
    };
  });
};

export const createPendingTurn = (input: string, turnId: string, timestamp: number, _pendingLabel: string): ChatTimelineMessage[] => [
  {
    id: `${turnId}-user`,
    role: 'user',
    kind: 'user',
    content: input,
    timestamp,
    turnId,
    traceDisplayMode: null,
    allowTraceCollapse: false,
  },
];

export const applyTurnUxPlan = (
  messages: ChatTimelineMessage[],
  turnId: string,
  plan: NormalizedTurnUxPlan | null,
  options: ApplyTurnUxPlanOptions = {},
): ChatTimelineMessage[] => {
  const resolvedTurnId = String(turnId || '').trim();
  if (!resolvedTurnId || !plan) return messages;

  if (plan.assistantSurfaceMode === 'reaction_only') {
    const reaction = REACTION_EMOJI_BY_STYLE[String(plan.reactionStyle || '').trim()] || '👌';
    const nextMessages = messages
      .filter((message) => !(message.turnId === resolvedTurnId && message.role === 'assistant'))
      .map((message) => (
        message.turnId === resolvedTurnId && message.role === 'user'
          ? applyUxMetadata({ ...message, reaction }, plan)
          : message
      ));
    return nextMessages;
  }

  if (plan.assistantSurfaceMode === 'interim_then_final') {
    const interimText = String(plan.interimText || '').trim();
    if (!interimText) return messages;

    const interimMessage: ChatTimelineMessage = {
      id: `${resolvedTurnId}-assistant`,
      role: 'assistant',
      kind: 'assistant',
      content: interimText,
      timestamp: Date.now(),
      turnId: resolvedTurnId,
      traceAvailable: false,
    };

    let replaced = false;
    const nextMessages = messages.map((message) => {
      if (message.turnId !== resolvedTurnId) return message;
      if (message.kind === 'assistant' || message.kind === 'status') {
        replaced = true;
        return applyUxMetadata({
          ...message,
          ...interimMessage,
          traceSummary: message.traceSummary ?? null,
          traceAvailable: Boolean(message.traceAvailable),
        }, plan);
      }
      return message;
    });

    if (replaced) return nextMessages;
    return [...messages, applyUxMetadata(interimMessage, plan)];
  }

  if (plan.thinkingIndicator && plan.thinkingIndicator !== 'hidden') {
    const hasTurnFeedback = messages.some(
      (message) =>
        message.turnId === resolvedTurnId &&
        (message.kind === 'assistant' || message.kind === 'status')
    );
    if (hasTurnFeedback) {
      return messages;
    }
    return [
      ...messages,
      applyUxMetadata({
        id: `${resolvedTurnId}-status`,
        role: 'assistant',
        kind: 'status',
        content: String(options.pendingLabel || 'Thinking...'),
        timestamp: Date.now(),
        turnId: resolvedTurnId,
        traceAvailable: false,
      }, plan),
    ];
  }

  return messages.map((message) => (
    message.turnId === resolvedTurnId ? applyUxMetadata(message, plan) : message
  ));
};

export const upsertTraceSummary = (
  messages: ChatTimelineMessage[],
  turnId: string,
  summary: NormalizedExecutionTraceSummary | null,
): ChatTimelineMessage[] => {
  if (!turnId) return messages;
  const nextSummary = summary || undefined;
  const traceDisplayMode = messages.find((message) => message.turnId === turnId)?.traceDisplayMode || null;
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
  if (traceDisplayMode === 'none') return messages;

  return [
    ...messages,
    {
      id: `${turnId}-status`,
      role: 'assistant',
      kind: 'status',
      content: nextSummary?.headline || 'Thinking...',
      timestamp: Date.now(),
      turnId,
      traceDisplayMode,
      allowTraceCollapse: Boolean(
        messages.find((message) => message.turnId === turnId)?.allowTraceCollapse
      ),
      traceSummary: nextSummary || null,
      traceAvailable: Boolean(nextSummary?.traceAvailable),
    },
  ];
};

export const shouldShowTraceEntry = (
  message: Pick<ChatTimelineMessage, 'turnId' | 'traceDisplayMode' | 'traceAvailable' | 'traceSummary'>,
  summary?: { trace_available?: boolean } | null,
): boolean => {
  const turnId = String(message.turnId || '').trim();
  if (!turnId) return false;
  const traceDisplayMode = String(message.traceDisplayMode || '').trim() || 'collapsible';
  if (traceDisplayMode === 'none') return false;
  return Boolean(
    message.traceAvailable ||
    message.traceSummary?.traceAvailable ||
    summary?.trace_available
  );
};

export const applyAgentResponse = (
  messages: ChatTimelineMessage[],
  payload: {
    content: string;
    timestamp?: number;
    messageId?: string;
    messageKind?: string | null;
    turnId?: string;
    traceSummary?: NormalizedExecutionTraceSummary | null;
    traceAvailable?: boolean;
    uxPlan?: NormalizedTurnUxPlan | null;
  },
): ChatTimelineMessage[] => {
  const turnId = String(payload.turnId || '').trim();
  const timestamp = Number(payload.timestamp || Date.now());
  const traceSummary = payload.traceSummary || null;
  const traceAvailable = Boolean(payload.traceAvailable || traceSummary?.traceAvailable);
  const uxPlan = payload.uxPlan || null;
  const buildAssistantMessage = (resolvedTurnId?: string): ChatTimelineMessage => ({
    id: String(payload.messageId || `${resolvedTurnId || turnId || 'assistant'}-assistant-${timestamp}`),
    role: 'assistant',
    kind: 'assistant',
    content: payload.content,
    timestamp,
    messageId: payload.messageId,
    messageKind: payload.messageKind || 'assistant_final',
    turnId: resolvedTurnId || turnId || undefined,
    traceDisplayMode: uxPlan?.traceDisplayMode ?? null,
    allowTraceCollapse: Boolean(uxPlan?.allowTraceCollapse),
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
    const fallbackTurnId = [...messages]
      .map((message) => String(message.turnId || '').trim())
      .reverse()
      .find(Boolean);
    if (fallbackTurnId) {
      return [...messages, { ...buildAssistantMessage(fallbackTurnId), id: String(payload.messageId || `${fallbackTurnId}-assistant`), turnId: fallbackTurnId }];
    }
    return [...messages, buildAssistantMessage()];
  }

  let replaced = false;
  const nextMessages = messages.map((message) => {
    if (message.turnId !== turnId) return message;
    if (message.kind === 'status' || message.kind === 'assistant') {
      replaced = true;
      return { ...buildAssistantMessage(turnId), id: String(payload.messageId || `${turnId}-assistant`), turnId };
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
      index === fallbackStatusIndex ? { ...buildAssistantMessage(turnId), id: String(payload.messageId || `${turnId}-assistant`), turnId } : message
    );
  }

  return [...messages, { ...buildAssistantMessage(turnId), id: String(payload.messageId || `${turnId}-assistant`), turnId }];
};
