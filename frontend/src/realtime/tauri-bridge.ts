/**
 * Tauri event bridge client for receiving realtime notifications.
 *
 * Listens to Tauri events emitted from the Rust notification bridge
 * and forwards them to registered listeners.
 */

import { listen } from '@tauri-apps/api/event';

import type { RealtimeMessage } from './provider';
import { normalizeRealtimeStreamEvent } from './stream-events';

type RealtimeListener = (message: RealtimeMessage) => void;

type RealtimeStatus = {
  connected: boolean;
  reconnectAttempts: number;
  lastError: string | null;
};

type RealtimeStatusListener = (status: RealtimeStatus) => void;

/** All Tauri event names the notification bridge can emit.
 *
 * Tauri rejects event names containing `.`, so control-plane channels are
 * carried over the IPC hop with `:` separators (e.g. ``control:permission:requested``)
 * and translated back to the dotted form expected by app code in the dispatcher.
 */
const BRIDGE_EVENTS = [
  'agent_response',
  'agent_response_chunk',
  'turn_ux_plan',
  'turn_execution_control',
  'execution_trace_update',
  'context_usage',
  'chat_message_upserted',
  'chat_message_hidden',
  'background_task_state_changed',
  'user_notification_added',
  'code_agent_delegation_event',
  'code_agent_delegation_state',
  // Control-plane channels (forwarded by the Rust bridge with `.` → `:` swap;
  // see backend/src/magi/agent/control/common/events.py).
  'control:permission:requested',
  'control:permission:resolved',
  'control:ask:requested',
  'control:plan:updated',
  'control:background:suspended',
  'control:background:resumed',
] as const;

const denormalizeBridgeEventName = (name: string): string =>
  name.startsWith('control:') ? name.replace(/:/g, '.') : name;

interface BridgePayload {
  channel: string;
  user_id: string;
  session_id: string;
  turn_id?: string;
  data: Record<string, unknown>;
}

export class TauriBridgeClient {
  private listeners = new Set<RealtimeListener>();
  private statusListeners = new Set<RealtimeStatusListener>();
  private unlisten: Array<() => void> = [];
  private connected = false;

  async connect(): Promise<void> {
    if (this.connected) return;

    // Previously dynamic-imported to fail gracefully outside Tauri, but
    // @tauri-apps/api/event is now statically pulled into the eager bundle
    // anyway (via api/window etc.), so the dynamic form only produced a
    // Vite/Rolldown ineffective-dynamic-import warning without any chunk
    // savings. Static import is fine — listen() itself only does work
    // when the Tauri runtime is present.
    for (const eventName of BRIDGE_EVENTS) {
      const unlistenFn = await listen<BridgePayload>(eventName, (event) => {
        const payload = event.payload;
        const data = payload.data;
        const dispatchedName = denormalizeBridgeEventName(eventName);
        const message: RealtimeMessage = {
          event: dispatchedName,
          data,
          streamEvent: dispatchedName === 'agent_response_chunk' ? normalizeRealtimeStreamEvent(data) : null,
        };
        this.listeners.forEach((listener) => listener(message));
      });
      this.unlisten.push(unlistenFn);
    }

    this.connected = true;
    this.emitStatus();
  }

  disconnect(): void {
    for (const fn of this.unlisten) {
      fn();
    }
    this.unlisten = [];
    this.connected = false;
    this.emitStatus();
  }

  subscribe(listener: RealtimeListener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  subscribeStatus(listener: RealtimeStatusListener): () => void {
    this.statusListeners.add(listener);
    listener(this.getStatus());
    return () => {
      this.statusListeners.delete(listener);
    };
  }

  private getStatus(): RealtimeStatus {
    return {
      connected: this.connected,
      reconnectAttempts: 0,
      lastError: null,
    };
  }

  private emitStatus(): void {
    const status = this.getStatus();
    this.statusListeners.forEach((listener) => listener(status));
  }
}
