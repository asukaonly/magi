import { useCallback, useEffect, useRef, useState } from 'react';
import {
  AskStateDTO,
  getAskState,
} from '@/api/modules/control';
import { APP_EVENTS, subscribeToAppEvent } from '@/constants/events';
import {
  captureChatHistoryGuard,
  isChatHistoryGuardCurrent,
} from '@/hooks/chatRetryInvalidation';
import { useControlEvents } from '@/realtime/useControlEvents';
import { useConversationStore } from '@/stores';
import { OPEN_ASK_REQUEST_EVENT } from './ui-events';
import { isInteractionExpired } from './interaction-expiry';

export interface AskDialogProps {
  sessionId: string | null | undefined;
  /** Poll interval in ms; set to 0 to disable polling. */
  intervalMs?: number;
  /** Called after a successful answer. */
  onAnswered?: (requestId: string, answer: string) => void;
  /** Optional flag to indicate this ask is from a suspended background task. */
  background?: boolean;
}

type SessionAskSnapshot = {
  sessionId: string;
  ask: AskStateDTO;
};

export function AskDialog({
  sessionId,
  intervalMs = 0,
  background = false,
}: AskDialogProps) {
  const upsertMessage = useConversationStore((state) => state.upsertMessage);
  const normalizedSessionId = String(sessionId || '').trim();
  const [snapshot, setSnapshot] = useState<SessionAskSnapshot | null>(null);
  const requestIdRef = useRef(0);
  const ask = snapshot?.sessionId === normalizedSessionId
    ? snapshot.ask
    : null;

  const pull = useCallback(async () => {
    const requestedSessionId = normalizedSessionId;
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    if (!requestedSessionId) {
      setSnapshot(null);
      return;
    }
    const historyGuard = captureChatHistoryGuard(requestedSessionId);
    const requestIsCurrent = () => (
      requestIdRef.current === requestId
      && isChatHistoryGuardCurrent(historyGuard)
    );
    try {
      const current = await getAskState(requestedSessionId);
      if (!requestIsCurrent()) {
        return;
      }
      if (
        current
        && current.status === 'pending'
        && !isInteractionExpired(current.expires_at_ms)
      ) {
        setSnapshot((previous) => (
          previous?.sessionId === requestedSessionId
          && previous.ask.request_id === current.request_id
            ? previous
            : { sessionId: requestedSessionId, ask: current }
        ));
      } else {
        setSnapshot(null);
      }
    } catch {
      // swallow — transient fetch errors shouldn't crash the host
    }
  }, [normalizedSessionId]);

  useEffect(() => {
    requestIdRef.current += 1;
    if (!normalizedSessionId) {
      setSnapshot(null);
      return () => {
        requestIdRef.current += 1;
      };
    }
    void pull();
    const handle = intervalMs > 0
      ? setInterval(() => {
        void pull();
      }, intervalMs)
      : null;
    return () => {
      if (handle !== null) {
        clearInterval(handle);
      }
      requestIdRef.current += 1;
    };
  }, [normalizedSessionId, intervalMs, pull]);

  useEffect(() => {
    const clearCurrentSession = () => {
      requestIdRef.current += 1;
      setSnapshot((current) => (
        current?.sessionId === normalizedSessionId ? null : current
      ));
    };
    const clearMatchingSession = (event: Event) => {
      const clearedSessionId = String(
        (event as CustomEvent<{ sessionId?: unknown }>).detail?.sessionId
          || '',
      ).trim();
      if (clearedSessionId === normalizedSessionId) {
        clearCurrentSession();
      }
    };
    const unsubscribeHistoryCleared = subscribeToAppEvent(
      APP_EVENTS.CHAT_HISTORY_CLEARED,
      clearMatchingSession,
    );
    const unsubscribeSessionDeleted = subscribeToAppEvent(
      APP_EVENTS.CHAT_SESSION_DELETED,
      clearMatchingSession,
    );
    const unsubscribeMemoryCleared = subscribeToAppEvent(
      APP_EVENTS.MEMORY_CLEARED,
      () => {
        requestIdRef.current += 1;
        setSnapshot(null);
      },
    );
    return () => {
      unsubscribeHistoryCleared();
      unsubscribeSessionDeleted();
      unsubscribeMemoryCleared();
    };
  }, [normalizedSessionId]);

  useEffect(() => {
    if (!ask?.expires_at_ms) return () => undefined;
    const deadlineDelay = Math.max(0, ask.expires_at_ms - Date.now() + 50);
    const deadline = window.setTimeout(() => {
      setSnapshot((current) => (
        current?.sessionId === normalizedSessionId
        && current.ask.request_id === ask.request_id
          ? null
          : current
      ));
      void pull();
    }, deadlineDelay);
    return () => {
      window.clearTimeout(deadline);
    };
  }, [ask?.request_id, ask?.expires_at_ms, normalizedSessionId, pull]);

  useControlEvents({
    sessionId: normalizedSessionId || null,
    onAskRequested: () => {
      void pull();
    },
  });

  useEffect(() => {
    const handleOpenAsk = () => {
      void pull();
    };

    window.addEventListener(OPEN_ASK_REQUEST_EVENT, handleOpenAsk);
    return () => {
      window.removeEventListener(OPEN_ASK_REQUEST_EVENT, handleOpenAsk);
    };
  }, [pull]);

  useEffect(() => {
    if (!normalizedSessionId || !ask) {
      return;
    }

    upsertMessage(normalizedSessionId, {
      id: `ask:${ask.request_id}`,
      messageId: `ask:${ask.request_id}`,
      role: 'assistant',
      kind: 'assistant',
      messageKind: 'ask_request',
      content: ask.question,
      timestamp: Number(ask.created_at_ms || Date.now()),
      payload: {
        ask_request_id: ask.request_id,
        session_id: normalizedSessionId,
        status: 'pending',
        question: ask.question,
        options: ask.options,
        allow_free_text: ask.allow_free_text,
        timeout_seconds: ask.timeout_seconds,
        expires_at_ms: ask.expires_at_ms,
        background,
      },
    });
  }, [ask, background, normalizedSessionId, upsertMessage]);

  return null;
}
