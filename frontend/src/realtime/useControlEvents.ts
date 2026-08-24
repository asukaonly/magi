/**
 * Subscribe to ``control.*`` realtime events pushed by the Rust
 * notification bridge.
 *
 * Consumers get a callback per event type (or ``onAny`` for a
 * firehose). The events themselves carry only pointers (session id,
 * request id); components are expected to refresh the authoritative
 * state via the REST API (``GET /api/control/*``) — this hook is
 * purely the "wake up now" signal that avoids long polling.
 */
import { useContext, useEffect } from 'react';
import { RealtimeContext } from './provider';

export type ControlEventName =
  | 'control.permission.requested'
  | 'control.permission.resolved'
  | 'control.ask.requested'
  | 'control.plan.updated'
  | 'control.background.suspended'
  | 'control.background.resumed';

export interface ControlEventPayload {
  session_id?: string;
  user_id?: string;
  request_id?: string;
  [key: string]: unknown;
}

export interface UseControlEventsOptions {
  /** Limit callbacks to a specific session id; null matches all. */
  sessionId?: string | null;
  enabled?: boolean;
  onPermissionRequested?: (payload: ControlEventPayload) => void;
  onPermissionResolved?: (payload: ControlEventPayload) => void;
  onAskRequested?: (payload: ControlEventPayload) => void;
  onPlanUpdated?: (payload: ControlEventPayload) => void;
  onBackgroundSuspended?: (payload: ControlEventPayload) => void;
  onBackgroundResumed?: (payload: ControlEventPayload) => void;
  onAny?: (event: ControlEventName, payload: ControlEventPayload) => void;
}

export function useControlEvents(options: UseControlEventsOptions): void {
  const ctx = useContext(RealtimeContext);

  useEffect(() => {
    if (!ctx || options.enabled === false) return;
    const unsubscribe = ctx.subscribe((message) => {
      const eventName = String(message.event || message.type || '');
      if (!eventName.startsWith('control.')) return;
      const payload = (message.data || {}) as ControlEventPayload;
      if (
        options.sessionId &&
        payload.session_id &&
        payload.session_id !== options.sessionId
      ) {
        return;
      }
      options.onAny?.(eventName as ControlEventName, payload);
      switch (eventName as ControlEventName) {
        case 'control.permission.requested':
          options.onPermissionRequested?.(payload);
          break;
        case 'control.permission.resolved':
          options.onPermissionResolved?.(payload);
          break;
        case 'control.ask.requested':
          options.onAskRequested?.(payload);
          break;
        case 'control.plan.updated':
          options.onPlanUpdated?.(payload);
          break;
        case 'control.background.suspended':
          options.onBackgroundSuspended?.(payload);
          break;
        case 'control.background.resumed':
          options.onBackgroundResumed?.(payload);
          break;
      }
    });
    return unsubscribe;
  }, [ctx, options]);
}
