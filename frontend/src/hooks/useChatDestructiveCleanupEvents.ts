import { useEffect } from 'react';

import { APP_EVENTS, subscribeToAppEvent } from '@/constants/events';
import type { PendingResponseTurnIdentity } from '@/domain/chat/turn-completion';
import {
  retireAllRealtimeChatProjections,
  retireRealtimeChatSession,
  retireRealtimeChatSessions,
} from '@/realtime/chat-projection-retirement';
import { useConversationStore } from '@/stores/conversation-store';
import { useContextUsageStore } from '@/stores/context-usage';
import { useDelegationsStore } from '@/stores/delegations-store';
import {
  clearAllPersistedChatRetries,
  clearPersistedChatRetriesForSession,
} from './chatRetryLifecycle';

type UseChatDestructiveCleanupEventsOptions = {
  clearAllAdmissionPendingTurns: () => void;
  clearAllInlineSkillRetries: () => void;
  clearAllPendingResponseTurns: () => void;
  clearAllRetryableSends: () => void;
  clearConversationBoundDraftState: () => void;
  clearDeletedSessionDraftState: () => void;
  clearInlineSkillRetriesForSession: (sessionId: string) => void;
  clearPendingResponseTurn: (
    expected?: Partial<PendingResponseTurnIdentity>,
  ) => void;
  clearAdmissionPendingTurn: (sessionId: string, turnId?: string) => void;
  clearRetryableSendsForSession: (sessionId: string) => void;
  clearSessionLifecycleState: (sessionId?: string) => void;
  clearSessionHistory: (sessionId: string) => void;
  getCurrentSessionId: () => string | null;
  resetTraceDrawer: () => void;
  resetConversation: () => void;
  setCurrentSessionId: (sessionId: string | null) => void;
};

export function useChatDestructiveCleanupEvents({
  clearAllAdmissionPendingTurns,
  clearAllInlineSkillRetries,
  clearAllPendingResponseTurns,
  clearAllRetryableSends,
  clearConversationBoundDraftState,
  clearDeletedSessionDraftState,
  clearInlineSkillRetriesForSession,
  clearPendingResponseTurn,
  clearAdmissionPendingTurn,
  clearRetryableSendsForSession,
  clearSessionLifecycleState,
  clearSessionHistory,
  getCurrentSessionId,
  resetTraceDrawer,
  resetConversation,
  setCurrentSessionId,
}: UseChatDestructiveCleanupEventsOptions): void {
  useEffect(() => {
    const unsubscribeSessionDeleted = subscribeToAppEvent(
      APP_EVENTS.CHAT_SESSION_DELETED,
      (event) => {
        const sessionId = String(
          (event as CustomEvent<{ sessionId?: unknown }>).detail?.sessionId
            || '',
        ).trim();
        if (!sessionId) {
          return;
        }
        retireRealtimeChatSession(sessionId);
        useContextUsageStore.getState().clear(sessionId);
        useDelegationsStore.getState().clearSession(sessionId);
        clearPersistedChatRetriesForSession(sessionId);
        clearRetryableSendsForSession(sessionId);
        clearInlineSkillRetriesForSession(sessionId);
        clearPendingResponseTurn({ sessionId });
        clearAdmissionPendingTurn(sessionId);
        clearSessionLifecycleState(sessionId);
        clearSessionHistory(sessionId);
        if (getCurrentSessionId() === sessionId) {
          clearDeletedSessionDraftState();
          setCurrentSessionId(null);
          resetTraceDrawer();
        }
      },
    );
    const unsubscribeMemoryCleared = subscribeToAppEvent(
      APP_EVENTS.MEMORY_CLEARED,
      () => {
        const conversation = useConversationStore.getState();
        retireRealtimeChatSessions(new Set([
          ...conversation.orderedSessionIds,
          ...Object.keys(conversation.sessionsById),
          ...Object.keys(conversation.messagesBySession),
        ]));
        retireAllRealtimeChatProjections();
        clearAllPersistedChatRetries();
        clearAllRetryableSends();
        clearAllInlineSkillRetries();
        clearAllPendingResponseTurns();
        clearAllAdmissionPendingTurns();
        clearConversationBoundDraftState();
        clearSessionLifecycleState();
        setCurrentSessionId(null);
        resetTraceDrawer();
        resetConversation();
        window.dispatchEvent(new Event(APP_EVENTS.SESSION_SYNC));
      },
    );
    return () => {
      unsubscribeSessionDeleted();
      unsubscribeMemoryCleared();
    };
  }, [
    clearAdmissionPendingTurn,
    clearAllAdmissionPendingTurns,
    clearAllInlineSkillRetries,
    clearAllPendingResponseTurns,
    clearAllRetryableSends,
    clearConversationBoundDraftState,
    clearDeletedSessionDraftState,
    clearInlineSkillRetriesForSession,
    clearPendingResponseTurn,
    clearRetryableSendsForSession,
    clearSessionLifecycleState,
    clearSessionHistory,
    getCurrentSessionId,
    resetTraceDrawer,
    resetConversation,
    setCurrentSessionId,
  ]);
}
