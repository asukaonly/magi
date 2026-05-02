import { create } from 'zustand';
import type { ChatAttachment, ChatSessionListItem } from '@/api';
import {
  applyAgentResponse,
  applyTurnUxPlan as applyTurnUxPlanUpdate,
  createPendingTurn,
  type ChatTimelineMessageLabel,
  type ChatTimelineMessage,
  type ChatTimelineReplyPreview,
  type NormalizedExecutionTraceSummary,
  type NormalizedTurnUxPlan,
  type ReasoningTrace,
  type ToolCallTrace,
  upsertTraceSummary as applyTraceSummaryUpdate,
} from '@/domain/chat/state';
import { isTranscriptMessage } from '@/domain/chat/presentation';

type AgentResponsePayload = {
  sessionId: string;
  content: string;
  attachments?: ChatAttachment[];
  timestamp: number;
  messageId?: string;
  messageKind?: string | null;
  personaId?: string | null;
  turnId?: string;
  traceSummary?: NormalizedExecutionTraceSummary | null;
  traceAvailable?: boolean;
  uxPlan?: NormalizedTurnUxPlan | null;
  payload?: Record<string, unknown> | null;
};

type StreamTextDeltaPayload = {
  sessionId: string;
  turnId: string;
  personaId?: string | null;
  textDelta: string;
};

type StreamTextFlushPayload = {
  sessionId: string;
  turnId: string;
  personaId?: string | null;
};

type StreamReasoningDeltaPayload = {
  sessionId: string;
  turnId: string;
  source: string;
  stepLabel?: string | null;
  personaId?: string | null;
  textDelta: string;
};

type StreamToolCallPayload = {
  sessionId: string;
  turnId: string;
  toolCallId?: string | null;
  toolName?: string | null;
  toolArgsDelta?: string;
  toolArguments?: Record<string, unknown> | null;
  personaId?: string | null;
  status: 'running' | 'completed';
};

type PendingTurnPayload = {
  sessionId: string;
  input: string;
  turnId: string;
  timestamp: number;
  pendingLabel: string;
  attachments?: ChatAttachment[];
  replyTo?: ChatTimelineReplyPreview | null;
};

type TurnUxPlanPayload = {
  sessionId: string;
  turnId: string;
  uxPlan: NormalizedTurnUxPlan | null;
  pendingLabel?: string;
  messageId?: string;
  messageKind?: string | null;
  timestamp?: number;
};

type ConversationState = {
  currentSessionId: string | null;
  orderedSessionIds: string[];
  sessionsById: Record<string, ChatSessionListItem>;
  messagesBySession: Record<string, ChatTimelineMessage[]>;
  unreadBySession: Record<string, number>;
  setCurrentSessionId: (sessionId: string | null) => void;
  hydrateSessions: (sessions: ChatSessionListItem[], currentSessionId?: string | null) => void;
  upsertSession: (session: ChatSessionListItem) => void;
  receiveHistory: (sessionId: string, messages: ChatTimelineMessage[]) => void;
  upsertMessage: (sessionId: string, message: ChatTimelineMessage) => void;
  appendPendingTurn: (payload: PendingTurnPayload) => void;
  applyTurnUxPlan: (payload: TurnUxPlanPayload) => void;
  receiveAgentResponse: (payload: AgentResponsePayload) => void;
  appendStreamTextDelta: (payload: StreamTextDeltaPayload) => void;
  appendStreamTextFlush: (payload: StreamTextFlushPayload) => void;
  appendStreamReasoningDelta: (payload: StreamReasoningDeltaPayload) => void;
  appendStreamToolCall: (payload: StreamToolCallPayload) => void;
  applyMessageLabel: (sessionId: string, messageId: string, label: ChatTimelineMessageLabel) => void;
  removeMessage: (sessionId: string, messageId: string) => void;
  upsertTraceSummary: (sessionId: string, turnId: string, summary: NormalizedExecutionTraceSummary | null) => void;
  reset: () => void;
};

