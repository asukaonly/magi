import { useCallback, useEffect, useState } from 'react';
import {
  AskStateDTO,
  getAskState,
} from '@/api/modules/control';
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

export function AskDialog({
  sessionId,
  intervalMs = 0,
  background = false,
}: AskDialogProps) {
  const upsertMessage = useConversationStore((state) => state.upsertMessage);
  const removeMessage = useConversationStore((state) => state.removeMessage);
  const [ask, setAsk] = useState<AskStateDTO | null>(null);

  const pull = useCallback(async () => {
    if (!sessionId) {
      setAsk(null);
      return;
    }
    try {
      const current = await getAskState(sessionId);
      if (
        current
        && current.status === 'pending'
        && !isInteractionExpired(current.expires_at_ms)
      ) {
        setAsk((prev) =>
          prev && prev.request_id === current.request_id ? prev : current,
        );
      } else {
        setAsk(null);
      }
    } catch {
      // swallow — transient fetch errors shouldn't crash the host
    }
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) {
      setAsk(null);
      return;
    }
    void pull();
    if (intervalMs <= 0) return () => undefined;
    const handle = setInterval(() => {
      void pull();
    }, intervalMs);
    return () => {
      clearInterval(handle);
    };
  }, [sessionId, intervalMs, pull]);

  useEffect(() => {
    if (!ask?.expires_at_ms) return () => undefined;
    const deadlineDelay = Math.max(0, ask.expires_at_ms - Date.now() + 50);
    const deadline = window.setTimeout(() => {
      setAsk((prev) => (prev?.request_id === ask.request_id ? null : prev));
      void pull();
    }, deadlineDelay);
    return () => {
      window.clearTimeout(deadline);
    };
  }, [ask?.request_id, ask?.expires_at_ms, pull]);

  useControlEvents({
    sessionId: sessionId ?? null,
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
    if (!sessionId) {
      return;
    }
    const state = useConversationStore.getState();
    if (!state.sessionsById[sessionId]) {
      return;
    }
    const currentMessages = state.messagesBySession[sessionId] || [];
    const askMessages = currentMessages.filter((message) => message.messageKind === 'ask_request');
    const answeredAskRequestIds = new Set(
      currentMessages
        .filter((message) => message.messageKind === 'ask_response')
        .map((message) => {
          const payload = message.payload && typeof message.payload === 'object'
            ? message.payload as Record<string, unknown>
            : {};
          return String(payload.ask_request_id || '').trim();
        })
        .filter(Boolean),
    );

    if (!ask) {
      askMessages.forEach((message) => {
        const payload = message.payload && typeof message.payload === 'object'
          ? message.payload as Record<string, unknown>
          : {};
        const requestId = String(payload.ask_request_id || '').trim();
        if (String(payload.status || '').trim().toLowerCase() === 'answered' || answeredAskRequestIds.has(requestId)) {
          return;
        }
        const messageId = String(message.messageId || '').trim();
        if (messageId) {
          removeMessage(sessionId, messageId);
        }
      });
      return;
    }

    const activeMessageId = `ask:${ask.request_id}`;
    askMessages.forEach((message) => {
      const messageId = String(message.messageId || '').trim();
      if (messageId && messageId !== activeMessageId) {
        removeMessage(sessionId, messageId);
      }
    });

    upsertMessage(sessionId, {
      id: activeMessageId,
      messageId: activeMessageId,
      role: 'assistant',
      kind: 'assistant',
      messageKind: 'ask_request',
      content: ask.question,
      timestamp: Number(ask.created_at_ms || Date.now()),
      payload: {
        ask_request_id: ask.request_id,
        session_id: sessionId,
        status: 'pending',
        question: ask.question,
        options: ask.options,
        allow_free_text: ask.allow_free_text,
        timeout_seconds: ask.timeout_seconds,
        expires_at_ms: ask.expires_at_ms,
        background,
      },
    });
  }, [ask, background, removeMessage, sessionId, upsertMessage]);

  return null;
}
