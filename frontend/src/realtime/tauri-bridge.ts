/**
 * Tauri event bridge client for receiving realtime notifications.
 *
 * Listens to Tauri events emitted from the Rust notification bridge
 * and forwards them to registered listeners.
 */

import type { RealtimeMessage } from './provider';

type RealtimeListener = (message: RealtimeMessage) => void;

type RealtimeStatus = {
  connected: boolean;
  reconnectAttempts: number;
  lastError: string | null;
};

type RealtimeStatusListener = (status: RealtimeStatus) => void;

/** All Tauri event names the notification bridge can emit. */
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
] as const;

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

    const { listen } = await import('@tauri-apps/api/event');

    for (const eventName of BRIDGE_EVENTS) {
      const unlistenFn = await listen<BridgePayload>(eventName, (event) => {
        const payload = event.payload;
        const message: RealtimeMessage = {
          event: eventName,
          data: payload.data,
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
