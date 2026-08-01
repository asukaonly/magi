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
import { useBackgroundTaskStore } from '@/stores/background-tasks';
import { useChatShellStore } from '@/stores/chat-shell';
import { clearOnboardingContentState } from '@/components/onboarding/onboardingStorage';
import { clearFirstContextContinuationSelections } from '@/domain/chat/first-context';
import { clearAllComposerMruCaches } from '@/lib/mruCache';
import { clearConversationReadCursors } from '@/stores/conversation-read-cursors';
import { clearDesktopNotificationContentState } from '@/runtime/desktop-notifications';
import { clearPrivateResourceAccessCache } from '@/api/modules/privateResources';
import {
  CHAT_RETRYABLE_SEND_STORAGE_KEY,
  INLINE_SKILL_RETRY_STORAGE_KEY,
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

export const clearAllPersistedChatRetries = (): boolean => {
  invalidateAllChatRetries();
  invalidateAllChatHistory();
  saveRetryableChatSends(new Map());
  saveRetryableInlineSkillOperations(new Map());
  if (typeof window === 'undefined') {
    return true;
  }
  try {
    return window.sessionStorage.getItem(CHAT_RETRYABLE_SEND_STORAGE_KEY) === null
      && window.sessionStorage.getItem(INLINE_SKILL_RETRY_STORAGE_KEY) === null;
  } catch {
    return false;
  }
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

export interface CompleteMemoryClearResult {
  browserStateCleared: boolean;
  failedScopes: string[];
}

export interface CompleteMemoryClearOptions {
  clearBoundaryAtSeconds?: number;
}

export const completeMemoryClear = (
  options: CompleteMemoryClearOptions = {},
): CompleteMemoryClearResult => {
  const failedScopes: string[] = [];
  const runCleanup = (scope: string, cleanup: () => boolean): void => {
    try {
      if (!cleanup()) {
        failedScopes.push(scope);
      }
    } catch {
      failedScopes.push(scope);
    }
  };

  runCleanup('private_resources', clearPrivateResourceAccessCache);
  runCleanup('onboarding', clearOnboardingContentState);
  runCleanup('first_context', clearFirstContextContinuationSelections);
  runCleanup('composer_mru', clearAllComposerMruCaches);
  runCleanup('read_cursors', clearConversationReadCursors);
  runCleanup('notification_dedupe', clearDesktopNotificationContentState);
  runCleanup('chat_retries', clearAllPersistedChatRetries);
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
  useBackgroundTaskStore.getState().retireForMemoryClear(
    options.clearBoundaryAtSeconds ?? Date.now() / 1000,
  );
  useChatShellStore.getState().resetContentState();
  const notifications = useNotificationStore.getState();
  notifications.clearForMemoryClear();
  runCleanup('active_chat_session', () => {
    window.localStorage.removeItem(CHAT_SESSION_KEY(DEFAULT_USER_ID));
    return window.localStorage.getItem(CHAT_SESSION_KEY(DEFAULT_USER_ID)) === null;
  });
  dispatchAppEvent.memoryCleared();
  return {
    browserStateCleared: failedScopes.length === 0,
    failedScopes,
  };
};
