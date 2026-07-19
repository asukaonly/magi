/**
 * Chat page - desktop-focused conversation workspace
 */
import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { motion, useReducedMotion } from 'framer-motion';
import { useChatComposerController } from '@/hooks/useChatComposerController';
import type { PendingAskAnswerPayload } from '@/hooks/useChatSendMessage';
import { useChatMessageOverlays } from '@/hooks/useChatMessageOverlays';
import { useChatMessageMutations } from '@/hooks/useChatMessageMutations';
import { useChatRealtimeEffects } from '@/hooks/useChatRealtimeEffects';
import { useChatSessionLifecycle } from '@/hooks/useChatSessionLifecycle';
import { useChatTraceDrawer } from '@/hooks/useChatTraceDrawer';
import { useChatExecutionControls } from '@/hooks/useChatExecutionControls';
import { useChatInlineSkillSend } from '@/hooks/useChatInlineSkillSend';
import { useChatDestructiveCleanupEvents } from '@/hooks/useChatDestructiveCleanupEvents';
import { useConversationStore } from '@/stores';
import { useContextUsageStore } from '@/stores/context-usage';
import { useDelegationsStore } from '@/stores/delegations-store';
import { ChatComposerPane } from '@/components/chat/ChatComposerPane';
import { ChatClearHistoryDialog } from '@/components/chat/ChatClearHistoryDialog';
import { SystemSuggestionTopBar } from '@/components/chat/SystemSuggestionTopBar';
import { SystemSuggestionSideCard } from '@/components/chat/SystemSuggestionSideCard';
import { useSystemSuggestions } from '@/hooks/useSystemSuggestions';
import type { SuggestionProposal } from '@/api/modules/systemSuggestions';
import { ComposerAskQuickReplies } from '@/components/chat/ComposerAskQuickReplies';
import { ChatPageOverlays } from '@/components/chat/ChatPageOverlays';
import { ChatTimelinePane } from '@/components/chat/ChatTimelinePane';
import { ComposerMentionPicker } from '@/components/chat/ComposerMentionPicker';
import { ComposerSlashPicker } from '@/components/chat/ComposerSlashPicker';
import { SkillArgsDialog } from '@/components/chat/SkillArgsDialog';
import { ToolArgsDialog } from '@/components/chat/ToolArgsDialog';
import { useChatComposerMentions } from '@/hooks/useChatComposerMentions';
import { useChatComposerCommands } from '@/hooks/useChatComposerCommands';
import { commandsApi, messagesApi, type CommandDescriptor, type SkillCommandDescriptor } from '@/api';
import { DEFAULT_USER_ID } from '@/constants';
import { dispatchAppEvent } from '@/constants/events';
import {
  clearPersistedChatRetriesForSession,
  clearPersistedChatRetriesForTurn,
} from '@/hooks/chatRetryLifecycle';
import {
  activateRealtimeChatSession,
  retireRealtimeChatDelegations,
  retireRealtimeChatHistory,
  retireRealtimeChatMessageIds,
  retireRealtimeChatTurns,
} from '@/realtime/chat-projection-retirement';
import { toast } from 'sonner';
import {
  buildSystemSuggestionTriggerText,
  type ChatTimelineMessage,
} from '@/domain/chat/state';
import {
  ChatTurnAdmissionCoordinator,
  type ExistingTurnAdmissionCheck,
  type RunWithChatTurnAdmission,
} from '@/hooks/chatTurnAdmission';
import {
  findLatestPendingResponseTurn,
  getNextRhythmPresentationAt,
  isTerminalRunState,
  messagesReadyForPresentation,
  resolvePendingTurnFromHistory,
} from '@/domain/chat/turn-completion';

const EMPTY_CHAT_MESSAGES: ChatTimelineMessage[] = [];

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
type PendingAskComposerState = {
  requestId: string;
  sessionId: string;
  messageId: string | null;
  question: string;
  options: string[];
  allowFreeText: boolean;
  expiresAtMs: number | null;
};

const numberOrNull = (value: unknown): number | null => {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
};

const normalizeAskOptions = (value: unknown): string[] => (
  Array.isArray(value)
    ? value.map((item) => String(item || '').trim()).filter(Boolean)
    : []
);

