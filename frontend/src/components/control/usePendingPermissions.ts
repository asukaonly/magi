/**
 * Hook that keeps track of pending permission prompts for a session.
 *
 * Polls ``GET /api/control/sessions/{sid}/permissions`` at a fixed
 * interval. If/when the runtime publishes ``control.permission.requested``
 * events through the gateway bridge, the consumer can still rely on the
 * hook to reconcile state, since it re-fetches the authoritative list
 * on every tick.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  listPendingPermissions,
  PendingPermissionDTO,
} from '@/api/modules/control';
import { APP_EVENTS, subscribeToAppEvent } from '@/constants/events';
import {
  captureChatHistoryGuard,
  isChatHistoryGuardCurrent,
} from '@/hooks/chatRetryInvalidation';
import { useControlEvents } from '@/realtime/useControlEvents';

interface UsePendingPermissionsOptions {
  sessionId?: string | null;
  intervalMs?: number;
  enabled?: boolean;
}

type PermissionSnapshot = {
  sessionId: string;
  items: PendingPermissionDTO[];
};

export function usePendingPermissions({
  sessionId,
  intervalMs = 5000,
  enabled = true,
}: UsePendingPermissionsOptions) {
  const normalizedSessionId = String(sessionId || '').trim();
  const [snapshot, setSnapshot] = useState<PermissionSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const requestIdRef = useRef(0);
  const items = snapshot?.sessionId === normalizedSessionId
    ? snapshot.items
    : [];

  const refresh = useCallback(async () => {
    const requestedSessionId = normalizedSessionId;
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    if (!requestedSessionId) {
      setSnapshot(null);
      setLoading(false);
      setError(null);
      return;
    }
    const historyGuard = captureChatHistoryGuard(requestedSessionId);
    const requestIsCurrent = () => (
      requestIdRef.current === requestId
      && isChatHistoryGuardCurrent(historyGuard)
    );
    setLoading(true);
    try {
      const next = await listPendingPermissions(requestedSessionId);
      if (!requestIsCurrent()) {
        return;
      }
      setSnapshot({
        sessionId: requestedSessionId,
        items: next.filter((item) => (
          !item.session_id || item.session_id === requestedSessionId
        )),
      });
      setError(null);
    } catch (err) {
      if (requestIsCurrent()) {
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      if (requestIsCurrent()) {
        setLoading(false);
      }
    }
  }, [normalizedSessionId]);

  useEffect(() => {
    requestIdRef.current += 1;
    setSnapshot(null);
    setLoading(false);
    setError(null);
    if (!enabled || !normalizedSessionId) {
      if (timer.current) {
        clearInterval(timer.current);
        timer.current = null;
      }
      return;
    }
    void refresh();
    if (intervalMs > 0) {
      timer.current = setInterval(() => {
        void refresh();
      }, intervalMs);
    }
    return () => {
      requestIdRef.current += 1;
      if (timer.current) {
        clearInterval(timer.current);
        timer.current = null;
      }
    };
  }, [enabled, normalizedSessionId, intervalMs, refresh]);

  useEffect(() => {
    const clearCurrentSession = () => {
      requestIdRef.current += 1;
      setSnapshot((current) => (
        current?.sessionId === normalizedSessionId ? null : current
      ));
      setLoading(false);
      setError(null);
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
        setLoading(false);
        setError(null);
      },
    );
    return () => {
      unsubscribeHistoryCleared();
      unsubscribeSessionDeleted();
      unsubscribeMemoryCleared();
    };
  }, [normalizedSessionId]);

  useControlEvents({
    sessionId: normalizedSessionId || null,
    onPermissionRequested: () => {
      void refresh();
    },
    // Phase H+2: when a permission is resolved (by ANY surface —
    // desktop modal click, WeChat /approve slash command, Telegram
    // button tap), backend pushes ``control.permission.resolved``.
    // Immediate refresh clears the modal without waiting for the
    // 5-second poll.
    onPermissionResolved: () => {
      void refresh();
    },
  });

  return { items, loading, error, refresh };
}
