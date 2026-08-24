import { useCallback, useRef } from 'react';
import { toast } from 'sonner';

import { commandsApi, type SkillCommandDescriptor } from '@/api';
import { DEFAULT_USER_ID } from '@/constants';
import { APP_EVENTS } from '@/constants/events';
import { parseSkillArguments } from '@/domain/chat/skill-arguments';
import { createClientTurnId } from '@/domain/chat/state';
import type { PendingResponseTurnIdentity } from '@/domain/chat/turn-completion';
import { useConversationStore } from '@/stores/conversation-store';
import { isChatTurnConfirmedTerminal, sendChatMessageReliably } from './chatSendReliability';
import {
  deleteRetryableInlineSkillOperationsForSession,
  deleteRetryableInlineSkillOperationsForTurn,
  isRetryableInlineSkillFresh,
  loadRetryableInlineSkillOperations,
  MAX_RETRYABLE_SENDS,
  saveRetryableInlineSkillOperations,
  type RetryableInlineSkillOperation,
} from './chatRetryableSendStorage';
import type {
  ExistingTurnAdmissionCheck,
  RunWithChatTurnAdmission,
} from './chatTurnAdmission';
import {
  areChatRetryGuardsCurrent,
  captureChatRetryGuard,
  invalidateAllChatRetries,
  invalidateChatRetrySession,
  invalidateChatRetryTurn,
  type ChatRetryGuard,
} from './chatRetryInvalidation';
import type { PendingTurnPayload } from './useChatSendMessage';

type InlineSkillReconciliation =
  | {
    kind: 'accepted';
    terminal: boolean;
  }
  | {
    kind: 'rejected';
  }
  | {
    kind: 'unconfirmed';
  }
  | {
    kind: 'invalidated';
  };

export type SkillExpansionOutcome =
  | {
    kind: 'accepted';
  }
  | {
    kind: 'not_sent';
    message: string;
  };

type UseChatInlineSkillSendOptions = {
  currentSessionId: string | null;
  workspacePath: string | null | undefined;
  allowInterjection: boolean;
  hasPendingAsk: boolean;
  appendPendingTurn: (payload: PendingTurnPayload) => void;
  removeMessage: (sessionId: string, messageId: string) => void;
  trackPendingResponseTurn: (sessionId: string, turnId: string) => void;
  clearPendingResponseTurn: (
    expected?: Partial<PendingResponseTurnIdentity>,
  ) => void;
  reconcilePendingSendBeforeExternalTurn: (
    sessionId: string,
  ) => Promise<boolean>;
  runWithTurnAdmission: RunWithChatTurnAdmission;
  translate: (key: string, options?: Record<string, unknown>) => string;
};