const resolvePendingAskComposerState = (
  messages: ChatTimelineMessage[],
  currentSessionId: string | null,
  nowMs: number,
): PendingAskComposerState | null => {
  const sessionId = String(currentSessionId || '').trim();
  if (!sessionId) {
    return null;
  }
  for (const message of [...messages].reverse()) {
    if (message.messageKind !== 'ask_request') {
      continue;
    }
    const payload = message.payload && typeof message.payload === 'object'
      ? message.payload as Record<string, unknown>
      : {};
    const payloadSessionId = String(payload.session_id || '').trim();
    if (payloadSessionId && payloadSessionId !== sessionId) {
      continue;
    }
    const status = String(payload.status || 'pending').trim().toLowerCase();
    if (status !== 'pending') {
      continue;
    }
    const expiresAtMs = numberOrNull(payload.expires_at_ms);
    if (expiresAtMs !== null && expiresAtMs <= nowMs) {
      continue;
    }
    const requestId = String(payload.ask_request_id || '').trim();
    if (!requestId) {
      continue;
    }
    const messageId = String(message.messageId || message.id || '').trim() || null;
    const question = String(payload.question || message.content || '').trim();
    return {
      requestId,
      sessionId,
      messageId,
      question,
      options: normalizeAskOptions(payload.options),
      allowFreeText: payload.allow_free_text !== false,
      expiresAtMs,
    };
  }
  return null;
};

