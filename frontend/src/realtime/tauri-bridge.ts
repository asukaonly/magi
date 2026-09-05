/**
 * Tauri event bridge client for receiving realtime notifications.
 *
 * Listens to Tauri events emitted from the Rust notification bridge
 * and forwards them to registered listeners.
 */

import { listen } from '@tauri-apps/api/event';
import { z } from 'zod';

import { getErrorMessage } from '@/utils/error-handler';

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

export const bridgePayloadSchema = z.object({
  channel: z.string(),
  user_id: z.string(),
  session_id: z.string(),
  turn_id: z.string().nullable(),
  data: z.record(z.string(), z.unknown()),
});

export class TauriBridgeClient {
  private listeners = new Set<RealtimeListener>();
  private statusListeners = new Set<RealtimeStatusListener>();
  private unlisten: Array<() => void> = [];
  private connected = false;
  private generation = 0;
  private connection: Promise<void> | undefined;
  private lastError: string | null = null;

  connect(): Promise<void> {
    if (this.connected) return Promise.resolve();
    if (this.connection) return this.connection;
    const generation = ++this.generation;
    this.lastError = null;
    this.connection = this.attach(generation);
    return this.connection;
  }

  private async attach(generation: number): Promise<void> {
    const subscriptions: Array<() => void> = [];
    this.unlisten = subscriptions;
    try {
      for (const eventName of BRIDGE_EVENTS) {
        const release = await listen<unknown>(eventName, (event) => {
          if (generation !== this.generation) return;
          const parsed = bridgePayloadSchema.safeParse(event.payload);
          if (!parsed.success) {
            this.lastError = 'Invalid desktop notification payload';
            this.emitStatus();
            return;
          }
          const data = parsed.data.data;
          const dispatchedName = denormalizeBridgeEventName(eventName);
          const message: RealtimeMessage = {
            event: dispatchedName,
            data,
            streamEvent: dispatchedName === 'agent_response_chunk' ? normalizeRealtimeStreamEvent(data) : null,
          };
          for (const listener of this.listeners) {
            try {
              listener(message);
            } catch (error) {
              console.error('Realtime notification listener failed', error);
            }
          }
        });
        if (generation !== this.generation) {
          release();
          return;
        }
        subscriptions.push(release);
      }
      this.connected = true;
      this.emitStatus();
    } catch (error) {
      for (const release of subscriptions) release();
      subscriptions.length = 0;
      if (generation === this.generation) {
        this.connected = false;
        this.lastError = getErrorMessage(error) || 'Desktop event connection failed';
        this.emitStatus();
      }
      throw error;
    } finally {
      if (generation === this.generation) this.connection = undefined;
    }
  }

  disconnect(): void {
    this.generation += 1;
    this.connection = undefined;
    for (const release of this.unlisten) release();
    this.unlisten.length = 0;
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
      lastError: this.lastError,
    };
  }

  private emitStatus(): void {
    const status = this.getStatus();
    this.statusListeners.forEach((listener) => listener(status));
  }
}