export function useChatInlineSkillSend({
  currentSessionId,
  workspacePath,
  allowInterjection,
  hasPendingAsk,
  appendPendingTurn,
  removeMessage,
  trackPendingResponseTurn,
  clearPendingResponseTurn,
  reconcilePendingSendBeforeExternalTurn,
  runWithTurnAdmission,
  translate,
}: UseChatInlineSkillSendOptions) {
  const hasPendingAskRef = useRef(hasPendingAsk);
  hasPendingAskRef.current = hasPendingAsk;
  const operationsRef = useRef(new Map<string, RetryableInlineSkillOperation>());
  const restoredTurnIdsRef = useRef(new Set<string>());
  const restoredRef = useRef(false);
  if (!restoredRef.current) {
    operationsRef.current = loadRetryableInlineSkillOperations();
    restoredTurnIdsRef.current = new Set(
      [...operationsRef.current.values()].map(
        (operation) => operation.confirmation.turnId,
      ),
    );
    restoredRef.current = true;
  }

  const clearRetryForTurn = useCallback((
    sessionId: string,
    turnId: string,
  ) => {
    invalidateChatRetryTurn(sessionId, turnId);
    const removed = deleteRetryableInlineSkillOperationsForTurn(
      operationsRef.current,
      sessionId,
      turnId,
    );
    if (removed.length === 0) {
      return;
    }
    restoredTurnIdsRef.current.delete(String(turnId || '').trim());
    saveRetryableInlineSkillOperations(operationsRef.current);
  }, []);

  const clearRetriesForSession = useCallback((sessionId: string) => {
    invalidateChatRetrySession(sessionId);
    const removed = deleteRetryableInlineSkillOperationsForSession(
      operationsRef.current,
      sessionId,
    );
    if (removed.length === 0) {
      return;
    }
    for (const operation of removed) {
      restoredTurnIdsRef.current.delete(operation.confirmation.turnId);
    }
    saveRetryableInlineSkillOperations(operationsRef.current);
  }, []);

  const clearAllRetries = useCallback(() => {
    invalidateAllChatRetries();
    operationsRef.current.clear();
    restoredTurnIdsRef.current.clear();
    saveRetryableInlineSkillOperations(operationsRef.current);
  }, []);

  const reconcileOperation = useCallback(async (
    operation: RetryableInlineSkillOperation,
    sessionStartGuard?: ChatRetryGuard,
  ): Promise<InlineSkillReconciliation> => {
    const sessionId = String(operation.request.session_id || '').trim();
    const turnId = String(operation.confirmation.turnId || '').trim();
    const sessionGuard = sessionStartGuard
      ?? captureChatRetryGuard(sessionId);
    const turnGuard = captureChatRetryGuard(sessionId, turnId);
    const operationIsCurrent = () => areChatRetryGuardsCurrent(
      sessionGuard,
      turnGuard,
    );
    if (!operationIsCurrent()) {
      return { kind: 'invalidated' };
    }
    let outcome;
    try {
      outcome = await sendChatMessageReliably({
        request: operation.request,
        confirmation: operation.confirmation,
        fallbackMessage: translate('chat.sendFailed'),
        preflight: true,
      });
    } catch {
      return operationIsCurrent()
        ? { kind: 'unconfirmed' }
        : { kind: 'invalidated' };
    }
    if (!operationIsCurrent()) {
      return { kind: 'invalidated' };
    }
    if (outcome.kind !== 'accepted') {
      return {
        kind: outcome.kind === 'concluded' ? 'rejected' : outcome.kind,
      };
    }
    const terminal = (
      allowInterjection
      || (
        Boolean(sessionId && turnId)
        && await isChatTurnConfirmedTerminal(sessionId, turnId)
      )
    );
    if (!operationIsCurrent()) {
      return { kind: 'invalidated' };
    }
    return {
      kind: 'accepted',
      terminal,
    };
  }, [allowInterjection, translate]);

  const reconcileBeforeComposerTurn = useCallback(async (
    sessionId: string,
    excludedRetryKey?: string,
  ): Promise<ExistingTurnAdmissionCheck> => {
    const normalizedSessionId = String(sessionId || '').trim();
    if (!normalizedSessionId) {
      return { kind: 'unconfirmed' };
    }
    const operations = [...operationsRef.current.values()]
      .filter((operation) => (
        String(operation.request.session_id || '').trim()
          === normalizedSessionId
        && operation.retryKey !== excludedRetryKey
      ))
      .sort((left, right) => left.createdAtMs - right.createdAtMs);
    let storageChanged = false;
    let resolvedRestoredOperation = false;
    const persistChanges = () => {
      if (storageChanged) {
        saveRetryableInlineSkillOperations(operationsRef.current);
      }
    };

    for (const operation of operations) {
      const turnId = String(operation.confirmation.turnId || '').trim();
      if (!isRetryableInlineSkillFresh(operation, Date.now())) {
        operationsRef.current.delete(operation.retryKey);
        restoredTurnIdsRef.current.delete(turnId);
        storageChanged = true;
        continue;
      }

      const outcome = await reconcileOperation(operation);
      if (outcome.kind === 'invalidated') {
        persistChanges();
        return { kind: 'ready' };
      }
      if (outcome.kind === 'unconfirmed') {
        persistChanges();
        return { kind: 'unconfirmed' };
      }

      operationsRef.current.delete(operation.retryKey);
      storageChanged = true;
      const wasRestored = restoredTurnIdsRef.current.delete(turnId);
      if (outcome.kind === 'accepted') {
        window.dispatchEvent(new Event(APP_EVENTS.SESSION_SYNC));
        if (!outcome.terminal) {
          persistChanges();
          return {
            kind: 'pending',
            sessionId: normalizedSessionId,
            turnId,
            input: operation.request.message,
            timestamp: operation.createdAtMs,
          };
        }
      }
      resolvedRestoredOperation ||= wasRestored;
    }

    persistChanges();
    return {
      kind: 'ready',
      stopCurrentIntent: resolvedRestoredOperation,
    };
  }, [reconcileOperation]);

  const stagePendingTurn = useCallback(({
    sessionId,
    turnId,
    input,
    timestamp,
  }: {
    sessionId: string;
    turnId: string;
    input: string;
    timestamp: number;
  }) => {
    const normalizedSessionId = String(sessionId || '').trim();
    const normalizedTurnId = String(turnId || '').trim();
    if (!normalizedSessionId || !normalizedTurnId) {
      return;
    }
    const alreadyVisible = (
      useConversationStore.getState().messagesBySession[normalizedSessionId] || []
    ).some((message) => (
      message.role === 'user'
      && String(message.turnId || '').trim() === normalizedTurnId
    ));
    if (!alreadyVisible) {
      appendPendingTurn({
        sessionId: normalizedSessionId,
        input,
        turnId: normalizedTurnId,
        timestamp,
        pendingLabel: translate('chat.trace.pending'),
      });
    }
    if (!allowInterjection) {
      trackPendingResponseTurn(normalizedSessionId, normalizedTurnId);
    }
  }, [allowInterjection, appendPendingTurn, trackPendingResponseTurn, translate]);

  const stageOperation = useCallback((operation: RetryableInlineSkillOperation) => {
    stagePendingTurn({
      sessionId: String(operation.request.session_id || ''),
      turnId: operation.confirmation.turnId,
      input: operation.request.message,
      timestamp: operation.createdAtMs,
    });
  }, [stagePendingTurn]);

  const clearPendingState = useCallback((operation: RetryableInlineSkillOperation) => {
    const sessionId = String(operation.request.session_id || '').trim();
    const turnId = String(operation.confirmation.turnId || '').trim();
    if (!sessionId || !turnId) {
      return;
    }
    removeMessage(sessionId, `${turnId}-user`);
    clearPendingResponseTurn({ sessionId, turnId });
  }, [clearPendingResponseTurn, removeMessage]);

  const runSkillExpansion = useCallback(async (
    descriptor: SkillCommandDescriptor,
    argsText: string,
  ): Promise<SkillExpansionOutcome> => {
    if (!currentSessionId) {
      throw new Error(translate('chat.sessionRequired'));
    }
    const notSent = (message: string): SkillExpansionOutcome => ({
      kind: 'not_sent',
      message,
    });
    const accepted = (): SkillExpansionOutcome => ({ kind: 'accepted' });
    const originSessionId = currentSessionId;
    const sessionStartGuard = captureChatRetryGuard(originSessionId);
    const resolvedWorkspacePath = workspacePath ?? null;
    const parsedArguments = parseSkillArguments(
      argsText,
      descriptor.argument_hint,
    );
    if (!parsedArguments.ok) {
      return notSent(translate('chat.skills.argumentsInvalid'));
    }
    const args = parsedArguments.arguments;

    if (descriptor.context_mode === 'fork') {
      const admission = await runWithTurnAdmission(
        originSessionId,
        'background_skill',
        async () => {
          if (!areChatRetryGuardsCurrent(sessionStartGuard)) {
            return notSent(translate('chat.skills.notSent'));
          }
          const result = await commandsApi.runSkillAsBackground({
            user_id: DEFAULT_USER_ID,
            session_id: originSessionId,
            skill_name: descriptor.name,
            arguments: args,
            workspace_path: resolvedWorkspacePath,
          });
          if (!areChatRetryGuardsCurrent(sessionStartGuard)) {
            return notSent(translate('chat.skills.notSent'));
          }
          toast.success(translate('chat.skills.backgroundQueued', {
            defaultValue: 'Started {{title}} in the background.',
            title: result.title,
          }));
          return accepted();
        },
      );
      if (admission.entered) {
        return admission.value;
      }
      if (admission.reason === 'history_unavailable') {
        return notSent(translate('chat.historyNotReady'));
      }
      if (admission.reason === 'exclusive_action') {
        return notSent(translate('chat.clearHistoryDialog.inProgress'));
      }
      if (admission.reason === 'invalid_session') {
        return notSent(translate('chat.sessionRequired'));
      }
      return notSent(translate('chat.skills.notSent'));
    }

    if (hasPendingAskRef.current) {
      return notSent(translate('chat.skills.pendingAskBlocked'));
    }

    const retryKey = JSON.stringify([
      originSessionId,
      resolvedWorkspacePath,
      descriptor.name,
      args,
    ]);
    const admission = await runWithTurnAdmission(
      originSessionId,
      'inline_skill',
      async () => {
        if (hasPendingAskRef.current) {
          return notSent(translate('chat.skills.pendingAskBlocked'));
        }
        if (!areChatRetryGuardsCurrent(sessionStartGuard)) {
          return notSent(translate('chat.skills.notSent'));
        }
        if (!await reconcilePendingSendBeforeExternalTurn(originSessionId)) {
          return notSent(translate('chat.previousSendUnconfirmed'));
        }
        if (!areChatRetryGuardsCurrent(sessionStartGuard)) {
          return notSent(translate('chat.skills.notSent'));
        }
        if (hasPendingAskRef.current) {
          return notSent(translate('chat.skills.pendingAskBlocked'));
        }

        const otherInlineAdmission = await reconcileBeforeComposerTurn(
          originSessionId,
          retryKey,
        );
        if (!areChatRetryGuardsCurrent(sessionStartGuard)) {
          return notSent(translate('chat.skills.notSent'));
        }
        if (hasPendingAskRef.current) {
          return notSent(translate('chat.skills.pendingAskBlocked'));
        }
        if (otherInlineAdmission.kind === 'unconfirmed') {
          return notSent(translate('chat.previousSendUnconfirmed'));
        }
        if (otherInlineAdmission.kind === 'pending') {
          stagePendingTurn(otherInlineAdmission);
          window.dispatchEvent(new Event(APP_EVENTS.SESSION_SYNC));
          return notSent(translate('chat.waitForCurrentReply'));
        }
        if (otherInlineAdmission.stopCurrentIntent) {
          return notSent(translate('chat.restoredSendResolved'));
        }

        let previousOperation = operationsRef.current.get(retryKey);
        if (
          previousOperation
          && !isRetryableInlineSkillFresh(previousOperation, Date.now())
        ) {
          operationsRef.current.delete(retryKey);
          restoredTurnIdsRef.current.delete(
            previousOperation.confirmation.turnId,
          );
          saveRetryableInlineSkillOperations(operationsRef.current);
          previousOperation = undefined;
        }
        if (previousOperation) {
          stageOperation(previousOperation);
          const previousOutcome = await reconcileOperation(
            previousOperation,
            sessionStartGuard,
          );
          if (previousOutcome.kind === 'invalidated') {
            return notSent(translate('chat.skills.notSent'));
          }
          if (previousOutcome.kind === 'accepted') {
            operationsRef.current.delete(retryKey);
            restoredTurnIdsRef.current.delete(
              previousOperation.confirmation.turnId,
            );
            saveRetryableInlineSkillOperations(operationsRef.current);
            if (previousOutcome.terminal) {
              clearPendingState(previousOperation);
            }
            window.dispatchEvent(new Event(APP_EVENTS.SESSION_SYNC));
            return accepted();
          }
          clearPendingState(previousOperation);
          if (previousOutcome.kind === 'unconfirmed') {
            saveRetryableInlineSkillOperations(operationsRef.current);
            return notSent(translate('chat.skills.sendUnconfirmed'));
          }
          operationsRef.current.delete(retryKey);
          const wasRestored = restoredTurnIdsRef.current.delete(
            previousOperation.confirmation.turnId,
          );
          saveRetryableInlineSkillOperations(operationsRef.current);
          if (wasRestored) {
            return notSent(translate('chat.restoredSendResolved'));
          }
        }

        const invocationText = `/${descriptor.name}${
          args.length > 0 ? ` ${args.join(' ')}` : ''
        }`;
        const turnId = createClientTurnId();
        const operation: RetryableInlineSkillOperation = {
          retryKey,
          createdAtMs: Date.now(),
          request: {
            user_id: DEFAULT_USER_ID,
            session_id: originSessionId,
            message: invocationText,
            workspace_path: resolvedWorkspacePath,
            client_turn_id: turnId,
            skill_invocation: {
              name: descriptor.name,
              arguments: args,
            },
          },
          confirmation: {
            kind: 'turn',
            sessionId: originSessionId,
            turnId,
          },
        };
        const turnGuard = captureChatRetryGuard(originSessionId, turnId);
        const operationIsCurrent = () => areChatRetryGuardsCurrent(
          sessionStartGuard,
          turnGuard,
        );
        operationsRef.current.set(retryKey, operation);
        while (operationsRef.current.size > MAX_RETRYABLE_SENDS) {
          const oldestKey = operationsRef.current.keys().next().value;
          if (typeof oldestKey !== 'string') {
            break;
          }
          operationsRef.current.delete(oldestKey);
        }
        saveRetryableInlineSkillOperations(operationsRef.current);
        stageOperation(operation);
        if (!operationIsCurrent()) {
          return notSent(translate('chat.skills.notSent'));
        }
        let outcome;
        try {
          outcome = await sendChatMessageReliably({
            request: operation.request,
            confirmation: operation.confirmation,
            fallbackMessage: translate('chat.sendFailed'),
          });
        } catch (error) {
          if (operationIsCurrent()) {
            clearPendingState(operation);
          }
          throw error;
        }
        if (!operationIsCurrent()) {
          return notSent(translate('chat.skills.notSent'));
        }
        if (outcome.kind === 'accepted') {
          operationsRef.current.delete(retryKey);
          saveRetryableInlineSkillOperations(operationsRef.current);
          window.dispatchEvent(new Event(APP_EVENTS.SESSION_SYNC));
          return accepted();
        }
        clearPendingState(operation);
        if (outcome.kind === 'rejected' || outcome.kind === 'concluded') {
          operationsRef.current.delete(retryKey);
          saveRetryableInlineSkillOperations(operationsRef.current);
          throw new Error(
            outcome.kind === 'rejected'
              ? outcome.message
              : translate('chat.sendFailed'),
          );
        }
        return notSent(translate('chat.skills.sendUnconfirmed'));
      },
    );
    if (admission.entered) {
      return admission.value;
    }
    if (admission.reason === 'pending_turn') {
      return notSent(translate('chat.waitForCurrentReply'));
    }
    if (admission.reason === 'history_unavailable') {
      return notSent(translate('chat.historyNotReady'));
    }
    if (admission.reason === 'exclusive_action') {
      return notSent(translate('chat.clearHistoryDialog.inProgress'));
    }
    if (admission.reason === 'invalid_session') {
      return notSent(translate('chat.sessionRequired'));
    }
    return notSent(translate('chat.skills.notSent'));
  }, [
    clearPendingState,
    currentSessionId,
    reconcileBeforeComposerTurn,
    reconcileOperation,
    reconcilePendingSendBeforeExternalTurn,
    runWithTurnAdmission,
    stageOperation,
    stagePendingTurn,
    translate,
    workspacePath,
  ]);

  return {
    clearAllRetries,
    clearRetryForTurn,
    clearRetriesForSession,
    reconcileBeforeComposerTurn,
    runSkillExpansion,
  };
}