export const ChatPage: React.FC = () => {
  const { t, i18n } = useTranslation('app');
  const shouldReduceMotion = useReducedMotion();
  const reduceTimelineMotion = Boolean(shouldReduceMotion);
  const currentSessionId = useConversationStore((state) => state.currentSessionId);
  const currentSession = useConversationStore((state) => (
    state.currentSessionId ? state.sessionsById[state.currentSessionId] || null : null
  ));
  const setCurrentSessionId = useConversationStore((state) => state.setCurrentSessionId);
  const storedMessages = useConversationStore((state) =>
    state.currentSessionId
      ? (state.messagesBySession[state.currentSessionId] || EMPTY_CHAT_MESSAGES)
      : EMPTY_CHAT_MESSAGES
  );
  const [presentationNowMs, setPresentationNowMs] = useState(() => Date.now());
  const [pendingAskNowMs, setPendingAskNowMs] = useState(() => Date.now());
  const nextRhythmPresentationAt = useMemo(
    () => getNextRhythmPresentationAt(storedMessages, presentationNowMs),
    [presentationNowMs, storedMessages],
  );
  const messages = useMemo(
    () => messagesReadyForPresentation(storedMessages, presentationNowMs),
    [presentationNowMs, storedMessages],
  );
  const appendPendingTurn = useConversationStore((state) => state.appendPendingTurn);
  const upsertMessage = useConversationStore((state) => state.upsertMessage);
  const applyMessageLabel = useConversationStore((state) => state.applyMessageLabel);
  const removeMessage = useConversationStore((state) => state.removeMessage);
  const clearSessionHistory = useConversationStore((state) => state.clearSessionHistory);
  const resetConversation = useConversationStore((state) => state.reset);

  const [historyImagePreview, setHistoryImagePreview] = useState<HistoryImagePreview | null>(null);
  const timelineScrollRef = useRef<HTMLDivElement>(null);
  const lastTimelineScrollKeyRef = useRef<string | null>(null);

  useEffect(() => {
    setPresentationNowMs(Date.now());
  }, [currentSessionId]);

  useEffect(() => {
    if (nextRhythmPresentationAt === null) {
      return;
    }
    const delayMs = Math.max(1, nextRhythmPresentationAt - Date.now() + 1);
    const timer = window.setTimeout(() => {
      setPresentationNowMs(Date.now());
    }, delayMs);
    return () => window.clearTimeout(timer);
  }, [nextRhythmPresentationAt]);

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
    settleTurnFromHistory,
  } = useChatExecutionControls({
    currentSessionId,
  });

  const {
    aiName,
    aiAvatar,
    assistantPersonas,
    coreModelSupportsVision,
    coreModelContextWindow,
    allowInterjection,
    interjectionSettingLoaded,
    clearSessionLifecycleState,
    ensureSessionHistoryReady,
    reconcileTurnFromHistory,
  } = useChatSessionLifecycle({
    currentSessionId,
    upsertMessage,
    removeMessage,
    translate: t,
  });

  const activePendingAsk = React.useMemo(
    () => resolvePendingAskComposerState(
      messages,
      currentSessionId,
      pendingAskNowMs,
    ),
    [currentSessionId, messages, pendingAskNowMs],
  );
  useEffect(() => {
    setPendingAskNowMs(Date.now());
  }, [currentSessionId, messages]);
  useEffect(() => {
    const expiresAtMs = activePendingAsk?.expiresAtMs;
    if (expiresAtMs === null || expiresAtMs === undefined) {
      return undefined;
    }
    const timeout = window.setTimeout(
      () => setPendingAskNowMs(Date.now()),
      Math.max(1, expiresAtMs - Date.now() + 1),
    );
    return () => window.clearTimeout(timeout);
  }, [activePendingAsk?.expiresAtMs]);

  const handleAskAnswerSent = React.useCallback((answerPayload: PendingAskAnswerPayload) => {
    const state = useConversationStore.getState();
    const sessionMessages = state.messagesBySession[answerPayload.sessionId] || [];
    const askMessage = sessionMessages.find((message) => {
      const messageId = String(message.messageId || message.id || '').trim();
      return messageId === answerPayload.messageId;
    }) || null;
    const askMessageId = answerPayload.messageId || `ask:${answerPayload.requestId}`;
    const askQuestion = String(askMessage?.content || answerPayload.question || '').trim();
    const askPayload = askMessage?.payload && typeof askMessage.payload === 'object'
      ? askMessage.payload as Record<string, unknown>
      : {};

    upsertMessage(answerPayload.sessionId, askMessage ? {
      ...askMessage,
      payload: {
        ...askPayload,
        status: 'answered',
        answer: answerPayload.answer,
        answered_at_ms: answerPayload.timestamp,
      },
    } : {
      id: askMessageId,
      messageId: askMessageId,
      role: 'assistant',
      kind: 'assistant',
      messageKind: 'ask_request',
      content: askQuestion,
      timestamp: Math.max(0, answerPayload.timestamp - 1),
      payload: {
        ask_request_id: answerPayload.requestId,
        session_id: answerPayload.sessionId,
        status: 'answered',
        question: askQuestion,
        answer: answerPayload.answer,
        answered_at_ms: answerPayload.timestamp,
      },
    });

    upsertMessage(answerPayload.sessionId, {
      id: `ask-response:${answerPayload.requestId}`,
      messageId: `ask-response:${answerPayload.requestId}`,
      role: 'user',
      kind: 'user',
      messageKind: 'ask_response',
      content: answerPayload.answer,
      timestamp: answerPayload.timestamp,
      replyTo: askQuestion ? {
        messageId: askMessageId,
        role: 'assistant',
        messageKind: 'ask_request',
        contentExcerpt: askQuestion.length > 140 ? `${askQuestion.slice(0, 137)}...` : askQuestion,
      } : null,
      payload: {
        ask_request_id: answerPayload.requestId,
        session_id: answerPayload.sessionId,
        answer: answerPayload.answer,
      },
      traceDisplayMode: null,
      allowTraceCollapse: false,
    });
  }, [upsertMessage]);


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

  const inlineSkillReconciliationRef = useRef<(
    sessionId: string,
    excludedRetryKey?: string,
  ) => Promise<ExistingTurnAdmissionCheck>>(async () => ({
    kind: 'unconfirmed',
  }));
  const reconcileInlineSkillBeforeComposerTurn = React.useCallback((
    sessionId: string,
    excludedRetryKey?: string,
  ) => inlineSkillReconciliationRef.current(
    sessionId,
    excludedRetryKey,
  ), []);
  const turnAdmissionCoordinatorRef = useRef<ChatTurnAdmissionCoordinator | null>(
    null,
  );
  if (!turnAdmissionCoordinatorRef.current) {
    turnAdmissionCoordinatorRef.current = new ChatTurnAdmissionCoordinator();
  }
  const ensureAdmissionHistoryReady = React.useCallback(async (
    sessionId: string,
  ): Promise<boolean> => {
    const historyState = await ensureSessionHistoryReady(sessionId);
    if (!historyState.loaded) {
      return false;
    }
    const pendingTurnId = findLatestPendingResponseTurn(
      historyState.messages,
      Date.now(),
    );
    if (pendingTurnId) {
      turnAdmissionCoordinatorRef.current!.markPendingTurn(
        sessionId,
        pendingTurnId,
      );
      return true;
    }
    const trackedTurnId = turnAdmissionCoordinatorRef.current!
      .getPendingTurnId(sessionId);
    if (
      trackedTurnId
      && resolvePendingTurnFromHistory(
        historyState.messages,
        trackedTurnId,
        Date.now(),
        { resolveMissing: false },
      ).resolved
    ) {
      turnAdmissionCoordinatorRef.current!.clearPendingTurn(
        sessionId,
        trackedTurnId,
      );
    }
    return true;
  }, [ensureSessionHistoryReady]);
  const runWithTurnAdmission = React.useCallback<RunWithChatTurnAdmission>(
    (sessionId, kind, operation) => (
      turnAdmissionCoordinatorRef.current!.run(
        sessionId,
        kind,
        ensureAdmissionHistoryReady,
        operation,
      )
    ),
    [ensureAdmissionHistoryReady],
  );
  const markAdmissionPendingTurn = React.useCallback((
    sessionId: string,
    turnId: string,
  ) => {
    turnAdmissionCoordinatorRef.current!.markPendingTurn(
      sessionId,
      turnId,
    );
  }, []);
  const clearAdmissionPendingTurn = React.useCallback((
    sessionId: string,
    turnId?: string,
  ) => {
    turnAdmissionCoordinatorRef.current!.clearPendingTurn(
      sessionId,
      turnId,
    );
  }, []);
  useLayoutEffect(() => {
    turnAdmissionCoordinatorRef.current!.setInterjectionPolicy({
      loaded: interjectionSettingLoaded,
      allow: allowInterjection,
    });
  }, [allowInterjection, interjectionSettingLoaded]);
  const {
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
    trackPendingResponseTurn,
    recallFeedbackDraft,
    removeDraftAttachment,
    replyTarget,
    sendingMessage,
    setAttachmentMenuOpen,
    setInputValue,
    setReplyTarget,
    startRecallFeedback,
    cancelRecallFeedback,
    convertRecallFeedbackToNormal,
    waitingForReply,
  } = useChatComposerController({
    currentSessionId,
    currentWorkspacePath: currentSession?.workspace_path,
    allowInterjection,
    coreModelSupportsVision,
    pendingAsk: activePendingAsk,
    appendPendingTurn,
    removePendingMessage: removeMessage,
    setCurrentSessionId,
    onAskAnswered: handleAskAnswerSent,
    requestRunCancel,
    markAdmissionPendingTurn,
    clearAdmissionPendingTurn,
    reconcileExternalTurnBeforeSend:
      reconcileInlineSkillBeforeComposerTurn,
    runWithTurnAdmission,
    translate: t,
  });

  const {
    clearAllRetries: clearAllInlineSkillRetries,
    clearRetryForTurn: clearInlineSkillRetryForTurn,
    clearRetriesForSession: clearInlineSkillRetriesForSession,
    reconcileBeforeComposerTurn:
      reconcileInlineSkillOperationsBeforeComposerTurn,
    runSkillExpansion,
  } = useChatInlineSkillSend({
    currentSessionId,
    workspacePath: currentSession?.workspace_path,
    allowInterjection,
    hasPendingAsk: Boolean(activePendingAsk),
    appendPendingTurn,
    removeMessage,
    trackPendingResponseTurn,
    clearPendingResponseTurn,
    reconcilePendingSendBeforeExternalTurn,
    runWithTurnAdmission,
    translate: t,
  });
  useLayoutEffect(() => {
    inlineSkillReconciliationRef.current =
      reconcileInlineSkillOperationsBeforeComposerTurn;
  }, [reconcileInlineSkillOperationsBeforeComposerTurn]);

  const getCurrentSessionId = React.useCallback(
    () => useConversationStore.getState().currentSessionId,
    [],
  );
  const clearAllAdmissionPendingTurns = React.useCallback(() => {
    turnAdmissionCoordinatorRef.current!.clearAllPendingTurns();
  }, []);
  useChatDestructiveCleanupEvents({
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
  });

  const recoveredPendingResponseTurnId = useMemo(() => (
    allowInterjection
      ? null
      : findLatestPendingResponseTurn(storedMessages, presentationNowMs)
  ), [allowInterjection, presentationNowMs, storedMessages]);

  useLayoutEffect(() => {
    if (!currentSessionId || !recoveredPendingResponseTurnId) {
      return;
    }
    trackPendingResponseTurn(currentSessionId, recoveredPendingResponseTurnId);
  }, [
    currentSessionId,
    recoveredPendingResponseTurnId,
    trackPendingResponseTurn,
  ]);

  const pendingTurnHistoryResolution = useMemo(() => (
    currentSessionId && pendingResponseTurnId
      ? resolvePendingTurnFromHistory(
        storedMessages,
        pendingResponseTurnId,
        presentationNowMs,
        { resolveMissing: false },
      )
      : null
  ), [
    currentSessionId,
    pendingResponseTurnId,
    presentationNowMs,
    storedMessages,
  ]);

  useEffect(() => {
    if (
      !currentSessionId
      || !pendingResponseTurnId
      || !pendingTurnHistoryResolution?.resolved
    ) {
      return;
    }
    clearPendingResponseTurn({
      sessionId: currentSessionId,
      turnId: pendingResponseTurnId,
    });
  }, [
    clearPendingResponseTurn,
    currentSessionId,
    pendingResponseTurnId,
    pendingTurnHistoryResolution,
  ]);

  const composerTextareaRef = useRef<HTMLTextAreaElement | null>(null);

  // System suggestions: fire after each completed user→assistant turn.
  const triggerText = useMemo(() => buildSystemSuggestionTriggerText(messages), [messages]);
  const suggestionLocale: 'zh' | 'en' = (i18n.language === 'zh-CN' || i18n.language === 'zh') ? 'zh' : 'en';
  const { proposals: systemSuggestions, dismiss: dismissSystemSuggestion } = useSystemSuggestions({
    triggerText,
    locale: suggestionLocale,
    sessionId: currentSessionId ?? undefined,
  });
  const [sideCardProposal, setSideCardProposal] = useState<SuggestionProposal | null>(null);
  const topBarProposal = systemSuggestions.length > 0 ? systemSuggestions[0] : null;

  const mentions = useChatComposerMentions({
    inputValue,
    setInputValue,
    textareaRef: composerTextareaRef,
    addMcpResourceDraft,
  });

  const [toolDialogDescriptor, setToolDialogDescriptor] = useState<CommandDescriptor | null>(null);
  const [skillDialogDescriptor, setSkillDialogDescriptor] = useState<SkillCommandDescriptor | null>(null);
  const [clearHistorySessionId, setClearHistorySessionId] = useState<string | null>(null);
  const [clearHistoryLoading, setClearHistoryLoading] = useState(false);
  const [clearHistoryError, setClearHistoryError] = useState<string | null>(null);
  const clearHistoryInFlightRef = useRef(false);

  const handleConfirmClearHistory = React.useCallback(async () => {
    const targetSessionId = String(clearHistorySessionId || '').trim();
    if (!targetSessionId || clearHistoryInFlightRef.current) return;

    clearHistoryInFlightRef.current = true;
    setClearHistoryLoading(true);
    setClearHistoryError(null);
    let cleanupPending = false;
    try {
      const admission = await turnAdmissionCoordinatorRef.current!.runExclusive(
        targetSessionId,
        async () => {
          const result = await messagesApi.clearHistory(
            DEFAULT_USER_ID,
            targetSessionId,
          );
          if (!result.success) {
            throw new Error('Clear history request was not completed');
          }
          if (String(result.session_id || '').trim() !== targetSessionId) {
            throw new Error('Clear history request returned another session');
          }
          cleanupPending = result.cleanup_pending;
          retireRealtimeChatMessageIds(
            targetSessionId,
            result.cleared_message_ids,
          );
          retireRealtimeChatTurns(
            targetSessionId,
            result.cleared_turn_ids,
          );
          retireRealtimeChatHistory(
            targetSessionId,
            useConversationStore.getState().messagesBySession[targetSessionId] || [],
          );
          useContextUsageStore.getState().clear(targetSessionId);
          retireRealtimeChatDelegations(
            targetSessionId,
            Object.keys(
              useDelegationsStore.getState().delegationsBySession[targetSessionId]
              || {},
            ),
          );
          useDelegationsStore.getState().clearSession(targetSessionId);
          clearSessionHistory(targetSessionId);
          clearSessionLifecycleState(targetSessionId);
          clearPersistedChatRetriesForSession(targetSessionId);
          clearRetryableSendsForSession(targetSessionId);
          clearInlineSkillRetriesForSession(targetSessionId);
          clearPendingResponseTurn({ sessionId: targetSessionId });
          if (currentSessionId === targetSessionId) {
            clearHistoryBoundDraftState();
            resetTraceDrawer();
          }
          dispatchAppEvent.chatHistoryCleared(targetSessionId);
        },
      );
      if (!admission.entered) {
        throw new Error('Clear history admission was not completed');
      }
      setClearHistorySessionId(null);
      if (cleanupPending) {
        toast.warning(t('chat.clearHistoryDialog.cleanupPending'));
      } else {
        toast.success(t('chat.clearHistoryDialog.success'));
      }
    } catch {
      const message = t('chat.clearHistoryDialog.error');
      setClearHistoryError(message);
      toast.error(message);
    } finally {
      clearHistoryInFlightRef.current = false;
      setClearHistoryLoading(false);
    }
  }, [
    clearHistorySessionId,
    clearPendingResponseTurn,
    clearInlineSkillRetriesForSession,
    clearRetryableSendsForSession,
    clearSessionLifecycleState,
    clearSessionHistory,
    clearHistoryBoundDraftState,
    currentSessionId,
    resetTraceDrawer,
    t,
  ]);

  const handleInternalCommand = React.useCallback(
    async (action: 'clear' | 'new-session' | 'cancel' | 'help') => {
      try {
        if (action === 'clear') {
          if (!currentSessionId) {
            toast.warning(t('chat.sessionRequired'));
            return;
          }
          setClearHistoryError(null);
          setClearHistorySessionId(currentSessionId);
          return;
        }
        if (action === 'new-session') {
          const created = await messagesApi.createNewSession(DEFAULT_USER_ID);
          const newId = created?.session_id ?? null;
          if (newId) {
            activateRealtimeChatSession(newId);
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
          const outcome = await requestRunCancel(pendingResponseTurnId);
          if (outcome === 'settled') {
            clearPendingResponseTurn({
              sessionId: currentSessionId || undefined,
              turnId: pendingResponseTurnId,
            });
          }
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
    [
      clearPendingResponseTurn,
      currentSessionId,
      pendingResponseTurnId,
      requestRunCancel,
      setCurrentSessionId,
      t,
    ],
  );

  const handleToolPicked = React.useCallback((descriptor: CommandDescriptor) => {
    setToolDialogDescriptor(descriptor);
  }, []);

  const handleSkillPicked = React.useCallback(
    async (descriptor: SkillCommandDescriptor) => {
      // If the skill declares no argument_hint, expand immediately and submit.
      // Otherwise open a small dialog so the user can fill them in.
      if (!descriptor.argument_hint) {
        try {
          const outcome = await runSkillExpansion(descriptor, '');
          if (outcome.kind === 'not_sent') {
            toast.warning(outcome.message);
          }
        } catch (exc: any) {
          toast.error(exc?.message ?? String(exc));
        }
      } else {
        setSkillDialogDescriptor(descriptor);
      }
    },
    [runSkillExpansion],
  );

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
    allowInlineSkills: !activePendingAsk,
    onPickInternal: handleInternalCommand,
    onPickTool: handleToolPicked,
    onPickSkill: handleSkillPicked,
  });

  const handleInputChangeWithMentions = React.useCallback(
    (next: string) => {
      setInputValue(next);
      if (recallFeedbackDraft) {
        return;
      }
      mentions.onValueChange(next);
      commands.onValueChange(next);
    },
    [commands, mentions, recallFeedbackDraft, setInputValue],
  );

  const handleAskQuickReplyPicked = React.useCallback(
    (value: string) => {
      const option = String(value || '').trim();
      if (!option) return;
      handleInputChangeWithMentions(option);
      window.requestAnimationFrame(() => {
        composerTextareaRef.current?.focus();
      });
    },
    [handleInputChangeWithMentions],
  );

  const handleKeyDownWithMentions = React.useCallback(
    (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (recallFeedbackDraft) {
        handleComposerKeyDown(event);
        return;
      }
      if (mentions.onKeyDown(event)) return;
      if (commands.onKeyDown(event)) return;
      handleComposerKeyDown(event);
    },
    [commands, handleComposerKeyDown, mentions, recallFeedbackDraft],
  );

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
    lastMessage?.content?.length || 0,
    lastMessage?.streaming ? 'streaming' : 'settled',
    lastReasoningFootprint,
    lastToolFootprint,
  ].join('::');

  const wasAtTimelineBottomRef = useRef(true);

  useEffect(() => {
    const timeline = timelineScrollRef.current;
    if (!timeline) return;
    const STICKY_THRESHOLD = 32;
    const updateStickiness = () => {
      const distanceFromBottom = timeline.scrollHeight - timeline.scrollTop - timeline.clientHeight;
      wasAtTimelineBottomRef.current = distanceFromBottom <= STICKY_THRESHOLD;
    };
    updateStickiness();
    timeline.addEventListener('scroll', updateStickiness, { passive: true });
    return () => {
      timeline.removeEventListener('scroll', updateStickiness);
    };
  }, []);

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
    } else {
      timeline.scrollTop = timeline.scrollHeight;
    }
    wasAtTimelineBottomRef.current = true;
  }, [reduceTimelineMotion, timelineScrollKey]);

  useEffect(() => {
    const timeline = timelineScrollRef.current;
    if (!timeline || typeof ResizeObserver === 'undefined') return;
    let lastClientHeight = timeline.clientHeight;
    const observer = new ResizeObserver(() => {
      const nextClientHeight = timeline.clientHeight;
      const heightShrank = nextClientHeight < lastClientHeight;
      lastClientHeight = nextClientHeight;
      if (!heightShrank) return;
      if (!wasAtTimelineBottomRef.current) return;
      timeline.scrollTop = timeline.scrollHeight;
    });
    observer.observe(timeline);
    return () => {
      observer.disconnect();
    };
  }, []);

  useLayoutEffect(() => {
    const timeline = timelineScrollRef.current;
    if (!timeline) return;
    if (!wasAtTimelineBottomRef.current) return;
    timeline.scrollTop = timeline.scrollHeight;
  }, [inputValue]);

  useChatRealtimeEffects({
    allowInterjection,
    pendingResponseTurnsBySession,
    refreshVisibleTrace,
    handleTurnExecutionControlEvent,
    reconcilePendingResponseTurn: reconcileTurnFromHistory,
    settleTurnFromHistory,
    clearPendingResponseTurn,
  });

  const clearRetryableTurn = React.useCallback((
    sessionId: string,
    turnId: string,
  ) => {
    clearPersistedChatRetriesForTurn(sessionId, turnId);
    clearRetryableSendForTurn(sessionId, turnId);
    clearInlineSkillRetryForTurn(sessionId, turnId);
  }, [clearInlineSkillRetryForTurn, clearRetryableSendForTurn]);

  const {
    applyLabelToMessage,
    handleDeleteMessage,
    handleCopyMessage,
  } = useChatMessageMutations({
    currentSessionId,
    activeLabelMessageId: labelPopoverState?.messageId || null,
    applyMessageLabel,
    removeMessage,
    clearRetryableTurn,
    clearPendingResponseTurn,
    clearComposerReferenceToMessage,
    closeLabelPopover,
    closeMessageContextMenu,
    normalizeCopyText: toPlainText,
    translate: t,
  });

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.15 }}
      className="relative flex h-full min-h-0 flex-col bg-[hsl(var(--app-chrome-surface))] px-4 pb-4 pt-3"
    >
      <SystemSuggestionTopBar
        proposal={topBarProposal}
        onOpen={(p) => setSideCardProposal(p)}
        onDismiss={(dedupeKey, kind) => {
          // Persist the localized rationale the user saw so the bell's restore
          // list shows the same text (not a humanized English key).
          const title = topBarProposal
            ? topBarProposal.rationale[suggestionLocale] ?? topBarProposal.rationale.en
            : undefined;
          void dismissSystemSuggestion(dedupeKey, kind, title);
        }}
      />
      {sideCardProposal && (
        <SystemSuggestionSideCard
          proposal={sideCardProposal}
          onClose={() => setSideCardProposal(null)}
          onDecline={(dedupeKey) => {
            const title =
              sideCardProposal.rationale[suggestionLocale] ?? sideCardProposal.rationale.en;
            void dismissSystemSuggestion(dedupeKey, 'explicit', title);
            setSideCardProposal(null);
          }}
          onActivated={() => setSideCardProposal(null)}
        />
      )}
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
        waitingForReply={waitingForReply}
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
        recallFeedbackDisabled={Boolean(activePendingAsk)}
        onStartRecallFeedback={startRecallFeedback}
      />

      <ChatComposerPane
        composerRef={composerRef}
        textareaRef={composerTextareaRef}
        replyTarget={recallFeedbackDraft || activePendingAsk ? null : replyTarget}
        onCancelReply={() => setReplyTarget(null)}
        attachments={recallFeedbackDraft ? [] : draftAttachments}
        onRemoveAttachment={removeDraftAttachment}
        inputValue={inputValue}
        onInputChange={handleInputChangeWithMentions}
        onCompositionStart={handleCompositionStart}
        onCompositionEnd={handleCompositionEnd}
        onKeyDown={handleKeyDownWithMentions}
        onPaste={handleComposerPaste}
        answeringAsk={Boolean(activePendingAsk)}
        choiceOnlyAsk={Boolean(activePendingAsk && !activePendingAsk.allowFreeText)}
        validChoiceSelected={Boolean(
          activePendingAsk
          && activePendingAsk.options.includes(inputValue.trim())
        )}
        waitingForReply={waitingForReply}
        attachmentMenuOpen={attachmentMenuOpen}
        coreModelSupportsVision={coreModelSupportsVision}
        coreModelContextWindow={coreModelContextWindow}
        onToggleAttachmentMenu={() => setAttachmentMenuOpen((open) => !open)}
        onPickImage={() => imageInputRef.current?.click()}
        onPickFile={() => fileInputRef.current?.click()}
        sessionId={currentSessionId}
        sendingMessage={sendingMessage}
        stoppingReply={Boolean(
          pendingResponseTurnId
          && (
            cancellingTurnIds.includes(pendingResponseTurnId)
            || pendingTurnHistoryResolution?.safeToCommitHistory
            || isTerminalRunState(
              executionControlByTurnId[pendingResponseTurnId]?.state,
            )
          )
        )}
        onPrimaryAction={handleComposerPrimaryAction}
        recallFeedbackDraft={recallFeedbackDraft}
        onCancelRecallFeedback={cancelRecallFeedback}
        onConvertRecallFeedbackToNormal={convertRecallFeedbackToNormal}
        imageInputRef={imageInputRef}
        fileInputRef={fileInputRef}
        onAttachmentInputChange={handleAttachmentInputChange}
        askAnswerSlot={activePendingAsk ? (
          <ComposerAskQuickReplies
            options={activePendingAsk.options}
            allowFreeText={activePendingAsk.allowFreeText}
            expiresAtMs={activePendingAsk.expiresAtMs}
            onPick={handleAskQuickReplyPicked}
          />
        ) : undefined}
        pickerSlot={recallFeedbackDraft || activePendingAsk ? undefined : (
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
        )}
      />

      <ToolArgsDialog
        open={toolDialogDescriptor !== null}
        descriptor={toolDialogDescriptor}
        onClose={() => setToolDialogDescriptor(null)}
        onRun={handleRunTool}
      />

      <SkillArgsDialog
        open={skillDialogDescriptor !== null}
        descriptor={skillDialogDescriptor}
        onClose={() => setSkillDialogDescriptor(null)}
        onSubmit={runSkillExpansion}
      />

      <ChatClearHistoryDialog
        open={clearHistorySessionId !== null}
        loading={clearHistoryLoading}
        error={clearHistoryError}
        onOpenChange={(open) => {
          if (!open) {
            setClearHistorySessionId(null);
            setClearHistoryError(null);
          }
        }}
        onConfirm={() => void handleConfirmClearHistory()}
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
