/**
 * Realtime event provider — authenticated HTTP event stream.
 *
 * Listens to server-push notifications over SSE from the center and dispatches them to subscribers.  All
 * client→server communication goes through the HTTP API layer.
 */
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PropsWithChildren,
} from 'react';
import { useTranslation } from 'react-i18next';
import { useConversationStore } from '@/stores/conversation-store';
import {
  buildUnreadChatNotificationRequest,
  getDesktopNotificationPreferences,
  notifyForUnreadChatMessage,
  syncUnreadBadgeCount,
} from '@/runtime/desktop-notifications';
import { OPEN_ASK_REQUEST_EVENT } from '@/components/control/ui-events';
import { APP_EVENTS } from '@/constants/events';
import type { RealtimeStreamEvent } from './stream-events';
import { normalizeRealtimeStreamEvent } from './stream-events';
import { isRealtimeChatContentEvent } from './chat-projection-retirement';
import { applyRealtimeStoreProjection } from './store-projection';
import { SseClient } from './sse-client';

export interface RealtimeMessage {
  type?: string;
  data?: unknown;
  event?: string;
  channel?: string;
  sid?: string;
  message?: string;
  streamEvent?: RealtimeStreamEvent | null;
  [key: string]: unknown;
}

type RealtimeContextValue = {
  subscribe: (listener: (message: RealtimeMessage) => void) => () => void;
};

export const RealtimeContext = createContext<RealtimeContextValue | null>(null);

const shouldWakeAskDialogFromChunk = (streamEvent: RealtimeStreamEvent | null | undefined): boolean => {
  if (streamEvent?.kind !== 'tool_call_end') {
    return false;
  }

  if (streamEvent.toolName !== 'ask_user_question') {
    return false;
  }

  if (!streamEvent.toolArguments) {
    return false;
  }

  return Boolean(String(streamEvent.toolArguments.question || '').trim());
};

class RealtimeDispatcher {
  private listeners = new Set<(message: RealtimeMessage) => void>();

  dispatch(message: RealtimeMessage): void {
    for (const listener of this.listeners) {
      try { listener(message); }
      catch (error) { console.error('Realtime subscriber failed', error); }
    }
  }

  subscribe(listener: (message: RealtimeMessage) => void): () => void {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }
}

export const RealtimeProvider = ({ children }: PropsWithChildren) => {
  const { t } = useTranslation('app');
  const [connectionAttempt, setConnectionAttempt] = useState(0);
  const [connectionState, setConnectionState] = useState<'connecting' | 'ready' | 'error'>('connecting');
  const translationRef = useRef(t);
  useEffect(() => { translationRef.current = t; }, [t]);
  const bridgeRef = useRef<SseClient>();
  const dispatcherRef = useRef<RealtimeDispatcher>();

  if (!dispatcherRef.current) {
    dispatcherRef.current = new RealtimeDispatcher();
  }

  useEffect(() => {
    const dispatcher = dispatcherRef.current!;

    // One center event connection serves all page subscribers.
    const bridge = new SseClient();
    bridgeRef.current = bridge;
    let lastRejectedProjectionSyncAt = 0;
    const unsubscribeBridge = bridge.subscribe((message) => {
      if (message.event === 'state.changed' || message.event === 'resync_required') {
        window.dispatchEvent(new CustomEvent(APP_EVENTS.CENTER_STATE_CHANGED, { detail: message.data }));
        if (message.event === 'resync_required') window.dispatchEvent(new Event(APP_EVENTS.SESSION_SYNC));
      }
      const normalizedData = message.data && typeof message.data === 'object'
        ? message.data as Record<string, unknown>
        : null;
      const normalizedMessage = {
        ...message,
        streamEvent: message.streamEvent ?? (normalizedData ? normalizeRealtimeStreamEvent(normalizedData) : null),
      };
      const eventName = String(
        normalizedMessage.event || normalizedMessage.type || '',
      ).trim();
      const projectionAccepted = applyRealtimeStoreProjection(
        normalizedMessage,
        { pendingLabel: translationRef.current('chat.trace.pending') },
      );
      if (isRealtimeChatContentEvent(eventName) && !projectionAccepted) {
        const now = Date.now();
        if (now - lastRejectedProjectionSyncAt >= 1_000) {
          lastRejectedProjectionSyncAt = now;
          window.dispatchEvent(new Event(APP_EVENTS.SESSION_SYNC));
        }
        return;
      }

      const conversationStore = useConversationStore.getState();
      const notificationRequest = buildUnreadChatNotificationRequest(
        normalizedMessage,
        conversationStore.currentSessionId,
      );
      if (
        eventName === 'agent_response_chunk'
        && normalizedData
      ) {
        const sessionId = String(normalizedData.session_id || '').trim();
        const turnId = String(normalizedData.turn_id || '').trim();
        if (
          sessionId
          && sessionId === conversationStore.currentSessionId
          && shouldWakeAskDialogFromChunk(normalizedMessage.streamEvent)
        ) {
          window.dispatchEvent(new CustomEvent(OPEN_ASK_REQUEST_EVENT, {
            detail: {
              sessionId,
              turnId,
              source: 'agent_response_chunk',
            },
          }));
        }
      }
      if (notificationRequest) {
        void notifyForUnreadChatMessage({
          ...notificationRequest,
          ...getDesktopNotificationPreferences(),
        });
      }
      dispatcher.dispatch(normalizedMessage);
    });
    let cancelled = false;
    setConnectionState('connecting');
    const unsubscribeStatus = bridge.subscribeStatus((status) => {
      if (!cancelled) setConnectionState(status.connected ? 'ready' : status.lastError ? 'error' : 'connecting');
    });
    bridge.connect().then(() => {
      if (cancelled) return;
      setConnectionState('ready');
      window.dispatchEvent(new Event(APP_EVENTS.SESSION_SYNC));
    }).catch(() => {
      if (!cancelled) setConnectionState('error');
    });

    return () => {
      cancelled = true;
      unsubscribeStatus();
      unsubscribeBridge();
      bridge.disconnect();
      bridgeRef.current = undefined;
    };
  }, [connectionAttempt]);

  useEffect(() => {
    let lastUnreadCount = -1;
    const syncBadge = (state: ReturnType<typeof useConversationStore.getState>) => {
      const unreadCount = Object.values(state.unreadBySession)
        .reduce((total, count) => total + Math.max(0, Number(count) || 0), 0);
      if (unreadCount === lastUnreadCount) {
        return;
      }
      lastUnreadCount = unreadCount;
      void syncUnreadBadgeCount(unreadCount);
    };
    syncBadge(useConversationStore.getState());
    return useConversationStore.subscribe(syncBadge);
  }, []);

  const value = useMemo<RealtimeContextValue>(() => ({
    subscribe: (listener) => dispatcherRef.current?.subscribe(listener) || (() => undefined),
  }), []);

  return (
    <RealtimeContext.Provider value={value}>
      {connectionState === 'error' ? (
        <div role="alert" className="fixed inset-x-4 top-12 z-[200] flex items-center justify-between gap-4 rounded-md border border-destructive bg-background px-4 py-3 text-sm text-foreground shadow-lg">
          <span>{t('shell.realtimeUnavailable')}</span>
          <button type="button" className="shrink-0 rounded px-2 py-1 font-medium underline focus-visible:ring-2 focus-visible:ring-primary" onClick={() => setConnectionAttempt((value) => value + 1)}>{t('shell.reconnect')}</button>
        </div>
      ) : null}
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
