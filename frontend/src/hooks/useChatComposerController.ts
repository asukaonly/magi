import { useCallback, useEffect, useRef, useState } from 'react';
import type React from 'react';
import {
  buildRecallFeedbackDraftText,
  type RecallFeedbackDraft,
} from '@/domain/chat/recall-feedback';
import { shouldSubmitOnEnter } from '@/domain/chat/shell-routing';
import type { ChatTimelineReplyPreview } from '@/domain/chat/state';
import type { PendingResponseTurnIdentity } from '@/domain/chat/turn-completion';
import { useChatDraftAttachments } from './useChatDraftAttachments';
import type { RunCancelOutcome } from './useChatExecutionControls';
import {
  useChatSendMessage,
  type ComposerSendDraftKind,
  type PendingAskAnswerPayload,
  type PendingAskSendContext,
  type UseChatSendMessageOptions,
} from './useChatSendMessage';

type UseChatComposerControllerOptions = Pick<
  UseChatSendMessageOptions,
  'currentSessionId'
  | 'currentWorkspacePath'
  | 'allowInterjection'
  | 'appendPendingTurn'
  | 'removePendingMessage'
  | 'setCurrentSessionId'
  | 'reconcileExternalTurnBeforeSend'
  | 'runWithTurnAdmission'
  | 'translate'
> & {
  coreModelSupportsVision: boolean;
  pendingAsk: PendingAskSendContext | null;
  onAskAnswered: (answer: PendingAskAnswerPayload) => void;
  requestRunCancel: (turnId: string) => Promise<RunCancelOutcome>;
  markAdmissionPendingTurn: (sessionId: string, turnId: string) => void;
  clearAdmissionPendingTurn: (sessionId: string, turnId?: string) => void;
};

type PendingAskDraft = {
  sessionId: string;
  requestId: string;
  value: string;
};

