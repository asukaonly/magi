import type {
  ChatAttachment,
  ChatRunState,
} from '@/api';
import {
  normalizeRecalledMemories,
  normalizeRecalledMemorySummary,
} from '@/domain/chat/state.history';
import type { NormalizedExecutionTraceSummary } from '@/domain/chat/state.trace';
import { normalizeChatTimestamp } from '@/domain/chat/timestamps';
import {
  orderCompleteRhythmItems,
  readRhythmSegmentMeta,
  type RhythmSegmentMeta,
} from '@/domain/chat/rhythm';

export {
  normalizeHistoryMessages,
  normalizeMessageLabel,
} from '@/domain/chat/state.history';
export {
  flattenPlanningNodeForDisplay,
  normalizeTraceNode,
  normalizeTraceSnapshot,
  normalizeTraceSummary,
  shouldShowTraceEntry,
} from '@/domain/chat/state.trace';
export type {
  NormalizedExecutionPlanStep,
  NormalizedExecutionPlanSummary,
  NormalizedExecutionTraceNode,
  NormalizedExecutionTraceSnapshot,
  NormalizedExecutionTraceSummary,
} from '@/domain/chat/state.trace';

export const createClientTurnId = (): string => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `turn_${crypto.randomUUID()}`;
  }
  return `turn_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
};

export type ChatMessageKind = 'user' | 'assistant' | 'status';

export interface ChatTimelineMessage {
  id: string;
  role: 'user' | 'assistant';
  kind: ChatMessageKind;
  content: string;
  timestamp: number;
  messageId?: string;
  messageKind?: string | null;
  personaId?: string | null;
  turnId?: string;
  reaction?: string | null;
  replyTo?: ChatTimelineReplyPreview | null;
  label?: ChatTimelineMessageLabel | null;
  attachments?: ChatAttachment[];
  traceDisplayMode?: string | null;
  allowTraceCollapse?: boolean;
  traceSummary?: NormalizedExecutionTraceSummary | null;
  traceAvailable?: boolean;
  runState?: ChatRunState | null;
  streaming?: boolean;
  runtimeStatuses?: RuntimeStatusTrace[];
  reasoning?: ReasoningTrace[];
  toolCalls?: ToolCallTrace[];
  recalledMemories?: RecalledMemory[];
  recalledMemorySummary?: RecalledMemorySummary;
  payload?: Record<string, unknown> | null;
}

const getRhythmSegmentMeta = (message: ChatTimelineMessage): RhythmSegmentMeta | null => {
  return readRhythmSegmentMeta(message.payload?.rhythm);
};

export const buildSystemSuggestionTriggerText = (messages: ChatTimelineMessage[]): string => {
  if (messages.length < 2) {
    return '';
  }
  const lastMessage = messages[messages.length - 1];
  if (!lastMessage || lastMessage.role !== 'assistant' || lastMessage.streaming) {
    return '';
  }

  if (lastMessage.messageKind === 'assistant_rhythm_segment') {
    const turnId = String(lastMessage.turnId || '').trim();
    const lastMeta = getRhythmSegmentMeta(lastMessage);
    if (!turnId || !lastMeta) {
      return '';
    }
    const segments: ChatTimelineMessage[] = [];
    let index = messages.length - 1;
    while (index >= 0) {
      const message = messages[index];
      if (
        !message
        || message.role !== 'assistant'
        || message.messageKind !== 'assistant_rhythm_segment'
        || String(message.turnId || '').trim() !== turnId
      ) {
        break;
      }
      segments.unshift(message);
      index -= 1;
    }
    const orderedSegments = orderCompleteRhythmItems(
      segments,
      getRhythmSegmentMeta,
    );
    if (
      !orderedSegments
      || orderedSegments.length !== lastMeta.segmentCount
    ) {
      return '';
    }
    const userMessage = messages[index];
    if (!userMessage || userMessage.role !== 'user') {
      return '';
    }
    return `${userMessage.content}\n${orderedSegments.map((message) => message.content).join('\n')}`;
  }

  const lastTwo = messages.slice(-2);
  if (lastTwo.length < 2) {
    return '';
  }
  const [maybeUser, maybeAssistant] = lastTwo;
  if (maybeUser.role !== 'user' || maybeAssistant.role !== 'assistant') {
    return '';
  }
  if (maybeAssistant.streaming) {
    return '';
  }
  return `${maybeUser.content}\n${maybeAssistant.content}`;
};

/**
 * Compact record of a memory finding the assistant pulled in to ground its
 * reply. Surfaced in the bubble's "called memories" row and the click-through
 * popover; the full retrieval trace stays inside the assistant runtime panel.
 */
export interface RecalledMemory {
  kind: string;
  sourceLayer: string;
  statement: string;
  topic: string;
  confidence?: number | null;
  occurredAt?: number | null;
  evidenceText?: string | null;
  feedbackRef?: string | null;
}

export interface RecalledMemorySummary {
  coverageKind: string;
  canClaimTotal: boolean;
  totalCount?: number | null;
  domain?: string | null;
}

export interface RuntimeStatusTrace {
  source: string;
  stepLabel?: string | null;
  content: string;
}

export interface ReasoningTrace {
  source: string;
  stepLabel?: string | null;
  content: string;
}

export interface ToolCallTrace {
  toolCallId?: string | null;
  toolName: string;
  status: 'running' | 'completed';
  toolArgsText?: string;
  toolArguments?: Record<string, unknown> | null;
}

export interface ChatTimelineReplyPreview {
  messageId: string;
  role: 'user' | 'assistant';
  messageKind?: string | null;
  contentExcerpt: string;
}

export interface ChatTimelineMessageLabel {
  kind: string;
  text: string;
  appliedBy: string;
  source: string;
  createdAtMs: number;
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
  messageId?: string;
  messageKind?: string | null;
  timestamp?: number;
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

export const normalizeTurnUxPlan = (raw: unknown): NormalizedTurnUxPlan | null => {
  if (!raw || typeof raw !== 'object') return null;
  const plan = raw as Record<string, unknown>;
  const assistantSurfaceMode = String(plan.assistant_surface_mode || '').trim();
  if (!assistantSurfaceMode) return null;

  const interimTextRaw = plan.interim_text;
  const thinkingIndicatorRaw = plan.thinking_indicator;
  const traceDisplayModeRaw = plan.trace_display_mode;
  const reactionStyleRaw = plan.reaction_style;
  const allowTraceCollapseRaw = plan.allow_trace_collapse;

  return {
    assistantSurfaceMode,
    thinkingIndicator: thinkingIndicatorRaw == null ? null : String(thinkingIndicatorRaw),
    traceDisplayMode: traceDisplayModeRaw == null ? null : String(traceDisplayModeRaw),
    allowTraceCollapse: Boolean(allowTraceCollapseRaw),
    interimText: interimTextRaw == null ? null : String(interimTextRaw),
    reactionStyle: reactionStyleRaw == null ? null : String(reactionStyleRaw),
  };
};

export const createPendingTurn = (
  input: string,
  turnId: string,
  timestamp: number,
  _pendingLabel: string,
  attachments: ChatAttachment[] = [],
  replyTo: ChatTimelineReplyPreview | null = null,
  payload: Record<string, unknown> | null = null,
): ChatTimelineMessage[] => [
  {
    id: `${turnId}-user`,
    role: 'user',
    kind: 'user',
    content: input,
    timestamp,
    turnId,
    replyTo,
    attachments: attachments.length > 0 ? attachments : undefined,
    traceDisplayMode: null,
    allowTraceCollapse: false,
    payload,
  },
];

const insertAfterTurnAnchor = (
  messages: ChatTimelineMessage[],
  incoming: ChatTimelineMessage,
  turnId: string,
): ChatTimelineMessage[] => {
  const resolvedTurnId = String(turnId || '').trim();
  if (!resolvedTurnId) {
    return [...messages, incoming];
  }

  let lastSameTurnIndex = -1;
  messages.forEach((message, index) => {
    if (String(message.turnId || '').trim() === resolvedTurnId) {
      lastSameTurnIndex = index;
    }
  });

  if (lastSameTurnIndex < 0) {
    return [...messages, incoming];
  }

  const nextMessages = [...messages];
  nextMessages.splice(lastSameTurnIndex + 1, 0, incoming);
  return nextMessages;
};

export const applyTurnUxPlan = (
  messages: ChatTimelineMessage[],
  turnId: string,
  plan: NormalizedTurnUxPlan | null,
  options: ApplyTurnUxPlanOptions = {},
): ChatTimelineMessage[] => {
  const resolvedTurnId = String(turnId || '').trim();
  if (!resolvedTurnId || !plan) return messages;

  const buildSyntheticInterimMessage = (content: string): ChatTimelineMessage => ({
    id: String(options.messageId || `${resolvedTurnId}-assistant`),
    role: 'assistant',
    kind: 'assistant',
    content,
    timestamp: normalizeChatTimestamp(options.timestamp),
    messageId: options.messageId,
    messageKind: options.messageKind || 'assistant_interim',
    turnId: resolvedTurnId,
    traceAvailable: false,
  });

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

    const interimMessage = buildSyntheticInterimMessage(interimText);

    let replaced = false;
    const nextMessages = messages.map((message) => {
      if (message.turnId !== resolvedTurnId) return message;
      if (message.messageKind === 'assistant_interim' || message.kind === 'status') {
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
    return insertAfterTurnAnchor(messages, applyUxMetadata(interimMessage, plan), resolvedTurnId);
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
    return insertAfterTurnAnchor(
      messages,
      applyUxMetadata(
        buildSyntheticInterimMessage(String(options.pendingLabel || 'Thinking...')),
        plan,
      ),
      resolvedTurnId,
    );
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
  const anchorMessage = messages.find((message) => message.turnId === turnId);
  const traceDisplayMode = anchorMessage?.traceDisplayMode || null;
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
    if (message.kind === 'status' && !String(message.messageKind || '').trim()) {
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
  if (
    nextSummary &&
    ['interrupted', 'merged'].includes(String(nextSummary.status || '').trim())
  ) {
    return messages.map((message) => (
      message.turnId === turnId && message.role === 'user'
        ? {
          ...message,
          traceSummary: nextSummary,
          traceAvailable: Boolean(nextSummary.traceAvailable),
        }
        : message
    ));
  }

  return insertAfterTurnAnchor(
    messages,
    {
      id: `${turnId}-assistant`,
      role: 'assistant',
      kind: 'status',
      content: nextSummary?.headline || 'Thinking...',
      timestamp: Date.now(),
      messageKind: null,
      turnId,
      traceDisplayMode,
      allowTraceCollapse: Boolean(anchorMessage?.allowTraceCollapse),
      traceSummary: nextSummary || null,
      traceAvailable: Boolean(nextSummary?.traceAvailable),
    },
    turnId,
  );
};

export const applyAgentResponse = (
  messages: ChatTimelineMessage[],
  payload: {
    content: string;
    attachments?: ChatAttachment[];
    timestamp?: number;
    messageId?: string;
    messageKind?: string | null;
    personaId?: string | null;
    turnId?: string;
    traceSummary?: NormalizedExecutionTraceSummary | null;
    traceAvailable?: boolean;
    uxPlan?: NormalizedTurnUxPlan | null;
    payload?: Record<string, unknown> | null;
  },
): ChatTimelineMessage[] => {
  const isTransientStatusMessage = (message: ChatTimelineMessage): boolean => (
    message.kind === 'status' && !String(message.messageKind || '').trim()
  );

  const turnId = String(payload.turnId || '').trim();
  const timestamp = normalizeChatTimestamp(payload.timestamp);
  const traceSummary = payload.traceSummary || null;
  const traceAvailable = Boolean(payload.traceAvailable || traceSummary?.traceAvailable);
  const uxPlan = payload.uxPlan || null;
  const messageKind = String(payload.messageKind || '').trim();
  const hasPayloadPersonaId = payload.personaId !== undefined;
  const normalizedPayloadPersonaId = String(payload.personaId || '').trim() || null;

  const resolvePersonaId = (existing?: ChatTimelineMessage): string | null => {
    if (hasPayloadPersonaId) {
      return normalizedPayloadPersonaId;
    }
    return existing?.personaId ?? null;
  };

  if (messageKind === 'assistant_reaction' && turnId) {
    return messages
      .filter((message) => !(message.turnId === turnId && message.kind === 'assistant'))
      .map((message) => {
        if (message.turnId !== turnId || message.role !== 'user') {
          return message;
        }
        return applyUxMetadata(
          {
            ...message,
            reaction: payload.content,
            traceSummary,
            traceAvailable,
          },
          uxPlan ?? {
            assistantSurfaceMode: 'reaction_only',
          }
        );
      });
  }

  const buildAssistantMessage = (resolvedTurnId?: string, existing?: ChatTimelineMessage): ChatTimelineMessage => ({
    id: String(payload.messageId || `${resolvedTurnId || turnId || 'assistant'}-assistant-${timestamp}`),
    role: 'assistant',
    kind: 'assistant',
    content: payload.content,
    attachments: Array.isArray(payload.attachments) && payload.attachments.length > 0 ? payload.attachments : undefined,
    timestamp,
    messageId: payload.messageId,
    messageKind: payload.messageKind || 'assistant_final',
    personaId: resolvePersonaId(existing),
    turnId: resolvedTurnId || turnId || undefined,
    traceDisplayMode: uxPlan?.traceDisplayMode ?? null,
    allowTraceCollapse: Boolean(uxPlan?.allowTraceCollapse),
    traceSummary,
    traceAvailable,
    runtimeStatuses: existing?.runtimeStatuses,
    reasoning: existing?.reasoning,
    toolCalls: existing?.toolCalls,
    recalledMemories: normalizeRecalledMemories(
      payload.payload && typeof payload.payload === 'object'
        ? (payload.payload as Record<string, unknown>).recalled_memories
        : null,
    ) ?? existing?.recalledMemories,
    recalledMemorySummary: normalizeRecalledMemorySummary(
      payload.payload && typeof payload.payload === 'object'
        ? (payload.payload as Record<string, unknown>).recalled_memory_summary
        : null,
    ) ?? existing?.recalledMemorySummary,
    payload: payload.payload ?? null,
  });

  const hasInterimAssistant = turnId
    ? messages.some(
      (message) =>
        message.turnId === turnId
        && message.kind === 'assistant'
        && message.messageKind === 'assistant_interim'
    )
    : false;
  const hasRhythmSegments = turnId
    ? messages.some(
      (message) =>
        message.turnId === turnId
        && message.kind === 'assistant'
        && message.messageKind === 'assistant_rhythm_segment'
    )
    : false;

  if (messageKind === 'assistant_rhythm_segment' && turnId) {
    const incoming = buildAssistantMessage(turnId);
    const withoutTransientStatus = messages.filter(
      (message) => !(message.turnId === turnId && isTransientStatusMessage(message)),
    );
    const existingIndex = withoutTransientStatus.findIndex(
      (message) => Boolean(payload.messageId) && message.messageId === payload.messageId,
    );
    if (existingIndex >= 0) {
      return withoutTransientStatus.map((message, index) => (
        index === existingIndex ? { ...incoming, personaId: incoming.personaId ?? message.personaId ?? null } : message
      ));
    }
    return insertAfterTurnAnchor(withoutTransientStatus, incoming, turnId);
  }

  if (hasRhythmSegments && !String(payload.messageId || '').trim()) {
    return messages.map((message) => {
      if (message.turnId !== turnId || message.messageKind !== 'assistant_rhythm_segment') {
        return message;
      }
      return {
        ...message,
        traceSummary: traceSummary ?? message.traceSummary ?? null,
        traceAvailable: traceAvailable || Boolean(message.traceAvailable),
      };
    });
  }

  if (hasRhythmSegments && messageKind === 'assistant_final' && turnId) {
    const incoming = buildAssistantMessage(turnId);
    let inserted = false;
    const nextMessages = messages.flatMap((message) => {
      if (message.turnId !== turnId || message.messageKind !== 'assistant_rhythm_segment') {
        return [message];
      }
      if (inserted) {
        return [];
      }
      inserted = true;
      return [{ ...incoming, personaId: incoming.personaId ?? message.personaId ?? null }];
    });
    return inserted ? nextMessages : insertAfterTurnAnchor(messages, incoming, turnId);
  }

  if (!turnId) {
    const lastStatusIndex = [...messages]
      .map((message, index) => ({ message, index }))
      .reverse()
      .find(({ message }) => isTransientStatusMessage(message))
      ?.index;
    if (lastStatusIndex !== undefined) {
      const fallbackTurnId = messages[lastStatusIndex]?.turnId;
      return messages.map((message, index) =>
        index === lastStatusIndex ? buildAssistantMessage(fallbackTurnId, message) : message
      );
    }
    const fallbackTurnId = [...messages]
      .map((message) => String(message.turnId || '').trim())
      .reverse()
      .find(Boolean);
    if (fallbackTurnId) {
      return insertAfterTurnAnchor(
        messages,
        { ...buildAssistantMessage(fallbackTurnId), id: String(payload.messageId || `${fallbackTurnId}-assistant`), turnId: fallbackTurnId },
        fallbackTurnId,
      );
    }
    return [...messages, buildAssistantMessage()];
  }

  let replaced = false;
  if (hasInterimAssistant) {
    const existingFinalIndex = messages.findIndex(
      (message) =>
        message.turnId === turnId
        && message.kind === 'assistant'
        && message.messageKind !== 'assistant_interim'
    );
    if (existingFinalIndex >= 0) {
      return messages.map((message, index) =>
        index === existingFinalIndex ? buildAssistantMessage(turnId, message) : message
      );
    }
    return insertAfterTurnAnchor(messages, buildAssistantMessage(turnId), turnId);
  }

  const nextMessages = messages.map((message) => {
    if (message.turnId !== turnId) return message;
    if (message.kind === 'assistant' || isTransientStatusMessage(message)) {
      replaced = true;
      return { ...buildAssistantMessage(turnId, message), turnId };
    }
    return message;
  });

  if (replaced) return nextMessages;

  const fallbackStatusIndex = [...messages]
    .map((message, index) => ({ message, index }))
    .reverse()
    .find(({ message }) => isTransientStatusMessage(message))
    ?.index;

  if (fallbackStatusIndex !== undefined) {
    return messages.map((message, index) =>
      index === fallbackStatusIndex ? { ...buildAssistantMessage(turnId, message), turnId } : message
    );
  }

  return insertAfterTurnAnchor(messages, { ...buildAssistantMessage(turnId), turnId }, turnId);
};