const emptyState = {
  currentSessionId: null,
  orderedSessionIds: [] as string[],
  sessionsById: {} as Record<string, ChatSessionListItem>,
  messagesBySession: {} as Record<string, ChatTimelineMessage[]>,
  unreadBySession: {} as Record<string, number>,
};

const appendReasoning = (
  prev: ReasoningTrace[] | undefined,
  source: string,
  stepLabel: string | null | undefined,
  textDelta: string,
): ReasoningTrace[] => {
  const list = prev ? [...prev] : [];
  const normalizedLabel = stepLabel ?? null;
  const lastIdx = list.length - 1;
  if (lastIdx >= 0) {
    const last = list[lastIdx];
    if (last.source === source && (last.stepLabel ?? null) === normalizedLabel) {
      list[lastIdx] = { ...last, content: last.content + textDelta };
      return list;
    }
  }
  list.push({ source, stepLabel: normalizedLabel, content: textDelta });
  return list;
};

const appendToolCall = (
  prev: ToolCallTrace[] | undefined,
  payload: StreamToolCallPayload,
): ToolCallTrace[] => {
  const list = prev ? [...prev] : [];
  const normalizedToolName = String(payload.toolName || '').trim() || 'Tool';
  const normalizedArgsDelta = typeof payload.toolArgsDelta === 'string' ? payload.toolArgsDelta : '';
  const nextArguments = payload.toolArguments ?? undefined;
  const index = list.findIndex((item) => {
    if (payload.toolCallId && item.toolCallId) {
      return item.toolCallId === payload.toolCallId;
    }
    return item.toolName === normalizedToolName;
  });

  if (index >= 0) {
    const current = list[index];
    list[index] = {
      ...current,
      toolCallId: payload.toolCallId ?? current.toolCallId,
      toolName: payload.toolName ? normalizedToolName : current.toolName,
      status: payload.status,
      toolArgsText: normalizedArgsDelta
        ? `${current.toolArgsText || ''}${normalizedArgsDelta}`
        : current.toolArgsText,
      toolArguments: nextArguments ?? current.toolArguments,
    };
    return list;
  }

  list.push({
    toolCallId: payload.toolCallId ?? null,
    toolName: normalizedToolName,
    status: payload.status,
    toolArgsText: normalizedArgsDelta || undefined,
    toolArguments: nextArguments ?? null,
  });
  return list;
};

const findStreamingAssistantIndex = (
  messages: ChatTimelineMessage[],
  turnId: string,
): number => {
  const existingIndex = messages.findIndex(
    (m) => m.role === 'assistant' && m.turnId === turnId && m.streaming,
  );
  if (existingIndex >= 0) {
    return existingIndex;
  }
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const candidate = messages[i];
    if (
      candidate.role === 'assistant'
      && candidate.turnId === turnId
      && !candidate.messageId
    ) {
      return i;
    }
  }
  return -1;
};

const ensureSession = (
  sessionsById: Record<string, ChatSessionListItem>,
  orderedSessionIds: string[],
  sessionId: string,
) => {
  if (!sessionId) {
    return { sessionsById, orderedSessionIds };
  }
  if (sessionsById[sessionId]) {
    return { sessionsById, orderedSessionIds };
  }
  return {
    sessionsById: {
      ...sessionsById,
      [sessionId]: {
        session_id: sessionId,
        title: 'New Chat',
        last_message_preview: '',
        last_user_message_preview: '',
        title_overridden: false,
        last_timestamp: 0,
        message_count: 0,
        workspace_path: null,
      },
    },
    orderedSessionIds: [sessionId, ...orderedSessionIds],
  };
};

const upsertSessionSummary = (
  sessionsById: Record<string, ChatSessionListItem>,
  orderedSessionIds: string[],
  session: ChatSessionListItem,
) => {
  const nextOrder = orderedSessionIds.filter((sessionId) => sessionId !== session.session_id);
  nextOrder.unshift(session.session_id);
  return {
    sessionsById: {
      ...sessionsById,
      [session.session_id]: session,
    },
    orderedSessionIds: nextOrder,
  };
};

