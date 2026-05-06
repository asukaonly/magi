/**
 * Convenience orchestrator: given a session id, polls pending
 * permissions and renders ``PermissionModal`` for the first one in
 * the queue. Meant to be mounted once near the root of the chat
 * surface so any pending prompt automatically surfaces.
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
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const [nowMs, setNowMs] = useState(() => Date.now());
  const resolvedRequestIdsRef = useRef<Set<string>>(new Set());
  const previousActiveRequestIdRef = useRef<string | null>(null);

  const visibleItems = useMemo(
    () => items.filter((item) => !isInteractionExpired(item.expires_at_ms, nowMs)),
    [items, nowMs],
  );

  useEffect(() => {
    setDismissed(new Set());
    resolvedRequestIdsRef.current = new Set();
    previousActiveRequestIdRef.current = null;
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
      if (!requestId) {
        setDismissed(new Set());
        return;
      }
      setDismissed((prev) => {
        const next = new Set(prev);
        next.delete(requestId);
        return next;
      });
    };

    window.addEventListener(OPEN_PERMISSION_REQUEST_EVENT, handleOpenRequest as EventListener);
    return () => {
      window.removeEventListener(OPEN_PERMISSION_REQUEST_EVENT, handleOpenRequest as EventListener);
    };
  }, []);

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

  const active =
    visibleItems.find((req) => !dismissed.has(req.request_id)) ?? null;

  useEffect(() => {
    const previousActiveRequestId = previousActiveRequestIdRef.current;
    const currentActiveRequestId = active?.request_id ?? null;

    if (previousActiveRequestId && previousActiveRequestId !== currentActiveRequestId) {
      const stillPending = visibleItems.some((item) => item.request_id === previousActiveRequestId);
      const wasResolved = resolvedRequestIdsRef.current.has(previousActiveRequestId);
      const wasDismissed = dismissed.has(previousActiveRequestId);

      if (!stillPending && !wasResolved && !wasDismissed && sessionId) {
        toast.warning(t('permission.toast_timed_out'));
      }

      resolvedRequestIdsRef.current.delete(previousActiveRequestId);
    }

    previousActiveRequestIdRef.current = currentActiveRequestId;
  }, [active?.request_id, dismissed, visibleItems, sessionId, t]);

  return (
    <PermissionModal
      request={active}
      open={active !== null}
      onOpenChange={(open) => {
        if (!open && active) {
          setDismissed((prev) => {
            const next = new Set(prev);
            next.add(active.request_id);
            return next;
          });
        }
      }}
      onResolved={(requestId) => {
        resolvedRequestIdsRef.current.add(requestId);
        void refresh();
      }}
    />
  );
}