export function useChatComposerController({
  currentSessionId,
  currentWorkspacePath,
  allowInterjection,
  coreModelSupportsVision,
  pendingAsk,
  appendPendingTurn,
  removePendingMessage,
  setCurrentSessionId,
  onAskAnswered,
  requestRunCancel,
  markAdmissionPendingTurn,
  clearAdmissionPendingTurn,
  reconcileExternalTurnBeforeSend,
  runWithTurnAdmission,
  translate,
}: UseChatComposerControllerOptions) {
  const [normalInputValue, setNormalInputValue] = useState('');
  const [pendingAskDraft, setPendingAskDraft] = useState<PendingAskDraft | null>(null);
  const [recallFeedbackDraft, setRecallFeedbackDraft] = useState<RecallFeedbackDraft | null>(null);
  const [replyTarget, setReplyTarget] = useState<ChatTimelineReplyPreview | null>(null);
  const [pendingResponseTurnsBySession, setPendingResponseTurnsBySession] = useState<Record<string, string>>({});
  const pendingResponseTurnsRef = useRef<Record<string, string>>({});
  const currentSessionIdRef = useRef(currentSessionId);
  currentSessionIdRef.current = currentSessionId;
  const previousComposerSessionIdRef = useRef(currentSessionId);
  const composerSessionRevisionRef = useRef(0);
  if (previousComposerSessionIdRef.current !== currentSessionId) {
    previousComposerSessionIdRef.current = currentSessionId;
    composerSessionRevisionRef.current += 1;
  }
  const composerRef = useRef<HTMLDivElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const isComposingRef = useRef(false);
  const getCurrentSessionId = useCallback(() => currentSessionIdRef.current, []);

  const clearSessionTransientState = useCallback(() => {
    setReplyTarget(null);
    setRecallFeedbackDraft(null);
  }, []);

  const {
    attachmentMenuOpen,
    draftAttachments,
    clearDraftAttachments,
    removeDraftAttachment,
    addMcpResourceDraft,
    handleAttachmentInputChange,
    handleComposerPaste,
    setAttachmentMenuOpen,
  } = useChatDraftAttachments({
    currentSessionId,
    coreModelSupportsVision,
    composerRef,
    onSessionReset: clearSessionTransientState,
    translate,
  });

  const activePendingAskDraft = (
    pendingAskDraft
    && pendingAsk
    && pendingAskDraft.sessionId === pendingAsk.sessionId
    && pendingAskDraft.requestId === pendingAsk.requestId
  )
    ? pendingAskDraft
    : null;
  const inputValue = recallFeedbackDraft
    ? buildRecallFeedbackDraftText(recallFeedbackDraft, translate)
    : pendingAsk
      ? activePendingAskDraft?.value ?? ''
      : normalInputValue;
  const composerDraftSignature = JSON.stringify(
    recallFeedbackDraft
      ? [
        'recall_feedback',
        inputValue,
        recallFeedbackDraft.kind,
        recallFeedbackDraft.targetMessageId,
        recallFeedbackDraft.findingRef || null,
        currentWorkspacePath || null,
      ]
      : pendingAsk
        ? [
          'pending_ask',
          inputValue,
          pendingAsk.requestId,
          currentWorkspacePath || null,
        ]
        : [
          'normal',
          inputValue,
          draftAttachments.map((attachment) => [attachment.kind, attachment.id]),
          replyTarget?.messageId || null,
          currentWorkspacePath || null,
        ],
  );
  const composerDraftIdentity = JSON.stringify([
    composerSessionRevisionRef.current,
    composerDraftSignature,
  ]);
  const composerDraftIdentityRef = useRef(composerDraftIdentity);
  composerDraftIdentityRef.current = composerDraftIdentity;
  const composerDraftSignatureRef = useRef(composerDraftSignature);
  composerDraftSignatureRef.current = composerDraftSignature;

  const setInputValue = useCallback((value: string) => {
    if (recallFeedbackDraft) {
      setRecallFeedbackDraft((current) => (
        current ? { ...current, customText: value } : current
      ));
      return;
    }
    if (pendingAsk) {
      setPendingAskDraft({
        sessionId: pendingAsk.sessionId,
        requestId: pendingAsk.requestId,
        value,
      });
      return;
    }
    setNormalInputValue(value);
  }, [pendingAsk, recallFeedbackDraft]);

  useEffect(() => {
    setPendingAskDraft((current) => {
      if (!current) {
        return current;
      }
      if (
        pendingAsk
        && current.sessionId === pendingAsk.sessionId
        && current.requestId === pendingAsk.requestId
      ) {
        return current;
      }
      return null;
    });
  }, [pendingAsk?.requestId, pendingAsk?.sessionId]);

  const clearRecallFeedback = useCallback(() => {
    setRecallFeedbackDraft(null);
  }, []);

  const clearComposerReferenceToMessage = useCallback((messageId: string) => {
    const normalizedMessageId = String(messageId || '').trim();
    if (!normalizedMessageId) {
      return;
    }
    setReplyTarget((current) => (
      current?.messageId === normalizedMessageId ? null : current
    ));
    setRecallFeedbackDraft((current) => (
      current?.targetMessageId === normalizedMessageId ? null : current
    ));
  }, []);

  const clearConversationBoundDraftState = useCallback(() => {
    clearDraftAttachments();
    setAttachmentMenuOpen(false);
    setPendingAskDraft(null);
    clearSessionTransientState();
  }, [
    clearDraftAttachments,
    clearSessionTransientState,
    setAttachmentMenuOpen,
  ]);

  const clearHistoryBoundDraftState = useCallback(() => {
    setPendingAskDraft(null);
    clearSessionTransientState();
  }, [clearSessionTransientState]);

  const clearDeletedSessionDraftState = useCallback(() => {
    clearConversationBoundDraftState();
    setNormalInputValue('');
  }, [clearConversationBoundDraftState]);

  const clearComposerDraftIfUnchanged = useCallback((
    expectedIdentity: string,
    expectedSignature: string,
    kind: ComposerSendDraftKind,
  ) => {
    if (
      composerDraftIdentityRef.current !== expectedIdentity
      || composerDraftSignatureRef.current !== expectedSignature
    ) {
      return;
    }
    if (kind === 'recall_feedback') {
      setRecallFeedbackDraft(null);
      return;
    }
    if (kind === 'pending_ask') {
      setPendingAskDraft(null);
      return;
    }
    setNormalInputValue('');
    clearDraftAttachments();
    setReplyTarget(null);
  }, [clearDraftAttachments]);

  const startRecallFeedback = useCallback((draft: Omit<RecallFeedbackDraft, 'customText'>) => {
    if (pendingAsk) {
      return false;
    }
    setAttachmentMenuOpen(false);
    setRecallFeedbackDraft({ ...draft, customText: null });
    window.requestAnimationFrame(() => {
      composerRef.current?.querySelector('textarea')?.focus();
    });
    return true;
  }, [composerRef, pendingAsk, setAttachmentMenuOpen]);

  const convertRecallFeedbackToNormal = useCallback(() => {
    if (!recallFeedbackDraft) {
      return;
    }
    setNormalInputValue(buildRecallFeedbackDraftText(recallFeedbackDraft, translate));
    setRecallFeedbackDraft(null);
  }, [recallFeedbackDraft, translate]);

  const handlePendingResponseTurn = useCallback((sessionId: string, turnId: string) => {
    const normalizedSessionId = String(sessionId || '').trim();
    const normalizedTurnId = String(turnId || '').trim();
    if (!normalizedSessionId || !normalizedTurnId) {
      return;
    }
    markAdmissionPendingTurn(normalizedSessionId, normalizedTurnId);
    pendingResponseTurnsRef.current = {
      ...pendingResponseTurnsRef.current,
      [normalizedSessionId]: normalizedTurnId,
    };
    setPendingResponseTurnsBySession((current) => (
      current[normalizedSessionId] === normalizedTurnId
        ? current
        : {
          ...current,
          [normalizedSessionId]: normalizedTurnId,
        }
    ));
  }, [markAdmissionPendingTurn]);

  const clearPendingResponseTurn = useCallback((
    expected?: Partial<PendingResponseTurnIdentity>,
  ) => {
    const expectedSessionId = String(
      expected?.sessionId || currentSessionId || '',
    ).trim();
    const expectedTurnId = String(expected?.turnId || '').trim();
    const trackedTurnId = expectedSessionId
      ? pendingResponseTurnsRef.current[expectedSessionId]
      : undefined;
    if (expectedSessionId) {
      clearAdmissionPendingTurn(
        expectedSessionId,
        expectedTurnId || trackedTurnId,
      );
    }
    if (
      expectedSessionId
      && trackedTurnId
      && (!expectedTurnId || trackedTurnId === expectedTurnId)
    ) {
      const next = { ...pendingResponseTurnsRef.current };
      delete next[expectedSessionId];
      pendingResponseTurnsRef.current = next;
    }
    setPendingResponseTurnsBySession((current) => {
      if (!expectedSessionId || !current[expectedSessionId]) {
        return current;
      }
      if (expectedTurnId && current[expectedSessionId] !== expectedTurnId) {
        return current;
      }
      const next = { ...current };
      delete next[expectedSessionId];
      return next;
    });
  }, [clearAdmissionPendingTurn, currentSessionId]);

  const clearAllPendingResponseTurns = useCallback(() => {
    for (const [sessionId, turnId] of Object.entries(
      pendingResponseTurnsRef.current,
    )) {
      clearAdmissionPendingTurn(sessionId, turnId);
    }
    pendingResponseTurnsRef.current = {};
    setPendingResponseTurnsBySession((current) => (
      Object.keys(current).length === 0 ? current : {}
    ));
  }, [clearAdmissionPendingTurn]);

  useEffect(() => {
    if (!allowInterjection) {
      return;
    }
    for (const [sessionId, turnId] of Object.entries(
      pendingResponseTurnsRef.current,
    )) {
      clearAdmissionPendingTurn(sessionId, turnId);
    }
    pendingResponseTurnsRef.current = {};
    setPendingResponseTurnsBySession((current) => (
      Object.keys(current).length === 0 ? current : {}
    ));
  }, [allowInterjection, clearAdmissionPendingTurn]);

  const normalizedCurrentSessionId = String(currentSessionId || '').trim();
  const pendingResponseTurnId = normalizedCurrentSessionId
    ? pendingResponseTurnsBySession[normalizedCurrentSessionId] || null
    : null;

  const handleAskAnswered = useCallback((answer: PendingAskAnswerPayload) => {
    if (
      pendingAskDraft
      && pendingAskDraft.sessionId === answer.sessionId
      && pendingAskDraft.requestId === answer.requestId
      && pendingAskDraft.value.trim()
      && pendingAskDraft.value.trim() !== answer.answer.trim()
    ) {
      setNormalInputValue(pendingAskDraft.value);
    }
    setPendingAskDraft(null);
    onAskAnswered(answer);
  }, [onAskAnswered, pendingAskDraft]);

  const {
    clearAllRetryableSends,
    clearRetryableSendForTurn,
    clearRetryableSendsForSession,
    sendingMessage,
    handleSendMessage,
    reconcilePendingSendBeforeExternalTurn,
  } = useChatSendMessage({
    currentSessionId,
    currentWorkspacePath,
    inputValue,
    draftAttachments,
    replyTarget,
    allowInterjection,
    pendingAsk,
    recallFeedbackDraft,
    appendPendingTurn,
    removePendingMessage,
    setCurrentSessionId,
    getCurrentSessionId,
    composerDraftIdentity,
    composerDraftSignature,
    clearComposerDraftIfUnchanged,
    onPendingResponseTurn: handlePendingResponseTurn,
    onPendingResponseFailure: (sessionId, turnId) => {
      clearPendingResponseTurn({ sessionId, turnId });
    },
    onAskAnswered: handleAskAnswered,
    reconcileExternalTurnBeforeSend,
    runWithTurnAdmission,
    translate,
  });

  const handleComposerKeyDown = useCallback((event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (shouldSubmitOnEnter(event, isComposingRef.current)) {
      event.preventDefault();
      void handleSendMessage();
    }
  }, [handleSendMessage]);

  const handleComposerPrimaryAction = useCallback(async () => {
    if (!recallFeedbackDraft && !pendingAsk && !allowInterjection && pendingResponseTurnId) {
      const outcome = await requestRunCancel(pendingResponseTurnId);
      if (outcome === 'settled') {
        clearPendingResponseTurn({
          sessionId: normalizedCurrentSessionId,
          turnId: pendingResponseTurnId,
        });
      }
      return;
    }
    await handleSendMessage();
  }, [
    allowInterjection,
    clearPendingResponseTurn,
    handleSendMessage,
    normalizedCurrentSessionId,
    pendingAsk,
    pendingResponseTurnId,
    recallFeedbackDraft,
    requestRunCancel,
  ]);

  const handleCompositionStart = useCallback(() => {
    isComposingRef.current = true;
  }, []);

  const handleCompositionEnd = useCallback(() => {
    isComposingRef.current = false;
  }, []);

  return {
    attachmentMenuOpen,
    clearAllPendingResponseTurns,
    clearAllRetryableSends,
    clearConversationBoundDraftState,
    clearComposerReferenceToMessage,
    clearDeletedSessionDraftState,
    clearHistoryBoundDraftState,
    clearRetryableSendForTurn,
    clearRetryableSendsForSession,
    clearPendingResponseTurn,
    composerRef,
    draftAttachments,
    fileInputRef,
    addMcpResourceDraft,
    handleAttachmentInputChange,
    handleComposerKeyDown,
    handleComposerPaste,
    handleComposerPrimaryAction,
    handleCompositionEnd,
    handleCompositionStart,
    imageInputRef,
    inputValue,
    pendingResponseTurnId,
    pendingResponseTurnsBySession,
    reconcilePendingSendBeforeExternalTurn,
    trackPendingResponseTurn: handlePendingResponseTurn,
    recallFeedbackDraft,
    removeDraftAttachment,
    replyTarget,
    sendingMessage,
    setAttachmentMenuOpen,
    setInputValue,
    setReplyTarget,
    startRecallFeedback,
    cancelRecallFeedback: clearRecallFeedback,
    convertRecallFeedbackToNormal,
    waitingForReply: (
      !pendingAsk
      && !allowInterjection
      && Boolean(pendingResponseTurnId)
    ),
  };
}
