import { dispatchAppEvent } from '@/constants/events';
import { CHAT_SESSION_KEY, DEFAULT_USER_ID } from '@/constants';
import {
  retireAllRealtimeChatProjections,
  retireRealtimeChatSession,
  retireRealtimeChatSessions,
} from '@/realtime/chat-projection-retirement';
import { useChatTraceStore } from '@/stores/chat-trace';
import { useConversationStore } from '@/stores/conversation-store';
import { useContextUsageStore } from '@/stores/context-usage';
import { useDelegationsStore } from '@/stores/delegations-store';
import { useNotificationStore } from '@/stores/notifications';
import {
  deleteRetryableChatSendForTurn,
  deleteRetryableChatSendsForSession,
  deleteRetryableInlineSkillOperationsForSession,
  deleteRetryableInlineSkillOperationsForTurn,
  loadRetryableChatSends,
  loadRetryableInlineSkillOperations,
  saveRetryableChatSends,
  saveRetryableInlineSkillOperations,
} from './chatRetryableSendStorage';
import {
  invalidateAllChatHistory,
  invalidateAllChatRetries,
  invalidateChatHistorySession,
  invalidateChatRetrySession,
  invalidateChatRetryTurn,
} from './chatRetryInvalidation';

export const clearPersistedChatRetriesForTurn = (
  sessionId: string,
  turnId: string,
): void => {
  invalidateChatRetryTurn(sessionId, turnId);
  invalidateChatHistorySession(sessionId);
  const composerOperations = loadRetryableChatSends();
  const inlineOperations = loadRetryableInlineSkillOperations();
  deleteRetryableChatSendForTurn(composerOperations, sessionId, turnId);
  deleteRetryableInlineSkillOperationsForTurn(
    inlineOperations,
    sessionId,
    turnId,
  );
  saveRetryableChatSends(composerOperations);
  saveRetryableInlineSkillOperations(inlineOperations);
};

export const clearPersistedChatRetriesForSession = (
  sessionId: string,
): void => {
  invalidateChatRetrySession(sessionId);
  invalidateChatHistorySession(sessionId);
  const composerOperations = loadRetryableChatSends();
  const inlineOperations = loadRetryableInlineSkillOperations();
  deleteRetryableChatSendsForSession(composerOperations, sessionId);
  deleteRetryableInlineSkillOperationsForSession(inlineOperations, sessionId);
  saveRetryableChatSends(composerOperations);
  saveRetryableInlineSkillOperations(inlineOperations);
};

export const clearAllPersistedChatRetries = (): void => {
  invalidateAllChatRetries();
  invalidateAllChatHistory();
  saveRetryableChatSends(new Map());
  saveRetryableInlineSkillOperations(new Map());
};

export const completeChatSessionDeletion = (sessionId: string): void => {
  const normalizedSessionId = String(sessionId || '').trim();
  if (!normalizedSessionId) {
    return;
  }
  retireRealtimeChatSession(normalizedSessionId);
  clearPersistedChatRetriesForSession(normalizedSessionId);
  useContextUsageStore.getState().clear(normalizedSessionId);
  useDelegationsStore.getState().clearSession(normalizedSessionId);
  const conversation = useConversationStore.getState();
  conversation.clearSessionHistory(normalizedSessionId);
  dispatchAppEvent.chatSessionDeleted(normalizedSessionId);
};

export const completeMemoryClear = (): void => {
  clearAllPersistedChatRetries();
  const conversation = useConversationStore.getState();
  retireRealtimeChatSessions(new Set([
    ...conversation.orderedSessionIds,
    ...Object.keys(conversation.sessionsById),
    ...Object.keys(conversation.messagesBySession),
  ]));
  retireAllRealtimeChatProjections();
  conversation.reset();
  useChatTraceStore.getState().reset();
  useContextUsageStore.getState().reset();
  useDelegationsStore.getState().reset();
  const notifications = useNotificationStore.getState();
  notifications.discardMemoryConflicts();
  void notifications.refresh();
  try {
    window.localStorage.removeItem(CHAT_SESSION_KEY(DEFAULT_USER_ID));
  } catch {
    // Keep the in-memory reset authoritative when persistence fails.
  }
  dispatchAppEvent.memoryCleared();
};
