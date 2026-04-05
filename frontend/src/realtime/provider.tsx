import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  type PropsWithChildren,
} from 'react';
import { normalizeHistoryMessages, normalizeTraceSummary } from '@/domain/chat/state';
import { DEFAULT_USER_CHANNEL } from '@/constants';
import { normalizeChatTimestamp } from '@/domain/chat/timestamps';
import { getRuntimeConfig, isTauriRuntime } from '@/runtime/config';
import { useConversationStore } from '@/stores/conversation-store';
import { useContextUsageStore } from '@/stores/context-usage';
import { useRealtimeStore } from '@/stores/realtime-store';
import { RealtimeClient, type RealtimeMessage } from './client';
import { TauriBridgeClient } from './tauri-bridge';

type RealtimeContextValue = {
  send: (message: Record<string, unknown>) => void;
  subscribe: (listener: (message: RealtimeMessage) => void) => () => void;
};

const RealtimeContext = createContext<RealtimeContextValue | null>(null);

const resolveWsUrl = (): string => {
  const runtime = getRuntimeConfig();
  const base = `${runtime.wsBaseUrl}/ws`;
  if (!runtime.sessionToken) {
    return base;
  }
  const separator = base.includes('?') ? '&' : '?';
  return `${base}${separator}token=${encodeURIComponent(runtime.sessionToken)}`;
};

/** Shared listener dispatcher for merging WS and Tauri bridge events. */
class RealtimeDispatcher {
  private listeners = new Set<(message: RealtimeMessage) => void>();

  dispatch(message: RealtimeMessage): void {
    this.listeners.forEach((listener) => listener(message));
  }

  subscribe(listener: (message: RealtimeMessage) => void): () => void {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }
}

