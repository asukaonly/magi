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
  upsertTraceSummary as applyTraceSummaryUpdate,
} from '@/domain/chat/state';
import { isTranscriptMessage } from '@/domain/chat/presentation';
import {
  buildReadCursor,
  loadReadCursors,
  persistSessionReadCursor,
  readCursorsInitialized,
  saveReadCursors,
  unreadCountFromCursor,
} from '@/stores/conversation-read-cursors';
import {
  canMergeTimelineMessage,
  mergeHistorySnapshot,
  upsertTimelineMessage,
} from '@/stores/conversation-timeline';
import {
  applyStreamReasoningDelta,
  applyStreamStatusUpdate,
  applyStreamTextDelta,
  applyStreamTextFlush,
  applyStreamToolCall,
  type StreamMessageUpdate,
  type StreamReasoningDeltaPayload,
  type StreamStatusUpdatePayload,
  type StreamTextDeltaPayload,
  type StreamTextFlushPayload,
  type StreamToolCallPayload,
} from '@/stores/conversation-streaming';

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

type PendingTurnPayload = {
  sessionId: string;
  input: string;
  turnId: string;
  timestamp: number;
  pendingLabel: string;
  attachments?: ChatAttachment[];
  replyTo?: ChatTimelineReplyPreview | null;
  payload?: Record<string, unknown> | null;
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
  historyVersionBySession: Record<string, number>;
  unreadBySession: Record<string, number>;
  setCurrentSessionId: (sessionId: string | null) => void;
  hydrateSessions: (sessions: ChatSessionListItem[], currentSessionId?: string | null) => void;
  upsertSession: (session: ChatSessionListItem) => void;
  receiveHistory: (sessionId: string, messages: ChatTimelineMessage[], historyVersion?: number | null) => void;
  upsertMessage: (sessionId: string, message: ChatTimelineMessage) => void;
  appendPendingTurn: (payload: PendingTurnPayload) => void;
  applyTurnUxPlan: (payload: TurnUxPlanPayload) => void;
  receiveAgentResponse: (payload: AgentResponsePayload) => void;
  appendStreamTextDelta: (payload: StreamTextDeltaPayload & { sessionId: string }) => void;
  appendStreamTextFlush: (payload: StreamTextFlushPayload & { sessionId: string }) => void;
  appendStreamReasoningDelta: (payload: StreamReasoningDeltaPayload & { sessionId: string }) => void;
  appendStreamStatusUpdate: (payload: StreamStatusUpdatePayload & { sessionId: string }) => void;
  appendStreamToolCall: (payload: StreamToolCallPayload & { sessionId: string }) => void;
  applyMessageLabel: (sessionId: string, messageId: string, label: ChatTimelineMessageLabel) => void;
  removeMessage: (sessionId: string, messageId: string) => void;
  clearSessionHistory: (sessionId: string) => void;
  upsertTraceSummary: (sessionId: string, turnId: string, summary: NormalizedExecutionTraceSummary | null) => void;
  reset: () => void;
};

const emptyState = {
  currentSessionId: null,
  orderedSessionIds: [] as string[],
  sessionsById: {} as Record<string, ChatSessionListItem>,
  messagesBySession: {} as Record<string, ChatTimelineMessage[]>,
  historyVersionBySession: {} as Record<string, number>,
  unreadBySession: {} as Record<string, number>,
};

const isUnreadWorthyMessage = (message: ChatTimelineMessage): boolean => (
  message.role !== 'user'
  && isTranscriptMessage(message)
  && !message.streaming
);

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

type ConversationStoreSnapshot = Pick<
  ConversationState,
  'sessionsById' | 'orderedSessionIds' | 'messagesBySession'
>;