const sortTimelineMessages = (messages: ChatTimelineMessage[]): ChatTimelineMessage[] => (
  [...messages].sort((left, right) => {
    const timestampDiff = Number(left.timestamp || 0) - Number(right.timestamp || 0);
    if (timestampDiff !== 0) {
      return timestampDiff;
    }
    if (left.role === right.role) {
      return 0;
    }
    return left.role === 'user' ? -1 : 1;
  })
);

const canMergeTimelineMessage = (
  existing: ChatTimelineMessage,
  incoming: ChatTimelineMessage,
): boolean => {
  const existingMessageId = String(existing.messageId || '').trim();
  const incomingMessageId = String(incoming.messageId || '').trim();
  if (existingMessageId && incomingMessageId) {
    return existingMessageId === incomingMessageId;
  }

  const existingTurnId = String(existing.turnId || '').trim();
  const incomingTurnId = String(incoming.turnId || '').trim();
  if (!existingTurnId || !incomingTurnId || existingTurnId !== incomingTurnId || existing.role !== incoming.role) {
    return false;
  }

  const incomingIsAssistantTranscript = incoming.role === 'assistant' && incoming.kind === 'assistant';

  // A streaming assistant transcript is mergeable with later persisted
  // assistant transcript rows for the same turn, but not with control/status
  // rows such as todo_state.
  if (existing.streaming && incomingIsAssistantTranscript) {
    return true;
  }

  // A completed-streaming placeholder (no persisted messageId) is mergeable with
  // the persisted assistant transcript for the same turn so the duplicate is replaced.
  if (!existingMessageId && incomingMessageId && incomingIsAssistantTranscript) {
    return true;
  }

  if (existing.role === 'user') {
    return existing.kind === 'user' && incoming.kind === 'user';
  }

  const existingMessageKind = String(existing.messageKind || '').trim();
  const incomingMessageKind = String(incoming.messageKind || '').trim();
  return Boolean(existingMessageKind && incomingMessageKind && existingMessageKind === incomingMessageKind);
};

const mergeTimelineMessage = (
  existing: ChatTimelineMessage,
  incoming: ChatTimelineMessage,
): ChatTimelineMessage => ({
  ...existing,
  ...incoming,
  id: String(incoming.messageId || existing.messageId || incoming.id || existing.id),
  messageId: incoming.messageId ?? existing.messageId,
  messageKind: incoming.messageKind ?? existing.messageKind ?? null,
  turnId: incoming.turnId ?? existing.turnId,
  replyTo: incoming.replyTo ?? existing.replyTo ?? null,
  label: incoming.label ?? existing.label ?? null,
  reaction: incoming.reaction ?? existing.reaction ?? null,
  attachments: incoming.attachments ?? existing.attachments,
  traceDisplayMode: incoming.traceDisplayMode ?? existing.traceDisplayMode ?? null,
  allowTraceCollapse: typeof incoming.allowTraceCollapse === 'boolean'
    ? incoming.allowTraceCollapse
    : Boolean(existing.allowTraceCollapse),
  traceSummary: incoming.traceSummary ?? existing.traceSummary ?? null,
  traceAvailable: typeof incoming.traceAvailable === 'boolean'
    ? incoming.traceAvailable
    : Boolean(existing.traceAvailable),
  personaId: incoming.personaId ?? existing.personaId ?? null,
});

const upsertTimelineMessage = (
  messages: ChatTimelineMessage[],
  incoming: ChatTimelineMessage,
): ChatTimelineMessage[] => {
  const existingIndex = messages.findIndex((message) => canMergeTimelineMessage(message, incoming));
  if (existingIndex < 0) {
    return sortTimelineMessages([...messages, incoming]);
  }
  const nextMessages = [...messages];
  nextMessages[existingIndex] = mergeTimelineMessage(messages[existingIndex], incoming);
  return sortTimelineMessages(nextMessages);
};

