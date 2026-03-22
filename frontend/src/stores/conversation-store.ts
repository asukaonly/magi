import { create } from 'zustand';
import type { ChatSessionListItem } from '@/api';
import {
  applyAgentResponse,
  applyTurnUxPlan as applyTurnUxPlanUpdate,
  createPendingTurn,
  mergeHistoryMessages,
  type ChatTimelineMessage,
  type NormalizedExecutionTraceSummary,
  type NormalizedTurnUxPlan,
  upsertTraceSummary as applyTraceSummaryUpdate,
} from '@/pages/chat-state';

type AgentResponsePayload = {
  sessionId: string;
  content: string;
  timestamp: number;
  messageId?: string;
  messageKind?: string | null;
  turnId?: string;
  traceSummary?: NormalizedExecutionTraceSummary | null;
  traceAvailable?: boolean;
  uxPlan?: NormalizedTurnUxPlan | null;
};

type PendingTurnPayload = {
  sessionId: string;
  input: string;
  turnId: string;
  timestamp: number;
  pendingLabel: string;
};

type TurnUxPlanPayload = {
  sessionId: string;
  turnId: string;
  uxPlan: NormalizedTurnUxPlan | null;
  pendingLabel?: string;
};

type ConversationState = {
  currentSessionId: string | null;
  orderedSessionIds: string[];
  sessionsById: Record<string, ChatSessionListItem>;
  messagesBySession: Record<string, ChatTimelineMessage[]>;
  unreadBySession: Record<string, number>;
  setCurrentSessionId: (sessionId: string | null) => void;
  hydrateSessions: (sessions: ChatSessionListItem[], currentSessionId?: string | null) => void;
  receiveHistory: (sessionId: string, messages: ChatTimelineMessage[]) => void;
  appendPendingTurn: (payload: PendingTurnPayload) => void;
  applyTurnUxPlan: (payload: TurnUxPlanPayload) => void;
  receiveAgentResponse: (payload: AgentResponsePayload) => void;
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
  receiveHistory: (sessionId, messages) => set((state) => {
    const ensured = ensureSession(state.sessionsById, state.orderedSessionIds, sessionId);
    const mergedMessages = mergeHistoryMessages(state.messagesBySession[sessionId] || [], messages);
    return {
      currentSessionId: sessionId,
      sessionsById: ensured.sessionsById,
      orderedSessionIds: ensured.orderedSessionIds,
      messagesBySession: {
        ...state.messagesBySession,
        [sessionId]: mergedMessages,
      },
      unreadBySession: {
        ...state.unreadBySession,
        [sessionId]: 0,
      },
    };
  }),
  appendPendingTurn: ({ sessionId, input, turnId, timestamp, pendingLabel }) => set((state) => {
    const ensured = ensureSession(state.sessionsById, state.orderedSessionIds, sessionId);
    const previousMessages = state.messagesBySession[sessionId] || [];
    const nextMessages = [
      ...previousMessages,
      ...createPendingTurn(input, turnId, timestamp, pendingLabel),
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
          }),
          last_user_message_preview: input.trim(),
          last_timestamp: Math.floor(timestamp / 1000),
        },
      },
      unreadBySession: {
        ...state.unreadBySession,
        [sessionId]: 0,
      },
    };
  }),
  applyTurnUxPlan: ({ sessionId, turnId, uxPlan, pendingLabel }) => set((state) => {
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
          { pendingLabel }
        ),
      },
      unreadBySession: {
        ...state.unreadBySession,
        [sessionId]: state.currentSessionId === sessionId ? 0 : state.unreadBySession[sessionId] || 0,
      },
    };
  }),
  receiveAgentResponse: ({ sessionId, content, timestamp, messageId, messageKind, turnId, traceSummary, traceAvailable, uxPlan }) => set((state) => {
    const ensured = ensureSession(state.sessionsById, state.orderedSessionIds, sessionId);
    const previousMessages = state.messagesBySession[sessionId] || [];
    const nextMessages = applyAgentResponse(previousMessages, {
      content,
      timestamp,
      messageId,
      messageKind,
      turnId,
      traceSummary,
      traceAvailable,
      uxPlan,
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
  upsertTraceSummary: (sessionId, turnId, summary) => set((state) => ({
    messagesBySession: {
      ...state.messagesBySession,
      [sessionId]: applyTraceSummaryUpdate(state.messagesBySession[sessionId] || [], turnId, summary),
    },
  })),
  reset: () => ({
    ...emptyState,
  }),
}));