const applyStreamUpdateToState = (
  state: ConversationStoreSnapshot,
  sessionId: string,
  update: StreamMessageUpdate,
) => {
  if (!update.changed) {
    return state;
  }
  const ensured = update.needsSession
    ? ensureSession(state.sessionsById, state.orderedSessionIds, sessionId)
    : { sessionsById: state.sessionsById, orderedSessionIds: state.orderedSessionIds };
  return {
    sessionsById: ensured.sessionsById,
    orderedSessionIds: ensured.orderedSessionIds,
    messagesBySession: {
      ...state.messagesBySession,
      [sessionId]: update.messages,
    },
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

export const useConversationStore = create<ConversationState>((set) => ({
  ...emptyState,
  setCurrentSessionId: (sessionId) => set((state) => {
    if (sessionId) {
      persistSessionReadCursor(
        sessionId,
        state.sessionsById[sessionId],
        state.messagesBySession[sessionId] || [],
      );
    }
    return {
      currentSessionId: sessionId,
      unreadBySession: sessionId
        ? { ...state.unreadBySession, [sessionId]: 0 }
        : state.unreadBySession,
    };
  }),
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
    const cursors = loadReadCursors();
    const initialized = readCursorsInitialized();
    const nextUnreadBySession: Record<string, number> = {};

    for (const session of sessions) {
      if (session.session_id === nextCurrentSessionId) {
        cursors[session.session_id] = buildReadCursor(
          session,
          state.messagesBySession[session.session_id] || [],
        );
        nextUnreadBySession[session.session_id] = 0;
        continue;
      }
      if (!initialized) {
        cursors[session.session_id] = buildReadCursor(
          session,
          state.messagesBySession[session.session_id] || [],
        );
        nextUnreadBySession[session.session_id] = 0;
        continue;
      }
      nextUnreadBySession[session.session_id] = unreadCountFromCursor(session, cursors[session.session_id]);
    }

    if (sessions.length > 0 || nextCurrentSessionId) {
      saveReadCursors(cursors);
    }

    return {
      sessionsById: nextSessionsById,
      orderedSessionIds: nextOrder,
      currentSessionId: nextCurrentSessionId,
      unreadBySession: nextUnreadBySession,
    };
  }),
  upsertSession: (session) => set((state) => {
    const nextSummaryState = upsertSessionSummary(state.sessionsById, state.orderedSessionIds, session);
    const currentMessages = state.messagesBySession[session.session_id] || [];
    const nextUnreadBySession = { ...state.unreadBySession };
    if (state.currentSessionId === session.session_id) {
      persistSessionReadCursor(session.session_id, session, currentMessages);
      nextUnreadBySession[session.session_id] = 0;
    } else if (readCursorsInitialized()) {
      nextUnreadBySession[session.session_id] = unreadCountFromCursor(
        session,
        loadReadCursors()[session.session_id],
      );
    }
    return {
      sessionsById: nextSummaryState.sessionsById,
      orderedSessionIds: nextSummaryState.orderedSessionIds,
      unreadBySession: nextUnreadBySession,
    };
  }),
  receiveHistory: (sessionId, messages, historyVersion) => set((state) => {
    const ensured = ensureSession(state.sessionsById, state.orderedSessionIds, sessionId);
    const previousMessages = state.messagesBySession[sessionId] || [];
    const normalizedHistoryVersion = Number(historyVersion);
    const shouldRecordHistoryVersion = Number.isFinite(normalizedHistoryVersion) && normalizedHistoryVersion >= 0;
    const mergedMessages = mergeHistorySnapshot(previousMessages, messages);
    if (state.currentSessionId === sessionId) {
      persistSessionReadCursor(sessionId, ensured.sessionsById[sessionId], mergedMessages);
    }
    const newUnreadMessageCount = state.currentSessionId === sessionId
      ? 0
      : messages.filter((message) => (
        isUnreadWorthyMessage(message)
        && !previousMessages.some((current) => canMergeTimelineMessage(current, message))
      )).length;
    return {
      currentSessionId: state.currentSessionId,
      sessionsById: ensured.sessionsById,
      orderedSessionIds: ensured.orderedSessionIds,
      messagesBySession: {
        ...state.messagesBySession,
        [sessionId]: mergedMessages,
      },
      historyVersionBySession: shouldRecordHistoryVersion
        ? {
          ...state.historyVersionBySession,
          [sessionId]: Math.trunc(normalizedHistoryVersion),
        }
        : state.historyVersionBySession,
      unreadBySession: {
        ...state.unreadBySession,
        [sessionId]: state.currentSessionId === sessionId
          ? 0
          : (state.unreadBySession[sessionId] || 0) + newUnreadMessageCount,
      },
    };
  }),
  upsertMessage: (sessionId, message) => set((state) => {
    if (!sessionId) {
      return state;
    }
    const ensured = ensureSession(state.sessionsById, state.orderedSessionIds, sessionId);
    const previousMessages = state.messagesBySession[sessionId] || [];
    const hadExistingMessage = previousMessages.some((existing) => canMergeTimelineMessage(existing, message));
    const nextMessages = upsertTimelineMessage(previousMessages, message);
    const shouldIncrementUnread = (
      state.currentSessionId !== sessionId
      && !hadExistingMessage
      && isUnreadWorthyMessage(message)
    );
    if (state.currentSessionId === sessionId) {
      persistSessionReadCursor(sessionId, ensured.sessionsById[sessionId], nextMessages);
    }
    return {
      currentSessionId: state.currentSessionId,
      sessionsById: ensured.sessionsById,
      orderedSessionIds: ensured.orderedSessionIds,
      messagesBySession: {
        ...state.messagesBySession,
        [sessionId]: nextMessages,
      },
      unreadBySession: {
        ...state.unreadBySession,
        [sessionId]: shouldIncrementUnread
          ? (state.unreadBySession[sessionId] || 0) + 1
          : (state.currentSessionId === sessionId ? 0 : state.unreadBySession[sessionId] || 0),
      },
    };
  }),
  appendPendingTurn: ({ sessionId, input, turnId, timestamp, pendingLabel, attachments, replyTo, payload }) => set((state) => {
    const ensured = ensureSession(state.sessionsById, state.orderedSessionIds, sessionId);
    const previousMessages = state.messagesBySession[sessionId] || [];
    const previewText = input.trim() || (attachments || []).map((attachment) => attachment.original_name).join(', ').trim();
    const nextMessages = [
      ...previousMessages,
      ...createPendingTurn(
        input,
        turnId,
        timestamp,
        pendingLabel,
        attachments || [],
        replyTo || null,
        payload || null,
      ),
    ];
    const nextSession = {
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
    };
    persistSessionReadCursor(sessionId, nextSession, nextMessages);
    return {
      currentSessionId: state.currentSessionId,
      orderedSessionIds: ensured.orderedSessionIds,
      messagesBySession: {
        ...state.messagesBySession,
        [sessionId]: nextMessages,
      },
      sessionsById: {
        ...ensured.sessionsById,
        [sessionId]: nextSession,
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
      currentSessionId: state.currentSessionId,
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
    if (!shouldIncrementUnread) {
      persistSessionReadCursor(sessionId, sessionSummary, nextMessages);
    }
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
  appendStreamTextDelta: ({ sessionId, ...payload }) => set((state) => {
    if (!sessionId) {
      return state;
    }
    return applyStreamUpdateToState(
      state,
      sessionId,
      applyStreamTextDelta(state.messagesBySession[sessionId] || [], payload),
    );
  }),
  appendStreamTextFlush: ({ sessionId, ...payload }) => set((state) => {
    if (!sessionId) {
      return state;
    }
    return applyStreamUpdateToState(
      state,
      sessionId,
      applyStreamTextFlush(state.messagesBySession[sessionId] || [], payload),
    );
  }),
  appendStreamReasoningDelta: ({ sessionId, ...payload }) => set((state) => {
    if (!sessionId) {
      return state;
    }
    return applyStreamUpdateToState(
      state,
      sessionId,
      applyStreamReasoningDelta(state.messagesBySession[sessionId] || [], payload),
    );
  }),
  appendStreamStatusUpdate: ({ sessionId, ...payload }) => set((state) => {
    if (!sessionId) {
      return state;
    }
    return applyStreamUpdateToState(
      state,
      sessionId,
      applyStreamStatusUpdate(state.messagesBySession[sessionId] || [], payload),
    );
  }),
  appendStreamToolCall: ({ sessionId, ...payload }) => set((state) => {
    if (!sessionId) {
      return state;
    }
    return applyStreamUpdateToState(
      state,
      sessionId,
      applyStreamToolCall(state.messagesBySession[sessionId] || [], payload),
    );
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
    const nextMessages = previousMessages.filter(
      (message) => String(message.messageId || message.id) !== messageId,
    );
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
  clearSessionHistory: (sessionId) => set((state) => {
    const normalizedSessionId = String(sessionId || '').trim();
    if (!normalizedSessionId) return state;
    const currentSession = state.sessionsById[normalizedSessionId];
    return {
      messagesBySession: {
        ...state.messagesBySession,
        [normalizedSessionId]: [],
      },
      sessionsById: currentSession
        ? {
          ...state.sessionsById,
          [normalizedSessionId]: {
            ...currentSession,
            last_message_preview: '',
            last_user_message_preview: '',
            message_count: 0,
            last_timestamp: 0,
          },
        }
        : state.sessionsById,
      historyVersionBySession: {
        ...state.historyVersionBySession,
        [normalizedSessionId]: (state.historyVersionBySession[normalizedSessionId] || 0) + 1,
      },
      unreadBySession: {
        ...state.unreadBySession,
        [normalizedSessionId]: 0,
      },
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
    historyVersionBySession: {},
    unreadBySession: {},
  }),
}));
