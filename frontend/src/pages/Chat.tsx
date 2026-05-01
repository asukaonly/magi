/**
 * Chat page - desktop-focused conversation workspace
 */
import React, { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { motion, useReducedMotion } from 'framer-motion';
import { ChatWorkspaceStatusBar } from '@/components/chat/ChatWorkspaceStatusBar';
import { useChatComposerController } from '@/hooks/useChatComposerController';
import { useChatMessageOverlays } from '@/hooks/useChatMessageOverlays';
import { useChatMessageMutations } from '@/hooks/useChatMessageMutations';
import { useChatRealtimeEffects } from '@/hooks/useChatRealtimeEffects';
import { useChatSessionLifecycle } from '@/hooks/useChatSessionLifecycle';
import { useChatTraceDrawer } from '@/hooks/useChatTraceDrawer';
import { useChatWorkspaceActions } from '@/hooks/useChatWorkspaceActions';
import { useChatExecutionControls } from '@/hooks/useChatExecutionControls';
import { useConversationStore } from '@/stores';
import { ChatComposerPane } from '@/components/chat/ChatComposerPane';
import { ChatPageOverlays } from '@/components/chat/ChatPageOverlays';
import { ChatTimelinePane } from '@/components/chat/ChatTimelinePane';
import { isTranscriptMessage } from '@/domain/chat/presentation';
const DEFAULT_CHAT_WORKSPACE_DISPLAY = '~/.magi/chat-workspace';
const toPlainText = (content: string): string => String(content || '')
  .replace(/```[\s\S]*?```/g, (block) => block.replace(/```[\w-]*\n?/g, '').replace(/```/g, ''))
  .replace(/`([^`]+)`/g, '$1')
  .replace(/!\[([^\]]*)\]\([^)]+\)/g, '$1')
  .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
  .replace(/^\s{0,3}#{1,6}\s+/gm, '')
  .replace(/^\s*>\s?/gm, '')
  .replace(/^\s*[-*+]\s+/gm, '')
  .replace(/^\s*\d+\.\s+/gm, '')
  .replace(/\*\*([^*]+)\*\*/g, '$1')
  .replace(/\*([^*]+)\*/g, '$1')
  .replace(/__([^_]+)__/g, '$1')
  .replace(/_([^_]+)_/g, '$1')
  .replace(/\n{3,}/g, '\n\n')
  .trim();

interface HistoryImagePreview {
  name: string;
  url: string;
}
const getWorkspaceDisplayPath = (workspacePath: string | null | undefined): string => {
  const normalizedPath = String(workspacePath || '').trim();
  return normalizedPath || DEFAULT_CHAT_WORKSPACE_DISPLAY;
};

export const ChatPage: React.FC = () => {
  const { t } = useTranslation('app');
  const shouldReduceMotion = useReducedMotion();
  const currentSessionId = useConversationStore((state) => state.currentSessionId);
  const currentSession = useConversationStore((state) => (
    state.currentSessionId ? state.sessionsById[state.currentSessionId] || null : null
  ));
  const setCurrentSessionId = useConversationStore((state) => state.setCurrentSessionId);
  const messages = useConversationStore((state) =>
    state.currentSessionId ? (state.messagesBySession[state.currentSessionId] || []) : []
  );
  const upsertSession = useConversationStore((state) => state.upsertSession);
  const appendPendingTurn = useConversationStore((state) => state.appendPendingTurn);
  const upsertMessage = useConversationStore((state) => state.upsertMessage);
  const applyMessageLabel = useConversationStore((state) => state.applyMessageLabel);
  const removeMessage = useConversationStore((state) => state.removeMessage);
  const resetConversation = useConversationStore((state) => state.reset);

  const [historyImagePreview, setHistoryImagePreview] = useState<HistoryImagePreview | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const clearPendingResponseTurnRef = useRef<() => void>(() => {});

  const {
    loadingTrace,
    summaries,
    snapshots,
    drawerOpen,
    activeTurnId,
    openTraceDrawer,
    closeTraceDrawer,
    refreshVisibleTrace,
    resetTraceDrawer,
  } = useChatTraceDrawer({ currentSessionId });

  const {
    cancellingTurnIds,
    detachingTurnIds,
    executionControlByTurnId,
    requestRunCancel,
    requestRunDetach,
    handleTurnExecutionControlEvent,
  } = useChatExecutionControls({
    currentSessionId,
    onTerminalExecutionState: () => clearPendingResponseTurnRef.current(),
  });

  const {
    aiName,
    aiAvatar,
    assistantPersonas,
    coreModelSupportsVision,
    allowInterjection,
  } = useChatSessionLifecycle({
    currentSessionId,
    setCurrentSessionId,
    resetConversation,
    resetTraceDrawer,
    upsertMessage,
    removeMessage,
    translate: t,
  });

  const {
    updatingWorkspace,
    persistSessionWorkspace,
    handlePickWorkspace,
  } = useChatWorkspaceActions({
    currentSessionId,
    currentWorkspacePath: currentSession?.workspace_path,
    upsertSession,
    translate: t,
  });

  const {
    labelPopoverState,
    labelPopoverDraft,
    messageContextMenu,
    labelPopoverRef,
    messageContextMenuRef,
    closeLabelPopover,
    closeMessageContextMenu,
    openLabelPopover,
    openMessageContextMenu,
    handleLabelDraftChange,
    handleLabelDraftCompositionStart,
    handleLabelDraftCompositionEnd,
  } = useChatMessageOverlays(currentSessionId);

  const {
    attachmentMenuOpen,
    clearPendingResponseTurn,
    composerRef,
    draftAttachments,
    fileInputRef,
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
    waitingForReply,
  } = useChatComposerController({
    currentSessionId,
    currentWorkspacePath: currentSession?.workspace_path,
    allowInterjection,
    coreModelSupportsVision,
    appendPendingTurn,
    setCurrentSessionId,
    requestRunCancel,
    translate: t,
  });

  useEffect(() => {
    clearPendingResponseTurnRef.current = clearPendingResponseTurn;
  }, [clearPendingResponseTurn]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useChatRealtimeEffects({
    allowInterjection,
    turnActive: waitingForReply,
    refreshVisibleTrace,
    handleTurnExecutionControlEvent,
    clearPendingResponseTurn,
  });

  const {
    applyLabelToMessage,
    handleDeleteMessage,
    handleCopyMessage,
  } = useChatMessageMutations({
    currentSessionId,
    activeLabelMessageId: labelPopoverState?.messageId || null,
    applyMessageLabel,
    removeMessage,
    closeLabelPopover,
    closeMessageContextMenu,
    normalizeCopyText: toPlainText,
    translate: t,
  });

  const visibleMessageCount = messages.filter(isTranscriptMessage).length;
  const workspaceDisplayPath = getWorkspaceDisplayPath(currentSession?.workspace_path);
  const hasSessionWorkspaceOverride = Boolean(String(currentSession?.workspace_path || '').trim());

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.15 }}
      className="relative flex h-full min-h-0 flex-col px-3 pb-3 pt-2"
    >
      <ChatWorkspaceStatusBar
        visible={Boolean(currentSessionId)}
        messageCount={visibleMessageCount}
        workspaceDisplayPath={workspaceDisplayPath}
        hasSessionWorkspaceOverride={hasSessionWorkspaceOverride}
        updatingWorkspace={updatingWorkspace}
        onChangeWorkspace={() => {
          void handlePickWorkspace();
        }}
        onClearWorkspace={() => {
          void persistSessionWorkspace(null);
        }}
      />

      <ChatTimelinePane
        messages={messages}
        assistantName={aiName}
        assistantAvatar={aiAvatar}
        assistantPersonas={assistantPersonas}
        currentSessionId={currentSessionId}
        shouldReduceMotion={Boolean(shouldReduceMotion)}
        summaries={summaries}
        executionControlByTurnId={executionControlByTurnId}
        cancellingTurnIds={cancellingTurnIds}
        detachingTurnIds={detachingTurnIds}
        labelPopoverState={labelPopoverState}
        labelPopoverDraft={labelPopoverDraft}
        labelPopoverRef={labelPopoverRef}
        messageContextMenu={messageContextMenu}
        messageContextMenuRef={messageContextMenuRef}
        messagesEndRef={messagesEndRef}
        onSetReplyTarget={setReplyTarget}
        onOpenImagePreview={setHistoryImagePreview}
        onOpenTraceDrawer={openTraceDrawer}
        onRequestRunCancel={requestRunCancel}
        onRequestRunDetach={requestRunDetach}
        onCloseLabelPopover={closeLabelPopover}
        onCloseMessageContextMenu={closeMessageContextMenu}
        onOpenLabelPopover={openLabelPopover}
        onOpenMessageContextMenu={openMessageContextMenu}
        onApplyLabelToMessage={applyLabelToMessage}
        onLabelDraftChange={handleLabelDraftChange}
        onLabelDraftCompositionStart={handleLabelDraftCompositionStart}
        onLabelDraftCompositionEnd={handleLabelDraftCompositionEnd}
        onCopyMessage={handleCopyMessage}
        onDeleteMessage={handleDeleteMessage}
      />

      <ChatComposerPane
        composerRef={composerRef}
        replyTarget={replyTarget}
        onCancelReply={() => setReplyTarget(null)}
        attachments={draftAttachments}
        onRemoveAttachment={removeDraftAttachment}
        inputValue={inputValue}
        onInputChange={setInputValue}
        onCompositionStart={handleCompositionStart}
        onCompositionEnd={handleCompositionEnd}
        onKeyDown={handleComposerKeyDown}
        onPaste={handleComposerPaste}
        waitingForReply={waitingForReply}
        attachmentMenuOpen={attachmentMenuOpen}
        coreModelSupportsVision={coreModelSupportsVision}
        onToggleAttachmentMenu={() => setAttachmentMenuOpen((open) => !open)}
        onPickImage={() => imageInputRef.current?.click()}
        onPickFile={() => fileInputRef.current?.click()}
        sessionId={currentSessionId}
        sendingMessage={sendingMessage}
        onPrimaryAction={handleComposerPrimaryAction}
        imageInputRef={imageInputRef}
        fileInputRef={fileInputRef}
        onAttachmentInputChange={handleAttachmentInputChange}
      />

      <ChatPageOverlays
        activeTurnId={activeTurnId}
        drawerOpen={drawerOpen}
        historyImagePreview={historyImagePreview}
        loadingTrace={loadingTrace}
        onCloseHistoryImagePreview={() => setHistoryImagePreview(null)}
        onCloseTraceDrawer={closeTraceDrawer}
        traceSnapshots={snapshots}
      />
    </motion.div>
  );

};

export default ChatPage;
