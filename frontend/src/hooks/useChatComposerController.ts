import { useCallback, useRef, useState } from 'react';
import type React from 'react';
import {
  buildRecallFeedbackDraftText,
  type RecallFeedbackDraft,
} from '@/domain/chat/recall-feedback';
import { shouldSubmitOnEnter } from '@/domain/chat/shell-routing';
import type { ChatTimelineReplyPreview } from '@/domain/chat/state';
import { useChatDraftAttachments } from './useChatDraftAttachments';
import { useChatSendMessage, type PendingAskAnswerPayload, type PendingAskSendContext, type UseChatSendMessageOptions } from './useChatSendMessage';

type UseChatComposerControllerOptions = Pick<
  UseChatSendMessageOptions,
  'currentSessionId' | 'currentWorkspacePath' | 'allowInterjection' | 'appendPendingTurn' | 'removePendingMessage' | 'setCurrentSessionId' | 'translate'
> & {
  coreModelSupportsVision: boolean;
  pendingAsk: PendingAskSendContext | null;
  onAskAnswered: (answer: PendingAskAnswerPayload) => void;
  requestRunCancel: (turnId: string) => Promise<unknown> | void;
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
  translate,
}: UseChatComposerControllerOptions) {
  const [normalInputValue, setNormalInputValue] = useState('');
  const [recallFeedbackDraft, setRecallFeedbackDraft] = useState<RecallFeedbackDraft | null>(null);
  const [replyTarget, setReplyTarget] = useState<ChatTimelineReplyPreview | null>(null);
  const [turnActive, setTurnActive] = useState(false);
  const [pendingResponseTurnId, setPendingResponseTurnId] = useState<string | null>(null);
  const composerRef = useRef<HTMLDivElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const isComposingRef = useRef(false);

  const clearReplyTarget = useCallback(() => {
    setReplyTarget(null);
  }, []);

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

  const inputValue = recallFeedbackDraft
    ? buildRecallFeedbackDraftText(recallFeedbackDraft, translate)
    : normalInputValue;

  const setInputValue = useCallback((value: string) => {
    if (recallFeedbackDraft) {
      setRecallFeedbackDraft((current) => (
        current ? { ...current, customText: value } : current
      ));
      return;
    }
    setNormalInputValue(value);
  }, [recallFeedbackDraft]);

  const clearRecallFeedback = useCallback(() => {
    setRecallFeedbackDraft(null);
  }, []);

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

  const handlePendingResponseTurn = useCallback((turnId: string) => {
    setTurnActive(true);
    setPendingResponseTurnId(turnId);
  }, []);

  const {
    sendingMessage,
    handleSendMessage,
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
    setInputValue,
    setCurrentSessionId,
    clearDraftAttachments,
    clearReplyTarget,
    clearRecallFeedback,
    onPendingResponseTurn: handlePendingResponseTurn,
    onAskAnswered,
    translate,
  });

  const clearPendingResponseTurn = useCallback(() => {
    setTurnActive(false);
    setPendingResponseTurnId(null);
  }, []);

  const handleComposerKeyDown = useCallback((event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (shouldSubmitOnEnter(event, isComposingRef.current)) {
      event.preventDefault();
      void handleSendMessage();
    }
  }, [handleSendMessage]);

  const handleComposerPrimaryAction = useCallback(() => {
    if (!recallFeedbackDraft && !pendingAsk && !allowInterjection && turnActive && pendingResponseTurnId) {
      void requestRunCancel(pendingResponseTurnId);
      return;
    }
    void handleSendMessage();
  }, [allowInterjection, handleSendMessage, pendingAsk, pendingResponseTurnId, recallFeedbackDraft, requestRunCancel, turnActive]);

  const handleCompositionStart = useCallback(() => {
    isComposingRef.current = true;
  }, []);

  const handleCompositionEnd = useCallback(() => {
    isComposingRef.current = false;
  }, []);

  return {
    attachmentMenuOpen,
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
    waitingForReply: !pendingAsk && !allowInterjection && turnActive,
  };
}
