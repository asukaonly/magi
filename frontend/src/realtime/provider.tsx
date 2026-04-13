/**
 * Realtime event provider — Tauri event bridge only.
 *
 * Listens to server-push notifications via Tauri events emitted from the
 * Rust notification bridge and dispatches them to subscribers.  All
 * client→server communication goes through the HTTP API layer.
 */
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  type PropsWithChildren,
} from 'react';
import { normalizeHistoryMessages, normalizeTraceSummary } from '@/domain/chat/state';
import { normalizeChatTimestamp } from '@/domain/chat/timestamps';
import { useConversationStore } from '@/stores/conversation-store';
import { useContextUsageStore } from '@/stores/context-usage';
import { TauriBridgeClient } from './tauri-bridge';

export interface RealtimeMessage {
  type?: string;
  data?: any;
  event?: string;
  channel?: string;
  sid?: string;
  message?: string;
  [key: string]: unknown;
}

type RealtimeContextValue = {
  subscribe: (listener: (message: RealtimeMessage) => void) => () => void;
};

const RealtimeContext = createContext<RealtimeContextValue | null>(null);

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
  const bridgeRef = useRef<TauriBridgeClient>();
  const dispatcherRef = useRef<RealtimeDispatcher>();

  if (!dispatcherRef.current) {
    dispatcherRef.current = new RealtimeDispatcher();
  }

  useEffect(() => {
    const dispatcher = dispatcherRef.current!;

    // Provider-level handler: route store-level events directly
    const unsubscribeProviderHandler = dispatcher.subscribe((message) => {
      const eventName = String(message.event || message.type || '').trim();
      const conversationStore = useConversationStore.getState();

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

      if (eventName === 'agent_response_chunk' && message.data && typeof message.data === 'object') {
        const payload = message.data as Record<string, unknown>;
        const sessionId = String(payload.session_id || conversationStore.currentSessionId || '').trim();
        const turnId = String(payload.turn_id || '').trim();
        if (sessionId && turnId) {
          conversationStore.appendStreamChunk({
            sessionId,
            turnId,
            contentDelta: String(payload.content_delta || ''),
            isFinal: Boolean(payload.is_final),
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
    });

    // Start Tauri event bridge
    const bridge = new TauriBridgeClient();
    bridgeRef.current = bridge;
    const unsubscribeBridge = bridge.subscribe((message) => dispatcher.dispatch(message));
    bridge.connect();

    return () => {
      unsubscribeProviderHandler();
      unsubscribeBridge();
      bridgeRef.current?.disconnect();
      bridgeRef.current = undefined;
    };
  }, []);

  const value = useMemo<RealtimeContextValue>(() => ({
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
