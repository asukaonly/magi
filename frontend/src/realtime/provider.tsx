import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  type PropsWithChildren,
} from 'react';
import { normalizeHistoryMessages, normalizeTraceSummary } from '@/pages/chat-state';
import { getRuntimeConfig } from '@/runtime/config';
import { useConversationStore } from '@/stores/conversation-store';
import { useRealtimeStore } from '@/stores/realtime-store';
import { RealtimeClient, type RealtimeMessage } from './client';

type RealtimeContextValue = {
  send: (message: Record<string, unknown>) => void;
  subscribe: (listener: (message: RealtimeMessage) => void) => () => void;
};

const USER_CHANNEL = 'user_web_user';

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

export const RealtimeProvider = ({ children }: PropsWithChildren) => {
  const clientRef = useRef<RealtimeClient>();
  const setConnected = useRealtimeStore((state) => state.setConnected);
  const setLastError = useRealtimeStore((state) => state.setLastError);
  const setReconnectAttempts = useRealtimeStore((state) => state.setReconnectAttempts);
  const setLastEventType = useRealtimeStore((state) => state.setLastEventType);
  const resetRealtime = useRealtimeStore((state) => state.reset);

  if (!clientRef.current) {
    clientRef.current = new RealtimeClient();
  }

  useEffect(() => {
    const client = clientRef.current!;
    const unsubscribeMessages = client.subscribe((message) => {
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
            timestamp: Number(payload.timestamp || Date.now() / 1000) * 1000,
            messageId: payload.message_id ? String(payload.message_id) : undefined,
            messageKind: payload.message_kind ? String(payload.message_kind) : null,
            turnId: String(payload.turn_id || '').trim() || undefined,
            traceSummary: summary,
            traceAvailable: Boolean(payload.trace_available || summary?.traceAvailable),
          });
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

      if (eventName) {
        setLastEventType(eventName);
      }
    });

    const unsubscribeStatus = client.subscribeStatus((status) => {
      setConnected(status.connected);
      setLastError(status.lastError);
      setReconnectAttempts(status.reconnectAttempts);
      if (status.connected) {
        client.send({ type: 'subscribe', channel: USER_CHANNEL });
      }
    });

    client.connect(resolveWsUrl());

    return () => {
      unsubscribeMessages();
      unsubscribeStatus();
      client.disconnect();
      resetRealtime();
    };
  }, [resetRealtime, setConnected, setLastError, setLastEventType, setReconnectAttempts]);

  const value = useMemo<RealtimeContextValue>(() => ({
    send: (message) => clientRef.current?.send(message),
    subscribe: (listener) => clientRef.current?.subscribe(listener) || (() => undefined),
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
