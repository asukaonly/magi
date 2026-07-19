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
import { TauriBridgeClient } from './tauri-bridge';

export interface RealtimeMessage {
  type?: string;
  data?: any;
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
    this.listeners.forEach((listener) => listener(message));
  }

  subscribe(listener: (message: RealtimeMessage) => void): () => void {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }
}

export const RealtimeProvider = ({ children }: PropsWithChildren) => {
  const { t } = useTranslation('app');
  const bridgeRef = useRef<TauriBridgeClient>();
  const dispatcherRef = useRef<RealtimeDispatcher>();

  if (!dispatcherRef.current) {
    dispatcherRef.current = new RealtimeDispatcher();
  }

  useEffect(() => {
    const dispatcher = dispatcherRef.current!;

    // Start Tauri event bridge
    const bridge = new TauriBridgeClient();
    bridgeRef.current = bridge;
    let lastRejectedProjectionSyncAt = 0;
    const unsubscribeBridge = bridge.subscribe((message) => {
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
        { pendingLabel: t('chat.trace.pending') },
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
    bridge.connect();

    return () => {
      unsubscribeBridge();
      bridgeRef.current?.disconnect();
      bridgeRef.current = undefined;
    };
  }, [t]);

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
