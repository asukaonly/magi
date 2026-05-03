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
import { ComposerMentionPicker } from '@/components/chat/ComposerMentionPicker';
import { ComposerSlashPicker } from '@/components/chat/ComposerSlashPicker';
import { ToolArgsDialog } from '@/components/chat/ToolArgsDialog';
import { useChatComposerMentions } from '@/hooks/useChatComposerMentions';
import { useChatComposerCommands } from '@/hooks/useChatComposerCommands';
import { commandsApi, messagesApi, type CommandDescriptor } from '@/api';
import { DEFAULT_USER_ID } from '@/constants';
import { toast } from 'sonner';
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
  const reduceTimelineMotion = Boolean(shouldReduceMotion);
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
  const timelineScrollRef = useRef<HTMLDivElement>(null);
  const lastTimelineScrollKeyRef = useRef<string | null>(null);
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

  const composerTextareaRef = useRef<HTMLTextAreaElement | null>(null);

  const mentions = useChatComposerMentions({
    inputValue,
    setInputValue,
    textareaRef: composerTextareaRef,
    addMcpResourceDraft,
  });

  const [toolDialogDescriptor, setToolDialogDescriptor] = useState<CommandDescriptor | null>(null);

  const handleInternalCommand = React.useCallback(
    async (action: 'clear' | 'new-session' | 'cancel' | 'help') => {
      try {
        if (action === 'clear') {
          if (!currentSessionId) {
            toast.warning(t('chat.sessionRequired'));
            return;
          }
          await messagesApi.clearHistory(DEFAULT_USER_ID, currentSessionId);
          toast.success(t('chat.cleared'));
          return;
        }
        if (action === 'new-session') {
          const created = await messagesApi.createNewSession(DEFAULT_USER_ID);
          const newId = created?.session_id ?? null;
          if (newId) {
            setCurrentSessionId(String(newId));
            toast.success(t('chat.sessionSwitched'));
          }
          return;
        }
        if (action === 'cancel') {
          if (!pendingResponseTurnId) {
            toast.info(t('chat.commands.nothingToCancel', { defaultValue: 'No active run to cancel.' }));
            return;
          }
          await requestRunCancel(pendingResponseTurnId);
          return;
        }
        if (action === 'help') {
          const list = await commandsApi.list();
          const lines = list.map((c) => `/${c.name} — ${c.description}`).join('\n');
          toast.message('Commands', {
            description: lines || t('chat.commands.empty', { defaultValue: 'No matching commands.' }),
          });
        }
      } catch (exc: any) {
        toast.error(exc?.message ?? String(exc));
      }
    },
    [currentSessionId, pendingResponseTurnId, requestRunCancel, setCurrentSessionId, t],
  );

  const handleToolPicked = React.useCallback((descriptor: CommandDescriptor) => {
    setToolDialogDescriptor(descriptor);
  }, []);

  const handleRunTool = React.useCallback(
    async (descriptor: CommandDescriptor, args: Record<string, unknown>, invocationText: string) => {
      if (!currentSessionId) {
        throw new Error(t('chat.sessionRequired'));
      }
      const result = await commandsApi.run({
        user_id: DEFAULT_USER_ID,
        session_id: currentSessionId,
        tool_name: descriptor.name,
        arguments: args,
        invocation_text: invocationText,
        workspace_path: currentSession?.workspace_path ?? null,
      });
      if (!result.success && result.error) {
        toast.error(result.error);
      }
    },
    [currentSession?.workspace_path, currentSessionId, t],
  );

  const commands = useChatComposerCommands({
    setInputValue,
    textareaRef: composerTextareaRef,
    onPickInternal: handleInternalCommand,
    onPickTool: handleToolPicked,
  });

  const handleInputChangeWithMentions = React.useCallback(
    (next: string) => {
      setInputValue(next);
      mentions.onValueChange(next);
      commands.onValueChange(next);
    },
    [commands, mentions, setInputValue],
  );

  const handleKeyDownWithMentions = React.useCallback(
    (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (mentions.onKeyDown(event)) return;
      if (commands.onKeyDown(event)) return;
      handleComposerKeyDown(event);
    },
    [commands, handleComposerKeyDown, mentions],
  );

  useEffect(() => {
    clearPendingResponseTurnRef.current = clearPendingResponseTurn;
  }, [clearPendingResponseTurn]);

  const lastMessage = messages.length > 0 ? messages[messages.length - 1] : null;
  const lastReasoningFootprint = (lastMessage?.reasoning || [])
    .map((item) => `${item.source}:${item.content.length}`)
    .join('|');
  const lastToolFootprint = (lastMessage?.toolCalls || [])
    .map((item) => `${item.toolCallId || ''}:${item.status}:${item.toolArgsText?.length || 0}`)
    .join('|');
  const timelineScrollKey = [
    currentSessionId || 'none',
    messages.length,
    lastMessage?.id || 'empty',
    lastMessage?.messageId || '',
    lastMessage?.messageKind || '',
    lastMessage?.role || '',
    lastMessage?.kind || '',
    lastMessage?.content.length || 0,
    lastMessage?.streaming ? 'streaming' : 'settled',
    lastReasoningFootprint,
    lastToolFootprint,
  ].join('::');

  useEffect(() => {
    if (lastTimelineScrollKeyRef.current === timelineScrollKey) {
      return;
    }
    lastTimelineScrollKeyRef.current = timelineScrollKey;
    const timeline = timelineScrollRef.current;
    if (!timeline) {
      return;
    }
    if (typeof timeline.scrollTo === 'function') {
      timeline.scrollTo({
        top: timeline.scrollHeight,
        behavior: reduceTimelineMotion ? 'auto' : 'smooth',
      });
      return;
    }
    timeline.scrollTop = timeline.scrollHeight;
  }, [reduceTimelineMotion, timelineScrollKey]);

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
        shouldReduceMotion={reduceTimelineMotion}
        summaries={summaries}
        executionControlByTurnId={executionControlByTurnId}
        cancellingTurnIds={cancellingTurnIds}
        detachingTurnIds={detachingTurnIds}
        labelPopoverState={labelPopoverState}
        labelPopoverDraft={labelPopoverDraft}
        labelPopoverRef={labelPopoverRef}
        messageContextMenu={messageContextMenu}
        messageContextMenuRef={messageContextMenuRef}
        timelineRef={timelineScrollRef}
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
        textareaRef={composerTextareaRef}
        replyTarget={replyTarget}
        onCancelReply={() => setReplyTarget(null)}
        attachments={draftAttachments}
        onRemoveAttachment={removeDraftAttachment}
        inputValue={inputValue}
        onInputChange={handleInputChangeWithMentions}
        onCompositionStart={handleCompositionStart}
        onCompositionEnd={handleCompositionEnd}
        onKeyDown={handleKeyDownWithMentions}
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
        pickerSlot={
          <>
            <ComposerMentionPicker
              open={mentions.state.open}
              query={mentions.state.open ? mentions.state.query : ''}
              items={mentions.items}
              activeIndex={mentions.state.open ? mentions.state.activeIndex : 0}
              loading={mentions.loading}
              error={mentions.error}
              onSelect={mentions.select}
              onActiveIndexChange={mentions.setActiveIndex}
            />
            <ComposerSlashPicker
              open={commands.state.open}
              query={commands.state.open ? commands.state.query : ''}
              items={commands.items}
              activeIndex={commands.state.open ? commands.state.activeIndex : 0}
              loading={commands.loading}
              error={commands.error}
              onSelect={commands.select}
              onActiveIndexChange={commands.setActiveIndex}
            />
          </>
        }
      />

      <ToolArgsDialog
        open={toolDialogDescriptor !== null}
        descriptor={toolDialogDescriptor}
        onClose={() => setToolDialogDescriptor(null)}
        onRun={handleRunTool}
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
