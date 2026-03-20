/**
 * useChat hook - Manages chat state and WebSocket communication.
 *
 * This hook encapsulates all chat-related business logic including:
 * - Message sending and receiving
 * - Session management
 * - Execution trace handling
 * - AI personality info
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';
import { messagesApi } from '@/api';
import { useRealtime } from '@/realtime/provider';
import {
  useChatTraceStore,
  useConversationStore,
  useRealtimeStore,
} from '@/stores';
import {
  APP_EVENTS,
  DEFAULT_USER_ID,
  WS_MESSAGE_TYPES,
  dispatchAppEvent,
} from '@/constants';
import {
  normalizeTraceSummary,
  normalizeTraceSnapshot,
  createClientTurnId,
} from '@/domain/chat/normalizers';
import type {
  RealtimeMessage,
  ChatTimelineMessage,
  NormalizedTraceSnapshot,
  ExecutionTraceSummary,
} from '@/types';
import type { PersonalityInfo } from '@/domain/chat';

// ============================================================================
// Types
// ============================================================================

export interface UseChatOptions {
  userId?: string;
}

export interface UseChatReturn {
  // State
  messages: ChatTimelineMessage[];
  connected: boolean;
  currentSessionId: string | null;
  aiName: string;
  aiAvatar: string;

  // Actions
  sendMessage: (content: string) => void;
  resetChat: () => void;

  // Trace drawer
  drawerOpen: boolean;
  activeTurnId: string | null;
  loadingTrace: boolean;
  openTraceDrawer: (turnId: string) => void;
  closeTraceDrawer: () => void;
  activeSnapshot: NormalizedTraceSnapshot | null;
  activeSummary: ExecutionTraceSummary | undefined;

  // Utilities
  getTraceSummary: (turnId: string) => ExecutionTraceSummary | undefined;
  canOpenTrace: (message: ChatTimelineMessage) => boolean;
}

// ============================================================================
// Hook Implementation
// ============================================================================

export function useChat(options: UseChatOptions = {}): UseChatReturn {
  const { userId = DEFAULT_USER_ID } = options;
  const { t } = useTranslation('app');

  // Realtime connection
  const { send, subscribe } = useRealtime();
  const connected = useRealtimeStore((state) => state.connected);

  // Conversation store
  const currentSessionId = useConversationStore((state) => state.currentSessionId);
  const setCurrentSessionId = useConversationStore((state) => state.setCurrentSessionId);
  const messages = useConversationStore((state) =>
    currentSessionId ? state.messagesBySession[currentSessionId] || [] : []
  );
  const appendPendingTurn = useConversationStore((state) => state.appendPendingTurn);
  const receiveAgentResponse = useConversationStore((state) => state.receiveAgentResponse);
  const applyConversationTraceSummary = useConversationStore((state) => state.upsertTraceSummary);
  const resetConversation = useConversationStore((state) => state.reset);

  // Trace store
  const drawerOpen = useChatTraceStore((state) => state.drawerOpen);
  const activeTurnId = useChatTraceStore((state) => state.activeTurnId);
  const summaries = useChatTraceStore((state) => state.summaries);
  const snapshots = useChatTraceStore((state) => state.snapshots);
  const upsertSummary = useChatTraceStore((state) => state.upsertSummary);
  const setSnapshot = useChatTraceStore((state) => state.setSnapshot);
  const openDrawer = useChatTraceStore((state) => state.openDrawer);
  const closeDrawer = useChatTraceStore((state) => state.closeDrawer);
  const resetTraceStore = useChatTraceStore((state) => state.reset);

  // Local state
  const [aiName, setAiName] = useState<string>('AI');
  const [aiAvatar, setAiAvatar] = useState<string>('');
  const [loadingTrace, setLoadingTrace] = useState(false);

  // Refs
  const lastHistoryRequestRef = useRef<string | null>(null);

  // ============================================================================
  // Trace Loading
  // ============================================================================

  const loadTrace = useCallback(
    async (turnId: string) => {
      if (!currentSessionId || !turnId) return;

      setLoadingTrace(true);
      try {
        const result = await messagesApi.getTrace(userId, currentSessionId, turnId);
        if (result.trace) {
          const snapshot = normalizeTraceSnapshot(result.trace);
          if (snapshot) {
            setSnapshot(result.trace);
          }
        }
      } catch {
        toast.error(t('chat.trace.loadFailed'));
      } finally {
        setLoadingTrace(false);
      }
    },
    [currentSessionId, setSnapshot, t, userId]
  );

  // ============================================================================
  // WebSocket Message Handlers
  // ============================================================================

  const requestHistory = useCallback(
    (sessionId: string) => {
      if (!sessionId) return;
      lastHistoryRequestRef.current = sessionId;
      send({ type: WS_MESSAGE_TYPES.GET_HISTORY, session_id: sessionId });
    },
    [send]
  );

  const handleExecutionTraceUpdate = useCallback(
    (payload: unknown) => {
      const data = payload as Record<string, unknown>;
      const sessionId = String(data?.session_id || currentSessionId || '').trim();
      const turnId = String(data?.turn_id || '').trim();
      const summary = normalizeTraceSummary(data?.trace_summary);

      if (!sessionId || !turnId || !summary) return;

      upsertSummary({
        turn_id: summary.turnId,
        mode: summary.mode,
        status: summary.status,
        headline: summary.headline,
        active_steps: summary.activeSteps,
        completed_steps: summary.completedSteps,
        failed_steps: summary.failedSteps,
        duration_seconds: summary.durationSeconds,
        trace_available: summary.traceAvailable,
        orchestration_id: summary.orchestrationId || null,
      });

      applyConversationTraceSummary(sessionId, turnId, summary);

      if (drawerOpen && activeTurnId === turnId) {
        void loadTrace(turnId);
      }
    },
    [activeTurnId, applyConversationTraceSummary, currentSessionId, drawerOpen, loadTrace, upsertSummary]
  );

  const handleAgentResponseEvent = useCallback(
    (payload: unknown) => {
      const data = payload as Record<string, unknown>;
      const sessionId = String(data?.session_id || currentSessionId || '').trim();
      const turnId = String(data?.turn_id || '').trim();
      const summary = normalizeTraceSummary(data?.trace_summary);

      if (sessionId) {
        receiveAgentResponse({
          sessionId,
          content: String(data?.content || ''),
          timestamp: Number(data?.timestamp || Date.now() / 1000) * 1000,
          turnId: turnId || undefined,
          traceSummary: summary,
          traceAvailable: Boolean(data?.trace_available || summary?.traceAvailable),
        });
      }

      if (summary) {
        upsertSummary({
          turn_id: summary.turnId,
          mode: summary.mode,
          status: summary.status,
          headline: summary.headline,
          active_steps: summary.activeSteps,
          completed_steps: summary.completedSteps,
          failed_steps: summary.failedSteps,
          duration_seconds: summary.durationSeconds,
          trace_available: summary.traceAvailable,
          orchestration_id: summary.orchestrationId || null,
        });
      }

      dispatchAppEvent.sessionSync();

      if (drawerOpen && activeTurnId === turnId) {
        void loadTrace(turnId);
      }
    },
    [activeTurnId, currentSessionId, drawerOpen, loadTrace, receiveAgentResponse, upsertSummary]
  );

  const handleWSMessage = useCallback(
    (message: RealtimeMessage) => {
      switch (message.type) {
        case WS_MESSAGE_TYPES.SUBSCRIBED:
          if (currentSessionId) {
            requestHistory(currentSessionId);
          }
          return;

        case WS_MESSAGE_TYPES.HISTORY:
          if (message.data?.session_id) {
            send({ type: WS_MESSAGE_TYPES.GET_PERSONALITY });
          }
          return;

        case WS_MESSAGE_TYPES.PERSONALITY_INFO:
          if (message.data) {
            const info = message.data as PersonalityInfo;
            setAiName(info.name || 'AI');
            setAiAvatar(info.avatar || '');

            if (currentSessionId && messages.length === 0 && info.greeting) {
              receiveAgentResponse({
                sessionId: currentSessionId,
                content: String(info.greeting),
                timestamp: Date.now(),
              });
            }
          }
          return;

        case WS_MESSAGE_TYPES.MESSAGE_SENT:
          if (message.data?.session_id) {
            setCurrentSessionId(String(message.data.session_id));
          }
          dispatchAppEvent.sessionSync();
          return;

        case WS_MESSAGE_TYPES.ERROR:
          toast.error(message.message || 'WebSocket error');
          return;

        default:
          break;
      }

      // Handle event-based messages (legacy compatibility)
      const eventName = (message as { event?: string }).event || message.type;

      if (eventName === WS_MESSAGE_TYPES.EXECUTION_TRACE_UPDATE) {
        handleExecutionTraceUpdate((message as { data?: unknown }).data);
        return;
      }

      if (eventName === WS_MESSAGE_TYPES.AGENT_RESPONSE) {
        handleAgentResponseEvent((message as { data?: unknown }).data);
      }
    },
    [
      currentSessionId,
      handleAgentResponseEvent,
      handleExecutionTraceUpdate,
      messages.length,
      receiveAgentResponse,
      requestHistory,
      send,
      setCurrentSessionId,
      userId,
    ]
  );

  // Subscribe to WebSocket messages
  useEffect(() => {
    return subscribe(handleWSMessage);
  }, [handleWSMessage, subscribe]);

  // Request history on connection/session change
  useEffect(() => {
    if (!connected || !currentSessionId) return;
    if (lastHistoryRequestRef.current === currentSessionId) return;

    requestHistory(currentSessionId);
    send({ type: WS_MESSAGE_TYPES.GET_PERSONALITY });
  }, [connected, currentSessionId, requestHistory, send]);

  // Handle memory cleared event
  useEffect(() => {
    const handleMemoryCleared = () => {
      setCurrentSessionId(null);
      lastHistoryRequestRef.current = null;
      resetTraceStore();
      resetConversation();
      dispatchAppEvent.sessionSync();
    };

    window.addEventListener(APP_EVENTS.MEMORY_CLEARED, handleMemoryCleared);
    return () => window.removeEventListener(APP_EVENTS.MEMORY_CLEARED, handleMemoryCleared);
  }, [connected, resetConversation, resetTraceStore, send, setCurrentSessionId]);

  // ============================================================================
  // Actions
  // ============================================================================

  const sendMessage = useCallback(
    (content: string) => {
      if (!content.trim()) {
        toast.warning(t('chat.emptyInput'));
        return;
      }

      if (!connected) {
        toast.error(t('chat.wsNotConnected'));
        return;
      }
      if (!currentSessionId) {
        toast.error(t('chat.sessionRequired'));
        return;
      }

      const messageContent = content.trim();
      const turnId = createClientTurnId();
      const timestamp = Date.now();

      appendPendingTurn({
        sessionId: currentSessionId,
        input: messageContent,
        turnId,
        timestamp,
        pendingLabel: t('chat.trace.pending'),
      });

      send({
        type: WS_MESSAGE_TYPES.SEND_MESSAGE,
        user_id: userId,
        session_id: currentSessionId,
        message: messageContent,
        client_turn_id: turnId,
      });
    },
    [appendPendingTurn, connected, currentSessionId, send, t, userId]
  );

  const resetChat = useCallback(() => {
    resetConversation();
    resetTraceStore();
    setCurrentSessionId(null);
    lastHistoryRequestRef.current = null;
  }, [resetConversation, resetTraceStore, setCurrentSessionId]);

  const openTraceDrawer = useCallback(
    (turnId: string) => {
      openDrawer(turnId);
      void loadTrace(turnId);
    },
    [loadTrace, openDrawer]
  );

  // ============================================================================
  // Computed Values
  // ============================================================================

  const activeSnapshot = normalizeTraceSnapshot(
    activeTurnId ? snapshots[activeTurnId] : null
  );
  const activeSummary = activeTurnId ? summaries[activeTurnId] : undefined;

  const getTraceSummary = useCallback(
    (turnId: string): ExecutionTraceSummary | undefined => {
      return summaries[turnId];
    },
    [summaries]
  );

  const canOpenTrace = useCallback((message: ChatTimelineMessage): boolean => {
    const turnId = message.turnId;
    if (!turnId) return false;

    const traceSummary = turnId ? summaries[turnId] : undefined;

    return Boolean(
      message.traceAvailable ||
      message.traceSummary?.traceAvailable ||
      traceSummary?.trace_available
    );
  }, [summaries]);

  // ============================================================================
  // Return
  // ============================================================================

  return {
    // State
    messages,
    connected,
    currentSessionId,
    aiName,
    aiAvatar,

    // Actions
    sendMessage,
    resetChat,

    // Trace drawer
    drawerOpen,
    activeTurnId,
    loadingTrace,
    openTraceDrawer,
    closeTraceDrawer: closeDrawer,
    activeSnapshot,
    activeSummary,

    // Utilities
    getTraceSummary,
    canOpenTrace,
  };
}