export const RealtimeProvider = ({ children }: PropsWithChildren) => {
  const clientRef = useRef<RealtimeClient>();
  const bridgeRef = useRef<TauriBridgeClient>();
  const dispatcherRef = useRef<RealtimeDispatcher>();
  const setConnected = useRealtimeStore((state) => state.setConnected);
  const setLastError = useRealtimeStore((state) => state.setLastError);
  const setReconnectAttempts = useRealtimeStore((state) => state.setReconnectAttempts);
  const setLastEventType = useRealtimeStore((state) => state.setLastEventType);
  const resetRealtime = useRealtimeStore((state) => state.reset);

  if (!clientRef.current) {
    clientRef.current = new RealtimeClient();
  }
  if (!dispatcherRef.current) {
    dispatcherRef.current = new RealtimeDispatcher();
  }

  useEffect(() => {
    const client = clientRef.current!;
    const dispatcher = dispatcherRef.current!;

    // Provider's own handler processes messages from all sources
    const unsubscribeProviderHandler = dispatcher.subscribe((message) => {
      const eventName = String(message.event || message.type || '').trim();
      const conversationStore = useConversationStore.getState();

      if (message.type === 'history' && message.data && typeof message.data === 'object' && 'session_id' in message.data) {
        const sessionId = String((message.data as { session_id?: string }).session_id || '').trim();
        const rawMessages = Array.isArray((message.data as { messages?: unknown[] }).messages)
          ? ((message.data as { messages?: unknown[] }).messages as any[])
          : [];
        if (sessionId) {
          conversationStore.receiveHistory(sessionId, normalizeHistoryMessages(rawMessages));
        }
        return;
      }

      if (message.type === 'message_sent' && message.data && typeof message.data === 'object' && 'session_id' in message.data) {
        const sessionId = String((message.data as { session_id?: string }).session_id || '').trim();
        if (sessionId) {
          conversationStore.setCurrentSessionId(sessionId);
        }
        return;
      }

      if (eventName === 'agent_response' && message.data && typeof message.data === 'object') {
        const payload = message.data as Record<string, unknown>;
        const sessionId = String(payload.session_id || conversationStore.currentSessionId || '').trim();
        const summary = normalizeTraceSummary(payload.trace_summary);
        if (sessionId) {
          conversationStore.receiveAgentResponse({
            sessionId,
            content: String(payload.content || ''),
            timestamp: normalizeChatTimestamp(payload.timestamp),
            messageId: payload.message_id ? String(payload.message_id) : undefined,
            messageKind: payload.message_kind ? String(payload.message_kind) : null,
            turnId: String(payload.turn_id || '').trim() || undefined,
            traceSummary: summary,
            traceAvailable: Boolean(payload.trace_available || summary?.traceAvailable),
          });
        }
        return;
      }

      if (eventName === 'chat_message_upserted' && message.data && typeof message.data === 'object') {
        const payload = message.data as Record<string, unknown>;
        const sessionId = String(payload.session_id || conversationStore.currentSessionId || '').trim();
        const rawMessage = payload.message;
        if (sessionId && rawMessage && typeof rawMessage === 'object') {
          const normalizedMessage = normalizeHistoryMessages([rawMessage as any])[0];
          if (normalizedMessage) {
            conversationStore.upsertMessage(sessionId, normalizedMessage);
          }
        }
        if (payload.session_summary && typeof payload.session_summary === 'object') {
          conversationStore.upsertSession(payload.session_summary as any);
        }
        return;
      }

      if (eventName === 'chat_message_hidden' && message.data && typeof message.data === 'object') {
        const payload = message.data as Record<string, unknown>;
        const sessionId = String(payload.session_id || conversationStore.currentSessionId || '').trim();
        const messageId = String(payload.message_id || '').trim();
        if (sessionId && messageId) {
          conversationStore.removeMessage(sessionId, messageId);
        }
        if (payload.session_summary && typeof payload.session_summary === 'object') {
          conversationStore.upsertSession(payload.session_summary as any);
        }
        return;
      }

      if (eventName === 'execution_trace_update' && message.data && typeof message.data === 'object') {
        const payload = message.data as Record<string, unknown>;
        const sessionId = String(payload.session_id || conversationStore.currentSessionId || '').trim();
        const turnId = String(payload.turn_id || '').trim();
        const summary = normalizeTraceSummary(payload.trace_summary);
        if (sessionId && turnId && summary) {
          conversationStore.upsertTraceSummary(sessionId, turnId, summary);
        }
        return;
      }

      if (eventName === 'context_usage' && message.data && typeof message.data === 'object') {
        const payload = message.data as Record<string, unknown>;
        const sessionId = String(payload.session_id || conversationStore.currentSessionId || '').trim();
        if (sessionId && typeof payload.used_tokens === 'number' && typeof payload.window_size === 'number') {
          useContextUsageStore.getState().update(sessionId, {
            used_tokens: payload.used_tokens as number,
            window_size: payload.window_size as number,
            threshold: (payload.threshold as number) || 0,
          });
        }
        return;
      }

      if (eventName) {
        setLastEventType(eventName);
      }
    });

    // Forward WS messages into the shared dispatcher
    const unsubscribeWs = client.subscribe((message) => dispatcher.dispatch(message));

    const unsubscribeStatus = client.subscribeStatus((status) => {
      setConnected(status.connected);
      setLastError(status.lastError);
        setReconnectAttempts(status.reconnectAttempts);
        if (status.connected) {
          client.send({ type: 'subscribe', channel: DEFAULT_USER_CHANNEL });
        }
      });

    client.connect(resolveWsUrl());

    // In desktop mode, also start Tauri event bridge for server-push notifications.
    // The WS client still handles client→server commands (send_message, etc.).
    let unsubscribeBridge: (() => void) | undefined;
    if (isTauriRuntime()) {
      const bridge = new TauriBridgeClient();
      bridgeRef.current = bridge;
      unsubscribeBridge = bridge.subscribe((message) => dispatcher.dispatch(message));
      bridge.connect();
    }

    return () => {
      unsubscribeProviderHandler();
      unsubscribeWs();
      unsubscribeStatus();
      unsubscribeBridge?.();
      bridgeRef.current?.disconnect();
      bridgeRef.current = undefined;
      client.disconnect();
      resetRealtime();
    };
  }, [resetRealtime, setConnected, setLastError, setLastEventType, setReconnectAttempts]);

  const value = useMemo<RealtimeContextValue>(() => ({
    send: (message) => clientRef.current?.send(message),
    subscribe: (listener) => dispatcherRef.current?.subscribe(listener) || (() => undefined),
  }), []);

  return (
    <RealtimeContext.Provider value={value}>
      {children}
    </RealtimeContext.Provider>
  );
};

export const useRealtime = (): RealtimeContextValue => {
  const context = useContext(RealtimeContext);
  if (!context) {
    throw new Error('useRealtime must be used within RealtimeProvider');
  }
  return context;
};
