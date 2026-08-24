import { useCallback, useRef, useState } from 'react';
import { toast } from 'sonner';
import { messagesApi } from '@/api';
import type { ChatAttachment } from '@/api';
import { DEFAULT_USER_ID } from '@/constants';
import { APP_EVENTS } from '@/constants/events';
import {
  createClientTurnId,
  type ChatTimelineReplyPreview,
} from '@/domain/chat/state';
import type { FirstContextQuestionContext } from '@/domain/chat/first-context';
import {
  toRecallFeedbackReplyPreview,
  toRecallFeedbackRequest,
  type RecallFeedbackDraft,
} from '@/domain/chat/recall-feedback';
import { useConversationStore } from '@/stores';
import {
  isChatTurnConfirmedTerminal,
  sendChatMessageReliably,
} from './chatSendReliability';
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
import {
  deleteRetryableChatSendForTurn,
  deleteRetryableChatSendsForSession,
  isRetryableChatSendFresh,
  loadRetryableChatSends,
  MAX_RETRYABLE_SENDS,
  saveRetryableChatSends,
  type RetryableAskAnswer,
  type RetryableAskSendContext,
  type RetryableChatSendOperation,
  type RetryablePendingTurn,
  type RetryableSendDraftKind,
} from './chatRetryableSendStorage';
import type { ComposerDraftItem } from './useChatDraftAttachments';
import type { ReasoningPreference } from '@/components/chat/ComposerReasoningControl';
import { isFileDraftAttachment, isMcpDraftAttachment } from './useChatDraftAttachments';

const USER_ID = DEFAULT_USER_ID;

export type ComposerSendDraftKind = RetryableSendDraftKind;

export type PendingTurnPayload = RetryablePendingTurn;

export type PendingAskSendContext = RetryableAskSendContext;

export type PendingAskAnswerPayload = RetryableAskAnswer;

export type UseChatSendMessageOptions = {
  currentSessionId: string | null;
  currentWorkspacePath: string | null | undefined;
  inputValue: string;
  draftAttachments: ComposerDraftItem[];
  replyTarget: ChatTimelineReplyPreview | null;
  allowInterjection: boolean;
  pendingAsk: PendingAskSendContext | null;
  firstContextQuestion?: FirstContextQuestionContext | null;
  recallFeedbackDraft: RecallFeedbackDraft | null;
  reasoningPreference: ReasoningPreference;
  appendPendingTurn: (payload: PendingTurnPayload) => void;
  removePendingMessage: (sessionId: string, messageId: string) => void;
  setCurrentSessionId: (sessionId: string | null) => void;
  getCurrentSessionId: () => string | null;
  composerDraftIdentity: string;
  composerDraftSignature: string;
  clearComposerDraftIfUnchanged: (
    expectedIdentity: string,
    kind: ComposerSendDraftKind,
  ) => void;
  onPendingResponseTurn: (sessionId: string, turnId: string) => void;
  onPendingResponseFailure: (sessionId: string, turnId: string) => void;
  onAskAnswered: (answer: PendingAskAnswerPayload) => void;
  reconcileExternalTurnBeforeSend: (
    sessionId: string,
  ) => Promise<ExistingTurnAdmissionCheck>;
  runWithTurnAdmission: RunWithChatTurnAdmission;
  translate: (key: string, options?: Record<string, unknown>) => string;
};

const mcpResourceToChatAttachment = (
  item: Extract<ComposerDraftItem, { kind: 'mcp_resource' }>,
): ChatAttachment => ({
  attachment_id: item.id,
  kind: 'mcp_resource',
  original_name: item.name || item.uri,
  mime_type: item.mimeType,
  server_id: item.serverId,
  uri: item.uri,
});

type RetryableSendOperation = RetryableChatSendOperation;

const trimRetryableSends = (
  operations: Map<string, RetryableSendOperation>,
) => {
  while (operations.size > MAX_RETRYABLE_SENDS) {
    const oldestKey = operations.keys().next().value;
    if (typeof oldestKey !== 'string') {
      break;
    }
    operations.delete(oldestKey);
  }
};

