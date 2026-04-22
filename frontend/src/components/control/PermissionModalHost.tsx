/**
 * Convenience orchestrator: given a session id, polls pending
 * permissions and renders ``PermissionModal`` for the first one in
 * the queue. Meant to be mounted once near the root of the chat
 * surface so any pending prompt automatically surfaces.
 */
import { useEffect, useState } from 'react';
import { PermissionModal } from './PermissionModal';
import { usePendingPermissions } from './usePendingPermissions';

export interface PermissionModalHostProps {
  sessionId: string | null | undefined;
  intervalMs?: number;
}

export function PermissionModalHost({
  sessionId,
  intervalMs = 1500,
}: PermissionModalHostProps) {
  const { items, refresh } = usePendingPermissions({
    sessionId,
    intervalMs,
    enabled: Boolean(sessionId),
  });
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  useEffect(() => {
    setDismissed(new Set());
  }, [sessionId]);

  const active =
    items.find((req) => !dismissed.has(req.request_id)) ?? null;

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
      onResolved={() => {
        void refresh();
      }}
    />
  );
}
