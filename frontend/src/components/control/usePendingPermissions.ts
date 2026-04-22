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

interface UsePendingPermissionsOptions {
  sessionId?: string | null;
  intervalMs?: number;
  enabled?: boolean;
}

export function usePendingPermissions({
  sessionId,
  intervalMs = 1500,
  enabled = true,
}: UsePendingPermissionsOptions) {
  const [items, setItems] = useState<PendingPermissionDTO[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    if (!sessionId) {
      setItems([]);
      return;
    }
    setLoading(true);
    try {
      const next = await listPendingPermissions(sessionId);
      setItems(next);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    if (!enabled || !sessionId) {
      if (timer.current) {
        clearInterval(timer.current);
        timer.current = null;
      }
      return;
    }
    void refresh();
    timer.current = setInterval(() => {
      void refresh();
    }, intervalMs);
    return () => {
      if (timer.current) {
        clearInterval(timer.current);
        timer.current = null;
      }
    };
  }, [enabled, sessionId, intervalMs, refresh]);

  return { items, loading, error, refresh };
}
