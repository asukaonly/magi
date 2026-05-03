import { useCallback, useRef, useState } from 'react';
import type React from 'react';
import { shouldSubmitOnEnter } from '@/pages/chat-route-helpers';
import type { ChatTimelineReplyPreview } from '@/domain/chat/state';
import { useChatDraftAttachments } from './useChatDraftAttachments';
import { useChatSendMessage, type UseChatSendMessageOptions } from './useChatSendMessage';

type UseChatComposerControllerOptions = Pick<
  UseChatSendMessageOptions,
  'currentSessionId' | 'currentWorkspacePath' | 'allowInterjection' | 'appendPendingTurn' | 'setCurrentSessionId' | 'translate'
> & {
  coreModelSupportsVision: boolean;
  requestRunCancel: (turnId: string) => Promise<unknown> | void;
};

export function useChatComposerController({
  currentSessionId,
  currentWorkspacePath,
  allowInterjection,
  coreModelSupportsVision,
  appendPendingTurn,
  setCurrentSessionId,
  requestRunCancel,
  translate,
}: UseChatComposerControllerOptions) {
  const [inputValue, setInputValue] = useState('');
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
    onSessionReset: clearReplyTarget,
    translate,
  });

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
    appendPendingTurn,
    setInputValue,
    setCurrentSessionId,
    clearDraftAttachments,
    clearReplyTarget,
    onPendingResponseTurn: handlePendingResponseTurn,
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
    if (!allowInterjection && turnActive && pendingResponseTurnId) {
      void requestRunCancel(pendingResponseTurnId);
      return;
    }
    void handleSendMessage();
  }, [allowInterjection, handleSendMessage, pendingResponseTurnId, requestRunCancel, turnActive]);

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
    removeDraftAttachment,
    replyTarget,
    sendingMessage,
    setAttachmentMenuOpen,
    setInputValue,
    setReplyTarget,
    waitingForReply: !allowInterjection && turnActive,
  };
}