const mergeHistorySnapshot = (
  existingMessages: ChatTimelineMessage[],
  snapshotMessages: ChatTimelineMessage[],
): ChatTimelineMessage[] => {
  const mergedSnapshot = snapshotMessages.map((message) => {
    const existingMatch = existingMessages.find((current) => canMergeTimelineMessage(current, message));
    return existingMatch ? mergeTimelineMessage(existingMatch, message) : message;
  });

  const localPendingMessages = existingMessages.filter((message) => {
    if (String(message.messageId || '').trim()) {
      return false;
    }
    return !snapshotMessages.some((snapshotMessage) => canMergeTimelineMessage(message, snapshotMessage));
  });

  return sortTimelineMessages([...mergedSnapshot, ...localPendingMessages]);
};

export const useConversationStore = create<ConversationState>((set) => ({
  ...emptyState,
  setCurrentSessionId: (sessionId) => set((state) => ({
    currentSessionId: sessionId,
    unreadBySession: sessionId
      ? { ...state.unreadBySession, [sessionId]: 0 }
      : state.unreadBySession,
  })),
  hydrateSessions: (sessions, currentSessionId) => set((state) => {
    const nextSessionsById = { ...state.sessionsById };
    const nextOrder: string[] = [];

    for (const session of sessions) {
      nextSessionsById[session.session_id] = session;
      nextOrder.push(session.session_id);
    }

    const hasLocalSelection =
      Boolean(state.currentSessionId) &&
      nextOrder.includes(state.currentSessionId as string);
    const nextCurrentSessionId = hasLocalSelection
      ? state.currentSessionId
      : (
        (currentSessionId && nextOrder.includes(currentSessionId) ? currentSessionId : null)
        ?? nextOrder[0]
        ?? null
      );

    return {
      sessionsById: nextSessionsById,
      orderedSessionIds: nextOrder,
      currentSessionId: nextCurrentSessionId,
      unreadBySession:
        nextCurrentSessionId
          ? { ...state.unreadBySession, [nextCurrentSessionId]: 0 }
          : state.unreadBySession,
    };
  }),
  upsertSession: (session) => set((state) => {
    const nextSummaryState = upsertSessionSummary(state.sessionsById, state.orderedSessionIds, session);
    return {
      sessionsById: nextSummaryState.sessionsById,
      orderedSessionIds: nextSummaryState.orderedSessionIds,
    };
  }),
  receiveHistory: (sessionId, messages) => set((state) => {
    const ensured = ensureSession(state.sessionsById, state.orderedSessionIds, sessionId);
    const previousMessages = state.messagesBySession[sessionId] || [];
    return {
      currentSessionId: sessionId,
      sessionsById: ensured.sessionsById,
      orderedSessionIds: ensured.orderedSessionIds,
      messagesBySession: {
        ...state.messagesBySession,
        [sessionId]: mergeHistorySnapshot(previousMessages, messages),
      },
      unreadBySession: {
        ...state.unreadBySession,
        [sessionId]: 0,
      },
    };
  }),
  upsertMessage: (sessionId, message) => set((state) => {
    if (!sessionId) {
      return state;
    }
    const ensured = ensureSession(state.sessionsById, state.orderedSessionIds, sessionId);
    return {
      currentSessionId: state.currentSessionId,
      sessionsById: ensured.sessionsById,
      orderedSessionIds: ensured.orderedSessionIds,
      messagesBySession: {
        ...state.messagesBySession,
        [sessionId]: upsertTimelineMessage(state.messagesBySession[sessionId] || [], message),
      },
    };
  }),
  appendPendingTurn: ({ sessionId, input, turnId, timestamp, pendingLabel, attachments, replyTo }) => set((state) => {
    const ensured = ensureSession(state.sessionsById, state.orderedSessionIds, sessionId);
    const previousMessages = state.messagesBySession[sessionId] || [];
    const previewText = input.trim() || (attachments || []).map((attachment) => attachment.original_name).join(', ').trim();
    const nextMessages = [
      ...previousMessages,
      ...createPendingTurn(input, turnId, timestamp, pendingLabel, attachments || [], replyTo || null),
    ];
    return {
      currentSessionId: sessionId,
      orderedSessionIds: ensured.orderedSessionIds,
      messagesBySession: {
        ...state.messagesBySession,
        [sessionId]: nextMessages,
      },
      sessionsById: {
        ...ensured.sessionsById,
        [sessionId]: {
          ...(ensured.sessionsById[sessionId] || {
            session_id: sessionId,
            title: input,
            last_message_preview: '',
            last_user_message_preview: '',
            title_overridden: false,
            last_timestamp: 0,
            message_count: 0,
            workspace_path: null,
          }),
          last_user_message_preview: previewText,
          last_timestamp: Math.floor(timestamp / 1000),
        },
      },
      unreadBySession: {
        ...state.unreadBySession,
        [sessionId]: 0,
      },
    };
  }),
  applyTurnUxPlan: ({ sessionId, turnId, uxPlan, pendingLabel, messageId, messageKind, timestamp }) => set((state) => {
    if (!sessionId || !turnId || !uxPlan) {
      return state;
    }
    const ensured = ensureSession(state.sessionsById, state.orderedSessionIds, sessionId);
    return {
      currentSessionId: sessionId,
      orderedSessionIds: ensured.orderedSessionIds,
      sessionsById: ensured.sessionsById,
      messagesBySession: {
        ...state.messagesBySession,
        [sessionId]: applyTurnUxPlanUpdate(
          state.messagesBySession[sessionId] || [],
          turnId,
          uxPlan,
          { pendingLabel, messageId, messageKind, timestamp }
        ),
      },
      unreadBySession: {
        ...state.unreadBySession,
        [sessionId]: state.currentSessionId === sessionId ? 0 : state.unreadBySession[sessionId] || 0,
      },
    };
  }),
  receiveAgentResponse: ({ sessionId, content, attachments, timestamp, messageId, messageKind, personaId, turnId, traceSummary, traceAvailable, uxPlan, payload }) => set((state) => {
    const ensured = ensureSession(state.sessionsById, state.orderedSessionIds, sessionId);
    const previousMessages = state.messagesBySession[sessionId] || [];
    const nextMessages = applyAgentResponse(previousMessages, {
      content,
      attachments,
      timestamp,
      messageId,
      messageKind,
      personaId,
      turnId,
      traceSummary,
      traceAvailable,
      uxPlan,
      payload,
    });
    const lastMessagePreview = content.trim() || ensured.sessionsById[sessionId]?.last_message_preview || '';
    const sessionSummary: ChatSessionListItem = {
      ...(ensured.sessionsById[sessionId] || {
        session_id: sessionId,
        title: 'New Chat',
        last_message_preview: '',
        last_user_message_preview: '',
        title_overridden: false,
        last_timestamp: 0,
        message_count: 0,
        workspace_path: null,
      }),
      session_id: sessionId,
      last_message_preview: lastMessagePreview,
      last_timestamp: Math.floor(timestamp / 1000),
      message_count: nextMessages.length,
    };
    const nextSummaryState = upsertSessionSummary(ensured.sessionsById, ensured.orderedSessionIds, sessionSummary);
    const shouldIncrementUnread = state.currentSessionId !== sessionId;
    return {
      sessionsById: nextSummaryState.sessionsById,
      orderedSessionIds: nextSummaryState.orderedSessionIds,
      messagesBySession: {
        ...state.messagesBySession,
        [sessionId]: nextMessages,
      },
      unreadBySession: {
        ...state.unreadBySession,
        [sessionId]: shouldIncrementUnread
          ? (state.unreadBySession[sessionId] || 0) + 1
          : 0,
      },
    };
  }),
  appendStreamTextDelta: ({ sessionId, turnId, personaId, textDelta }) => set((state) => {
    if (!sessionId || !turnId || !textDelta) {
      return state;
    }
    const previousMessages = state.messagesBySession[sessionId] || [];
    // Prefer an active streaming bubble for this turn. Fall back to the most
    // recent assistant placeholder for the same turn that has not yet been
    // replaced by a persisted message (no messageId) — this keeps multi-step
    // turns rendered as a single bubble even if a stray text_flush arrived
    // between LLM calls.
    const existingIndex = findStreamingAssistantIndex(previousMessages, turnId);
    if (existingIndex >= 0) {
      const existing = previousMessages[existingIndex];
      const nextMessages = [...previousMessages];
      nextMessages[existingIndex] = {
        ...existing,
        content: existing.content + textDelta,
        personaId: personaId ?? existing.personaId ?? null,
        streaming: true,
      };
      return {
        messagesBySession: {
          ...state.messagesBySession,
          [sessionId]: nextMessages,
        },
      };
    }
    const ensured = ensureSession(state.sessionsById, state.orderedSessionIds, sessionId);
    const streamingMessage: ChatTimelineMessage = {
      id: `stream_${turnId}`,
      role: 'assistant',
      kind: 'assistant' as ChatTimelineMessage['kind'],
      content: textDelta,
      timestamp: Date.now(),
      turnId,
      personaId: personaId ?? null,
      streaming: true,
    };
    return {
      sessionsById: ensured.sessionsById,
      orderedSessionIds: ensured.orderedSessionIds,
      messagesBySession: {
        ...state.messagesBySession,
        [sessionId]: [...previousMessages, streamingMessage],
      },
    };
  }),
  appendStreamTextFlush: ({ sessionId, turnId, personaId }) => set((state) => {
    if (!sessionId || !turnId) {
      return state;
    }
    const previousMessages = state.messagesBySession[sessionId] || [];
    const existingIndex = previousMessages.findIndex(
      (m) => m.role === 'assistant' && m.turnId === turnId && m.streaming,
    );
    if (existingIndex < 0) {
      return state;
    }
    const existing = previousMessages[existingIndex];
    const nextMessages = [...previousMessages];
    nextMessages[existingIndex] = {
      ...existing,
      personaId: personaId ?? existing.personaId ?? null,
      streaming: false,
    };
    return {
      messagesBySession: {
        ...state.messagesBySession,
        [sessionId]: nextMessages,
      },
    };
  }),
  appendStreamReasoningDelta: ({ sessionId, turnId, source, stepLabel, personaId, textDelta }) => set((state) => {
    if (!sessionId || !turnId || !textDelta) {
      return state;
    }
    const previousMessages = state.messagesBySession[sessionId] || [];
    const existingIndex = findStreamingAssistantIndex(previousMessages, turnId);
    let messages = previousMessages;
    let targetIndex = existingIndex;
    if (existingIndex < 0) {
      const ensured = ensureSession(state.sessionsById, state.orderedSessionIds, sessionId);
      const placeholder: ChatTimelineMessage = {
        id: `stream_${turnId}`,
        role: 'assistant',
        kind: 'assistant' as ChatTimelineMessage['kind'],
        content: '',
        timestamp: Date.now(),
        turnId,
        personaId: personaId ?? null,
        streaming: true,
        reasoning: [],
      };
      messages = [...previousMessages, placeholder];
      targetIndex = messages.length - 1;
      const target = messages[targetIndex];
      const nextReasoning = appendReasoning(target.reasoning, source, stepLabel, textDelta);
      messages[targetIndex] = { ...target, personaId: personaId ?? target.personaId ?? null, reasoning: nextReasoning };
      return {
        sessionsById: ensured.sessionsById,
        orderedSessionIds: ensured.orderedSessionIds,
        messagesBySession: {
          ...state.messagesBySession,
          [sessionId]: messages,
        },
      };
    }
    const target = previousMessages[targetIndex];
    const nextReasoning = appendReasoning(target.reasoning, source, stepLabel, textDelta);
    const nextMessages = [...previousMessages];
    nextMessages[targetIndex] = { ...target, personaId: personaId ?? target.personaId ?? null, reasoning: nextReasoning };
    return {
      messagesBySession: {
        ...state.messagesBySession,
        [sessionId]: nextMessages,
      },
    };
  }),
  appendStreamToolCall: ({ sessionId, turnId, toolCallId, toolName, toolArgsDelta, toolArguments, personaId, status }) => set((state) => {
    if (!sessionId || !turnId) {
      return state;
    }
    const previousMessages = state.messagesBySession[sessionId] || [];
    const existingIndex = findStreamingAssistantIndex(previousMessages, turnId);
    let messages = previousMessages;
    let targetIndex = existingIndex;

    if (existingIndex < 0) {
      const ensured = ensureSession(state.sessionsById, state.orderedSessionIds, sessionId);
      const placeholder: ChatTimelineMessage = {
        id: `stream_${turnId}`,
        role: 'assistant',
        kind: 'assistant' as ChatTimelineMessage['kind'],
        content: '',
        timestamp: Date.now(),
        turnId,
        personaId: personaId ?? null,
        streaming: true,
        toolCalls: [],
      };
      messages = [...previousMessages, placeholder];
      targetIndex = messages.length - 1;
      const target = messages[targetIndex];
      const nextToolCalls = appendToolCall(target.toolCalls, {
        sessionId,
        turnId,
        toolCallId,
        toolName,
        toolArgsDelta,
        toolArguments,
        status,
      });
      messages[targetIndex] = { ...target, personaId: personaId ?? target.personaId ?? null, toolCalls: nextToolCalls };
      return {
        sessionsById: ensured.sessionsById,
        orderedSessionIds: ensured.orderedSessionIds,
        messagesBySession: {
          ...state.messagesBySession,
          [sessionId]: messages,
        },
      };
    }

    const target = previousMessages[targetIndex];
    const nextToolCalls = appendToolCall(target.toolCalls, {
      sessionId,
      turnId,
      toolCallId,
      toolName,
      toolArgsDelta,
      toolArguments,
      status,
    });
    const nextMessages = [...previousMessages];
    nextMessages[targetIndex] = { ...target, personaId: personaId ?? target.personaId ?? null, toolCalls: nextToolCalls };
    return {
      messagesBySession: {
        ...state.messagesBySession,
        [sessionId]: nextMessages,
      },
    };
  }),
  applyMessageLabel: (sessionId, messageId, label) => set((state) => {
    if (!sessionId || !messageId) {
      return state;
    }
    const previousMessages = state.messagesBySession[sessionId] || [];
    let updated = false;
    const nextMessages = previousMessages.map((message) => {
      if (message.messageId !== messageId) {
        return message;
      }
      updated = true;
      return {
        ...message,
        label,
      };
    });
    if (!updated) {
      return state;
    }
    return {
      messagesBySession: {
        ...state.messagesBySession,
        [sessionId]: nextMessages,
      },
    };
  }),
  removeMessage: (sessionId, messageId) => set((state) => {
    if (!sessionId || !messageId) {
      return state;
    }
    const previousMessages = state.messagesBySession[sessionId] || [];
    const nextMessages = previousMessages.filter((message) => message.messageId !== messageId);
    if (nextMessages.length === previousMessages.length) {
      return state;
    }
    const currentSession = state.sessionsById[sessionId];
    const visibleMessages = nextMessages.filter(isTranscriptMessage);
    const lastVisibleMessage = [...visibleMessages].reverse().find((message) => Boolean(String(message.content || '').trim()));
    const lastVisibleUserMessage = [...visibleMessages]
      .reverse()
      .find((message) => message.role === 'user' && Boolean(String(message.content || '').trim()));
    return {
      messagesBySession: {
        ...state.messagesBySession,
        [sessionId]: nextMessages,
      },
      sessionsById: currentSession
        ? {
          ...state.sessionsById,
          [sessionId]: {
            ...currentSession,
            last_message_preview: lastVisibleMessage?.content || '',
            last_user_message_preview: lastVisibleUserMessage?.content || '',
            message_count: visibleMessages.length,
            last_timestamp: visibleMessages.length > 0
              ? Math.floor((visibleMessages[visibleMessages.length - 1]?.timestamp || 0) / 1000)
              : 0,
          },
        }
        : state.sessionsById,
    };
  }),
  upsertTraceSummary: (sessionId, turnId, summary) => set((state) => ({
    messagesBySession: {
      ...state.messagesBySession,
      [sessionId]: applyTraceSummaryUpdate(state.messagesBySession[sessionId] || [], turnId, summary),
    },
  })),
  reset: () => set({
    currentSessionId: null,
    orderedSessionIds: [],
    sessionsById: {},
    messagesBySession: {},
    unreadBySession: {},
  }),
}));