export function useChatSendMessage({
  currentSessionId,
  currentWorkspacePath,
  inputValue,
  draftAttachments,
  replyTarget,
  allowInterjection,
  pendingAsk,
  firstContextQuestion = null,
  recallFeedbackDraft,
  reasoningPreference,
  appendPendingTurn,
  removePendingMessage,
  setCurrentSessionId,
  getCurrentSessionId,
  composerDraftIdentity,
  composerDraftSignature,
  clearComposerDraftIfUnchanged,
  onPendingResponseTurn,
  onPendingResponseFailure,
  onAskAnswered,
  reconcileExternalTurnBeforeSend,
  runWithTurnAdmission,
  translate,
}: UseChatSendMessageOptions) {
  const [sendingSessionIds, setSendingSessionIds] = useState<Set<string>>(
    () => new Set(),
  );
  const setSessionSending = useCallback((
    sessionId: string,
    sending: boolean,
  ) => {
    const normalizedSessionId = String(sessionId || '').trim();
    if (!normalizedSessionId) {
      return;
    }
    setSendingSessionIds((current) => {
      const hasSession = current.has(normalizedSessionId);
      if (hasSession === sending) {
        return current;
      }
      const next = new Set(current);
      if (sending) {
        next.add(normalizedSessionId);
      } else {
        next.delete(normalizedSessionId);
      }
      return next;
    });
  }, []);
  const normalizedCurrentSessionId = String(currentSessionId || '').trim();
  const sendingMessage = (
    Boolean(normalizedCurrentSessionId)
    && sendingSessionIds.has(normalizedCurrentSessionId)
  );
  const retryableSendsRef = useRef(new Map<string, RetryableSendOperation>());
  const restoredRetryableTurnIdsRef = useRef(new Set<string>());
  const retryableSendsRestoredRef = useRef(false);
  if (!retryableSendsRestoredRef.current) {
    retryableSendsRef.current = loadRetryableChatSends();
    restoredRetryableTurnIdsRef.current = new Set(
      [...retryableSendsRef.current.values()].map(
        (operation) => operation.turnId,
      ),
    );
    retryableSendsRestoredRef.current = true;
  }

  const uploadDraftAttachments = useCallback(async (
    sessionId: string,
    turnId: string,
    drafts: ComposerDraftItem[],
  ): Promise<ChatAttachment[]> => {
    if (!drafts.length) {
      return [];
    }

    const fileDrafts = drafts.filter(isFileDraftAttachment);
    const mcpDrafts = drafts.filter(isMcpDraftAttachment);

    const uploaded = fileDrafts.length === 0
      ? []
      : await Promise.all(
        fileDrafts.map((draft) =>
          messagesApi.uploadAttachment(USER_ID, sessionId, turnId, draft.file),
        ),
      );

    return [...uploaded, ...mcpDrafts.map(mcpResourceToChatAttachment)];
  }, []);

  const clearRetryableSendForTurn = useCallback((
    sessionId: string,
    turnId: string,
  ) => {
    const normalizedSessionId = String(sessionId || '').trim();
    const normalizedTurnId = String(turnId || '').trim();
    if (!normalizedSessionId || !normalizedTurnId) {
      return;
    }
    invalidateChatRetryTurn(normalizedSessionId, normalizedTurnId);
    const operation = deleteRetryableChatSendForTurn(
      retryableSendsRef.current,
      normalizedSessionId,
      normalizedTurnId,
    );
    if (!operation) {
      return;
    }
    restoredRetryableTurnIdsRef.current.delete(normalizedTurnId);
    saveRetryableChatSends(retryableSendsRef.current);
    onPendingResponseFailure(normalizedSessionId, normalizedTurnId);
  }, [onPendingResponseFailure]);

  const clearRetryableSendsForSession = useCallback((sessionId: string) => {
    const normalizedSessionId = String(sessionId || '').trim();
    if (!normalizedSessionId) {
      return;
    }
    invalidateChatRetrySession(normalizedSessionId);
    const operation = deleteRetryableChatSendsForSession(
      retryableSendsRef.current,
      normalizedSessionId,
    );
    if (!operation) {
      return;
    }
    restoredRetryableTurnIdsRef.current.delete(operation.turnId);
    saveRetryableChatSends(retryableSendsRef.current);
    onPendingResponseFailure(normalizedSessionId, operation.turnId);
  }, [onPendingResponseFailure]);

  const clearAllRetryableSends = useCallback(() => {
    invalidateAllChatRetries();
    const operations = [...retryableSendsRef.current.values()];
    retryableSendsRef.current.clear();
    restoredRetryableTurnIdsRef.current.clear();
    saveRetryableChatSends(retryableSendsRef.current);
    for (const operation of operations) {
      onPendingResponseFailure(operation.sessionId, operation.turnId);
    }
  }, [onPendingResponseFailure]);

  const submitOperation = useCallback(async (
    operation: RetryableSendOperation,
    retrying: boolean,
    sessionStartGuard?: ChatRetryGuard,
  ) => {
    const sessionGuard = sessionStartGuard
      ?? captureChatRetryGuard(operation.sessionId);
    if (!areChatRetryGuardsCurrent(sessionGuard)) {
      return;
    }
    const turnGuard = captureChatRetryGuard(
      operation.sessionId,
      operation.turnId,
    );
    const operationIsCurrent = () => areChatRetryGuardsCurrent(
      sessionGuard,
      turnGuard,
    );
    const isOriginSessionCurrent = () => (
      getCurrentSessionId() === operation.sessionId
    );
    const selectResponseSessionIfStillCurrent = (sessionId: unknown) => {
      const normalizedSessionId = String(sessionId || '').trim();
      if (normalizedSessionId && isOriginSessionCurrent()) {
        setCurrentSessionId(normalizedSessionId);
      }
    };
    const ensureOptimisticTurn = () => {
      if (!operation.pendingTurn) {
        return;
      }
      const alreadyVisible = (
        useConversationStore.getState().messagesBySession[operation.sessionId] || []
      ).some((message) => (
        message.role === 'user'
        && String(message.turnId || '').trim() === operation.turnId
      ));
      if (!alreadyVisible) {
        appendPendingTurn(operation.pendingTurn);
      }
    };
    const markAccepted = (responseSessionId?: unknown) => {
      if (
        retryableSendsRef.current.get(operation.sessionId)?.turnId
        === operation.turnId
      ) {
        retryableSendsRef.current.delete(operation.sessionId);
        restoredRetryableTurnIdsRef.current.delete(operation.turnId);
        saveRetryableChatSends(retryableSendsRef.current);
      }
      selectResponseSessionIfStillCurrent(responseSessionId);
      if (isOriginSessionCurrent()) {
        clearComposerDraftIfUnchanged(
          operation.draftIdentity,
          operation.draftKind,
        );
      }
      if (operation.askAnswer) {
        onAskAnswered(operation.askAnswer);
      }
      window.dispatchEvent(new Event(APP_EVENTS.SESSION_SYNC));
    };
    const markRejected = (message: string) => {
      if (
        retryableSendsRef.current.get(operation.sessionId)?.turnId
        === operation.turnId
      ) {
        retryableSendsRef.current.delete(operation.sessionId);
        restoredRetryableTurnIdsRef.current.delete(operation.turnId);
        saveRetryableChatSends(retryableSendsRef.current);
      }
      onPendingResponseFailure(operation.sessionId, operation.turnId);
      if (operation.pendingTurn) {
        removePendingMessage(
          operation.sessionId,
          `${operation.turnId}-user`,
        );
      }
      toast.error(message);
    };
    const markUnconfirmed = () => {
      retryableSendsRef.current.set(operation.sessionId, operation);
      trimRetryableSends(retryableSendsRef.current);
      saveRetryableChatSends(retryableSendsRef.current);
      onPendingResponseFailure(operation.sessionId, operation.turnId);
      if (operation.pendingTurn) {
        removePendingMessage(
          operation.sessionId,
          `${operation.turnId}-user`,
        );
      }
      toast.warning(translate('chat.sendUnconfirmed'));
    };
    const markConcluded = () => {
      if (
        retryableSendsRef.current.get(operation.sessionId)?.turnId
        === operation.turnId
      ) {
        retryableSendsRef.current.delete(operation.sessionId);
        restoredRetryableTurnIdsRef.current.delete(operation.turnId);
        saveRetryableChatSends(retryableSendsRef.current);
      }
      onPendingResponseFailure(operation.sessionId, operation.turnId);
      if (operation.pendingTurn) {
        removePendingMessage(
          operation.sessionId,
          `${operation.turnId}-user`,
        );
      }
      toast.warning(translate('chat.askNoLongerPending'));
      window.dispatchEvent(new Event(APP_EVENTS.SESSION_SYNC));
    };

    if (!allowInterjection && operation.draftKind !== 'pending_ask') {
      onPendingResponseTurn(operation.sessionId, operation.turnId);
    }

    retryableSendsRef.current.set(operation.sessionId, operation);
    trimRetryableSends(retryableSendsRef.current);
    saveRetryableChatSends(retryableSendsRef.current);
    ensureOptimisticTurn();
    if (!operationIsCurrent()) {
      return;
    }
    const outcome = await sendChatMessageReliably({
      request: operation.request,
      confirmation: operation.confirmation,
      fallbackMessage: translate('chat.sendFailed'),
      preflight: retrying,
    });

    if (!operationIsCurrent()) {
      return;
    }

    if (outcome.kind === 'accepted') {
      markAccepted(outcome.responseSessionId);
      return;
    }
    if (outcome.kind === 'rejected') {
      markRejected(outcome.message);
      return;
    }
    if (outcome.kind === 'concluded') {
      markConcluded();
      return;
    }
    if (outcome.kind === 'unconfirmed') {
      markUnconfirmed();
    }
  }, [
    allowInterjection,
    appendPendingTurn,
    clearComposerDraftIfUnchanged,
    getCurrentSessionId,
    onAskAnswered,
    onPendingResponseFailure,
    onPendingResponseTurn,
    removePendingMessage,
    setCurrentSessionId,
    translate,
  ]);

  const reconcileChangedDraftOperation = useCallback(async (
    operation: RetryableSendOperation,
    allowAcceptedPendingTurn = false,
  ): Promise<boolean> => {
    const operationGuard = captureChatRetryGuard(
      operation.sessionId,
      operation.turnId,
    );
    let outcome;
    try {
      outcome = await sendChatMessageReliably({
        request: operation.request,
        confirmation: operation.confirmation,
        fallbackMessage: translate('chat.sendFailed'),
        preflight: true,
      });
    } catch {
      if (!areChatRetryGuardsCurrent(operationGuard)) {
        return false;
      }
      toast.warning(translate('chat.previousSendUnconfirmed'));
      return false;
    }
    if (!areChatRetryGuardsCurrent(operationGuard)) {
      return false;
    }
    if (outcome.kind === 'unconfirmed') {
      toast.warning(translate('chat.previousSendUnconfirmed'));
      return false;
    }

    if (
      retryableSendsRef.current.get(operation.sessionId)?.turnId
      === operation.turnId
    ) {
      retryableSendsRef.current.delete(operation.sessionId);
      saveRetryableChatSends(retryableSendsRef.current);
    }
    const wasRestored = restoredRetryableTurnIdsRef.current.delete(
      operation.turnId,
    );
    if (operation.pendingTurn) {
      removePendingMessage(
        operation.sessionId,
        `${operation.turnId}-user`,
      );
    }
    if (outcome.kind === 'accepted') {
      if (operation.askAnswer) {
        onPendingResponseFailure(operation.sessionId, operation.turnId);
        onAskAnswered(operation.askAnswer);
        window.dispatchEvent(new Event(APP_EVENTS.SESSION_SYNC));
        if (wasRestored) {
          toast.warning(translate('chat.restoredSendResolved'));
        }
        return false;
      }
      const terminal = allowInterjection || await isChatTurnConfirmedTerminal(
        operation.sessionId,
        operation.turnId,
      );
      if (!areChatRetryGuardsCurrent(operationGuard)) {
        return false;
      }
      if (!terminal) {
        onPendingResponseTurn(operation.sessionId, operation.turnId);
        window.dispatchEvent(new Event(APP_EVENTS.SESSION_SYNC));
        if (wasRestored) {
          toast.warning(translate('chat.restoredSendResolved'));
        }
        return allowAcceptedPendingTurn;
      }
      onPendingResponseFailure(operation.sessionId, operation.turnId);
      window.dispatchEvent(new Event(APP_EVENTS.SESSION_SYNC));
      if (wasRestored) {
        toast.warning(translate('chat.restoredSendResolved'));
        return false;
      }
      return true;
    }
    if (outcome.kind === 'concluded') {
      onPendingResponseFailure(operation.sessionId, operation.turnId);
      window.dispatchEvent(new Event(APP_EVENTS.SESSION_SYNC));
      return true;
    }
    onPendingResponseFailure(operation.sessionId, operation.turnId);
    if (wasRestored) {
      toast.warning(translate('chat.restoredSendResolved'));
      return false;
    }
    return true;
  }, [
    allowInterjection,
    onAskAnswered,
    onPendingResponseFailure,
    onPendingResponseTurn,
    removePendingMessage,
    translate,
  ]);

  const reconcilePendingSendBeforeExternalTurn = useCallback(async (
    sessionId: string,
  ): Promise<boolean> => {
    const normalizedSessionId = String(sessionId || '').trim();
    if (!normalizedSessionId) {
      return false;
    }
    const operation = retryableSendsRef.current.get(normalizedSessionId);
    if (!operation) {
      return true;
    }
    if (!isRetryableChatSendFresh(operation, Date.now())) {
      retryableSendsRef.current.delete(normalizedSessionId);
      restoredRetryableTurnIdsRef.current.delete(operation.turnId);
      saveRetryableChatSends(retryableSendsRef.current);
      return true;
    }
    return reconcileChangedDraftOperation(operation);
  }, [reconcileChangedDraftOperation]);

  const executeSendMessage = useCallback(async (
    admissionGuard?: ChatRetryGuard,
  ) => {
    const trimmedMessage = inputValue.trim();
    if (!currentSessionId) {
      toast.error(translate('chat.sessionRequired'));
      return;
    }
    const originSessionId = currentSessionId;
    const sessionStartGuard = admissionGuard
      ?? captureChatRetryGuard(originSessionId);
    if (
      sessionStartGuard.sessionId !== originSessionId
      || !areChatRetryGuardsCurrent(sessionStartGuard)
    ) {
      return;
    }
    if (
      pendingAsk?.expiresAtMs !== null
      && pendingAsk?.expiresAtMs !== undefined
      && pendingAsk.expiresAtMs <= Date.now()
    ) {
      toast.warning(translate('chat.askNoLongerPending'));
      return;
    }
    if (
      pendingAsk
      && !pendingAsk.allowFreeText
      && !pendingAsk.options.includes(trimmedMessage)
    ) {
      toast.warning(translate('chat.askOptionRequired'));
      return;
    }
    const externalAdmission = await reconcileExternalTurnBeforeSend(
      originSessionId,
    );
    if (!areChatRetryGuardsCurrent(sessionStartGuard)) {
      return;
    }
    if (externalAdmission.kind === 'unconfirmed') {
      toast.warning(translate('chat.previousSendUnconfirmed'));
      return;
    }
    if (externalAdmission.kind === 'pending') {
      const alreadyVisible = (
        useConversationStore.getState().messagesBySession[
          externalAdmission.sessionId
        ] || []
      ).some((message) => (
        message.role === 'user'
        && String(message.turnId || '').trim()
          === externalAdmission.turnId
      ));
      if (!alreadyVisible) {
        appendPendingTurn({
          sessionId: externalAdmission.sessionId,
          input: externalAdmission.input,
          turnId: externalAdmission.turnId,
          timestamp: externalAdmission.timestamp,
          pendingLabel: translate('chat.trace.pending'),
        });
      }
      if (!allowInterjection) {
        onPendingResponseTurn(
          externalAdmission.sessionId,
          externalAdmission.turnId,
        );
      }
      window.dispatchEvent(new Event(APP_EVENTS.SESSION_SYNC));
      if (!pendingAsk) {
        return;
      }
    }
    if (
      externalAdmission.kind === 'ready'
      && externalAdmission.stopCurrentIntent
      && !pendingAsk
    ) {
      toast.warning(translate('chat.restoredSendResolved'));
      return;
    }
    let retryableOperation = retryableSendsRef.current.get(originSessionId);
    if (
      retryableOperation
      && !isRetryableChatSendFresh(retryableOperation, Date.now())
    ) {
      retryableSendsRef.current.delete(originSessionId);
      restoredRetryableTurnIdsRef.current.delete(retryableOperation.turnId);
      saveRetryableChatSends(retryableSendsRef.current);
      retryableOperation = undefined;
    }
    if (
      retryableOperation
      && retryableOperation.draftSignature === composerDraftSignature
    ) {
      setSessionSending(originSessionId, true);
      try {
        await submitOperation({
          ...retryableOperation,
          draftIdentity: composerDraftIdentity,
          draftSignature: composerDraftSignature,
        }, true, sessionStartGuard);
      } finally {
        setSessionSending(originSessionId, false);
      }
      return;
    }
    if (retryableOperation) {
      setSessionSending(originSessionId, true);
      try {
        if (!await reconcileChangedDraftOperation(
          retryableOperation,
          Boolean(pendingAsk),
        )) {
          return;
        }
      } finally {
        setSessionSending(originSessionId, false);
      }
    }
    if (recallFeedbackDraft && !trimmedMessage) {
      toast.warning(translate('chat.emptyInput'));
      return;
    }
    if (!recallFeedbackDraft && !trimmedMessage && draftAttachments.length === 0) {
      toast.warning(translate('chat.emptyInput'));
      return;
    }

    if (pendingAsk) {
      if (recallFeedbackDraft) {
        toast.warning(translate('chat.recallFeedback.pendingAskBlocked'));
        return;
      }
      if (!trimmedMessage) {
        toast.warning(translate('chat.emptyInput'));
        return;
      }
      if (draftAttachments.length > 0) {
        toast.warning(translate('chat.askAttachmentsUnsupported', { defaultValue: 'Remove attachments before answering this question.' }));
        return;
      }

      setSessionSending(originSessionId, true);
      try {
        const turnId = createClientTurnId();
        await submitOperation({
          sessionId: originSessionId,
          turnId,
          createdAtMs: Date.now(),
          draftIdentity: composerDraftIdentity,
          draftSignature: composerDraftSignature,
          draftKind: 'pending_ask',
          request: {
            user_id: USER_ID,
            session_id: originSessionId,
            message: trimmedMessage,
            workspace_path: currentWorkspacePath ?? null,
            client_turn_id: turnId,
            metadata: {
              ask_request_id: pendingAsk.requestId,
            },
          },
          confirmation: {
            kind: 'ask_response',
            sessionId: originSessionId,
            requestId: pendingAsk.requestId,
            answer: trimmedMessage,
          },
          askAnswer: {
            ...pendingAsk,
            answer: trimmedMessage,
            timestamp: Date.now(),
          },
        }, false, sessionStartGuard);
      } finally {
        setSessionSending(originSessionId, false);
      }
      return;
    }

    if (recallFeedbackDraft) {
      setSessionSending(originSessionId, true);
      try {
        const turnId = createClientTurnId();
        const feedbackRequest = toRecallFeedbackRequest(recallFeedbackDraft);
        const feedbackReply = toRecallFeedbackReplyPreview(recallFeedbackDraft);
        await submitOperation({
          sessionId: originSessionId,
          turnId,
          createdAtMs: Date.now(),
          draftIdentity: composerDraftIdentity,
          draftSignature: composerDraftSignature,
          draftKind: 'recall_feedback',
          request: {
            user_id: USER_ID,
            session_id: originSessionId,
            message: trimmedMessage,
            reply_to_message_id: recallFeedbackDraft.targetMessageId,
            workspace_path: currentWorkspacePath ?? null,
            client_turn_id: turnId,
            recall_feedback: feedbackRequest,
          },
          confirmation: {
            kind: 'turn',
            sessionId: originSessionId,
            turnId,
          },
          pendingTurn: {
            sessionId: originSessionId,
            input: trimmedMessage,
            turnId,
            timestamp: Date.now(),
            pendingLabel: translate('chat.trace.pending'),
            replyTo: feedbackReply,
            payload: { recall_feedback: feedbackRequest },
          },
        }, false, sessionStartGuard);
      } finally {
        setSessionSending(originSessionId, false);
      }
      return;
    }

    if (firstContextQuestion && draftAttachments.length > 0) {
      toast.warning(translate('chat.firstContextContinuation.attachmentsUnsupported'));
      return;
    }

    const messageContent = trimmedMessage;

    setSessionSending(originSessionId, true);
    try {
      const turnId = createClientTurnId();
      let uploadedAttachments: ChatAttachment[];
      try {
        uploadedAttachments = await uploadDraftAttachments(
          originSessionId,
          turnId,
          draftAttachments,
        );
      } catch (error: unknown) {
        if (!areChatRetryGuardsCurrent(sessionStartGuard)) {
          return;
        }
        const message = error instanceof Error
          ? error.message
          : translate('chat.sendFailed');
        toast.error(translate('chat.attachments.uploadFailed', { message }));
        return;
      }
      if (!areChatRetryGuardsCurrent(sessionStartGuard)) {
        return;
      }
      const operation: RetryableSendOperation = {
        sessionId: originSessionId,
        turnId,
        createdAtMs: Date.now(),
        draftIdentity: composerDraftIdentity,
        draftSignature: composerDraftSignature,
        draftKind: firstContextQuestion ? 'first_context' : 'normal',
        request: {
          user_id: USER_ID,
          session_id: originSessionId,
          message: messageContent,
          attachments: uploadedAttachments,
          reply_to_message_id: replyTarget?.messageId,
          workspace_path: currentWorkspacePath ?? null,
          client_turn_id: turnId,
          reasoning_preference: reasoningPreference,
          ...(firstContextQuestion ? {
            interaction_kind: 'first_context_story' as const,
            first_context: {
              question_id: firstContextQuestion.questionId,
              question_text: firstContextQuestion.questionText,
            },
          } : {}),
        },
        confirmation: {
          kind: 'turn',
          sessionId: originSessionId,
          turnId,
        },
        pendingTurn: {
          sessionId: originSessionId,
          input: messageContent,
          turnId,
          timestamp: Date.now(),
          pendingLabel: translate('chat.trace.pending'),
          attachments: uploadedAttachments,
          replyTo: replyTarget,
          payload: firstContextQuestion ? {
            interaction_kind: 'first_context_story',
            first_context: {
              question_id: firstContextQuestion.questionId,
              question_text: firstContextQuestion.questionText,
            },
          } : undefined,
        },
      };
      try {
        await submitOperation(operation, false, sessionStartGuard);
      } catch {
        onPendingResponseFailure(originSessionId, turnId);
        removePendingMessage(originSessionId, `${turnId}-user`);
        toast.error(translate('chat.sendFailed'));
      }
    } finally {
      setSessionSending(originSessionId, false);
    }
  }, [
    allowInterjection,
    appendPendingTurn,
    composerDraftIdentity,
    composerDraftSignature,
    currentSessionId,
    currentWorkspacePath,
    draftAttachments,
    firstContextQuestion,
    inputValue,
    pendingAsk,
    onPendingResponseFailure,
    onPendingResponseTurn,
    recallFeedbackDraft,
    reasoningPreference,
    reconcileChangedDraftOperation,
    reconcileExternalTurnBeforeSend,
    removePendingMessage,
    replyTarget,
    setSessionSending,
    submitOperation,
    translate,
    uploadDraftAttachments,
  ]);

  const handleSendMessage = useCallback(async () => {
    const sessionId = String(currentSessionId || '').trim();
    if (!sessionId) {
      await executeSendMessage();
      return;
    }
    const admissionGuard = captureChatRetryGuard(sessionId);
    const submissionKind = pendingAsk
      ? 'ask_response'
      : recallFeedbackDraft
        ? 'recall_feedback'
        : 'message';
    const admission = await runWithTurnAdmission(
      sessionId,
      submissionKind,
      () => executeSendMessage(admissionGuard),
    );
    if (!admission.entered && admission.reason === 'pending_turn') {
      toast.warning(translate('chat.waitForCurrentReply'));
    }
    if (!admission.entered && admission.reason === 'history_unavailable') {
      toast.warning(translate('chat.historyNotReady'));
    }
    if (!admission.entered && admission.reason === 'exclusive_action') {
      toast.warning(translate('chat.clearHistoryDialog.inProgress'));
    }
  }, [
    currentSessionId,
    executeSendMessage,
    pendingAsk,
    recallFeedbackDraft,
    runWithTurnAdmission,
    translate,
  ]);

  return {
    sendingMessage,
    handleSendMessage,
    reconcilePendingSendBeforeExternalTurn,
    clearRetryableSendForTurn,
    clearRetryableSendsForSession,
    clearAllRetryableSends,
  };
}
