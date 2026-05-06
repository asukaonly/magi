/**
 * Convenience orchestrator: given a session id, polls pending
 * permissions, mirrors them into chat status cards, and opens the
 * full permission prompt only when the user requests more options.
 */
import { useEffect, useMemo, useState } from 'react';
import { useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { useConversationStore } from '@/stores';
import { PermissionModal } from './PermissionModal';
import { usePendingPermissions } from './usePendingPermissions';
import { OPEN_PERMISSION_REQUEST_EVENT } from './ui-events';
import { isInteractionExpired } from './interaction-expiry';

export interface PermissionModalHostProps {
  sessionId: string | null | undefined;
  intervalMs?: number;
}

export function PermissionModalHost({
  sessionId,
  intervalMs = 1500,
}: PermissionModalHostProps) {
  const { t } = useTranslation('control');
  const upsertMessage = useConversationStore((state) => state.upsertMessage);
  const removeMessage = useConversationStore((state) => state.removeMessage);
  const { items, refresh } = usePendingPermissions({
    sessionId,
    intervalMs,
    enabled: Boolean(sessionId),
  });
  const [focusedRequestId, setFocusedRequestId] = useState<string | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const previousFocusedRequestIdRef = useRef<string | null>(null);

  const visibleItems = useMemo(
    () => items.filter((item) => !isInteractionExpired(item.expires_at_ms, nowMs)),
    [items, nowMs],
  );

  useEffect(() => {
    setFocusedRequestId(null);
    previousFocusedRequestIdRef.current = null;
    setNowMs(Date.now());
  }, [sessionId]);

  useEffect(() => {
    const nextDeadline = items
      .map((item) => item.expires_at_ms)
      .filter((deadline): deadline is number => typeof deadline === 'number' && deadline > nowMs)
      .sort((a, b) => a - b)[0];
    if (!nextDeadline) return () => undefined;
    const delay = Math.max(0, nextDeadline - nowMs + 50);
    const handle = window.setTimeout(() => {
      setNowMs(Date.now());
      void refresh();
    }, delay);
    return () => {
      window.clearTimeout(handle);
    };
  }, [items, nowMs, refresh]);

  useEffect(() => {
    const handleOpenRequest = (event: Event) => {
      const detail = (event as CustomEvent<{ requestId?: string }>).detail;
      const requestId = String(detail?.requestId || '').trim();
      setFocusedRequestId(requestId || visibleItems[0]?.request_id || null);
    };

    window.addEventListener(OPEN_PERMISSION_REQUEST_EVENT, handleOpenRequest as EventListener);
    return () => {
      window.removeEventListener(OPEN_PERMISSION_REQUEST_EVENT, handleOpenRequest as EventListener);
    };
  }, [visibleItems]);

  useEffect(() => {
    if (!sessionId) {
      return;
    }
    const state = useConversationStore.getState();
    if (!state.sessionsById[sessionId]) {
      return;
    }

    const currentMessages = state.messagesBySession[sessionId] || [];
    const activeMessageIds = new Set(visibleItems.map((item) => `permission:${item.request_id}`));
    currentMessages
      .filter((message) => message.messageKind === 'permission_request')
      .forEach((message) => {
        const messageId = String(message.messageId || '').trim();
        if (messageId && !activeMessageIds.has(messageId)) {
          removeMessage(sessionId, messageId);
        }
      });

    visibleItems.forEach((item) => {
      const turnId = String(item.turn_id || '').trim() || undefined;
      upsertMessage(sessionId, {
        id: `permission:${item.request_id}`,
        messageId: `permission:${item.request_id}`,
        role: 'assistant',
        kind: 'status',
        messageKind: 'permission_request',
        content: item.tool_name,
        timestamp: item.created_at ? item.created_at * 1000 : Date.now(),
        turnId,
        payload: {
          permission_request_id: item.request_id,
          session_id: sessionId,
          tool: item.tool_name,
          risk_level: item.risk_level,
          origin: item.origin,
          tool_args: item.arguments,
          timeout_seconds: item.timeout_seconds,
          expires_at_ms: item.expires_at_ms,
        },
      });
    });
  }, [visibleItems, removeMessage, sessionId, upsertMessage]);

  const active = focusedRequestId
    ? visibleItems.find((req) => req.request_id === focusedRequestId) ?? null
    : null;

  useEffect(() => {
    if (focusedRequestId && !active) {
      setFocusedRequestId(null);
    }
  }, [active, focusedRequestId]);

  useEffect(() => {
    const previousActiveRequestId = previousFocusedRequestIdRef.current;
    const currentActiveRequestId = active?.request_id ?? null;

    if (previousActiveRequestId && previousActiveRequestId !== currentActiveRequestId) {
      const stillPending = visibleItems.some((item) => item.request_id === previousActiveRequestId);

      if (!stillPending && sessionId) {
        toast.warning(t('permission.toast_timed_out'));
      }
    }

    previousFocusedRequestIdRef.current = currentActiveRequestId;
  }, [active?.request_id, visibleItems, sessionId, t]);

  return (
    <PermissionModal
      request={active}
      open={active !== null}
      onOpenChange={(open) => {
        if (!open) {
          setFocusedRequestId(null);
        }
      }}
      onResolved={() => {
        setFocusedRequestId(null);
        void refresh();
      }}
    />
  );
}
