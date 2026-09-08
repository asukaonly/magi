import { z } from 'zod';
import { authenticatedFetch, resolveApiBaseUrl } from '@/api/client';
import { getRuntimeConfig } from '@/runtime/config';
import type { RealtimeMessage } from './provider';
import { normalizeRealtimeStreamEvent } from './stream-events';

export const bridgePayloadSchema = z.object({
  channel: z.string(), user_id: z.string(), session_id: z.string(), turn_id: z.string().nullable(),
  data: z.record(z.string(), z.unknown()),
});
const envelopeSchema = z.object({
  server_id: z.string().uuid(), epoch: z.string().uuid(), sequence: z.number().int().nonnegative(),
  event_id: z.string().max(100), event_type: z.string().min(1).max(128), data: z.unknown(),
});
type Status = { connected: boolean; reconnectAttempts: number; lastError: string | null };

/** Incremental parsing is bounded independently of network chunk boundaries. */
export class SseFrames {
  private buffer = '';
  push(text: string): string[] {
    this.buffer += text;
    const frames: string[] = [];
    while (true) {
      const match = /\r?\n\r?\n/.exec(this.buffer);
      if (!match) break;
      if (match.index > 128 * 1024) throw new Error('Server event exceeds size limit');
      frames.push(this.buffer.slice(0, match.index));
      this.buffer = this.buffer.slice(match.index + match[0].length);
    }
    if (this.buffer.length > 128 * 1024) throw new Error('Server event exceeds size limit');
    return frames;
  }
}

export class SseClient {
  private listeners = new Set<(message: RealtimeMessage) => void>();
  private statusListeners = new Set<(status: Status) => void>();
  private abort: AbortController | undefined;
  private connecting: Promise<void> | undefined;
  private status: Status = { connected: false, reconnectAttempts: 0, lastError: null };
  private lastId: string | undefined;
  private epoch: string | undefined;
  private sequence = -1;

  connect(): Promise<void> {
    if (this.connecting) return this.connecting;
    if (this.abort) return Promise.resolve();
    const owner = new AbortController();
    this.abort = owner;
    const pending = this.open(owner).then((response) => {
      if (owner !== this.abort || owner.signal.aborted) { void response.body?.cancel().catch(() => undefined); return; }
      this.setStatus({ connected: true, lastError: null });
      void this.run(owner, response).catch(() => undefined);
    }).catch((error: unknown) => {
      if (owner === this.abort) {
        this.setStatus({ connected: false, lastError: 'Center event connection failed' });
        this.abort = undefined;
      }
      throw error;
    }).finally(() => { if (this.connecting === pending) this.connecting = undefined; });
    this.connecting = pending;
    return pending;
  }

  private async open(owner: AbortController): Promise<Response> {
    const headers: Record<string, string> = { Accept: 'text/event-stream' };
    if (this.lastId) headers['Last-Event-ID'] = this.lastId;
    const opening = new AbortController();
    const timer = setTimeout(() => opening.abort(), 15_000);
    const response = await authenticatedFetch(`${resolveApiBaseUrl()}/events`, {
      headers, signal: AbortSignal.any([owner.signal, opening.signal]),
    }).finally(() => clearTimeout(timer));
    if (!response.ok || !response.headers.get('Content-Type')?.startsWith('text/event-stream') || !response.body) {
      await response.body?.cancel();
      throw new Error('Center event stream was rejected');
    }
    return response;
  }

  private async run(owner: AbortController, initial: Response): Promise<void> {
    let response = initial;
    while (owner === this.abort && !owner.signal.aborted) {
      try { await this.consume(owner, response); }
      catch { /* An interrupted stream resumes from the last validated frame. */ }
      if (owner !== this.abort || owner.signal.aborted) return;
      this.setStatus({ connected: false, lastError: 'Center event stream interrupted' });
      while (owner === this.abort && !owner.signal.aborted) {
        this.setStatus({ reconnectAttempts: this.status.reconnectAttempts + 1 });
        await this.delay(owner, Math.min(30_000, 500 * 2 ** Math.min(this.status.reconnectAttempts, 6)));
        if (owner.signal.aborted) return;
        try {
          response = await this.open(owner);
          if (owner !== this.abort || owner.signal.aborted) { await response.body?.cancel(); return; }
          this.setStatus({ connected: true, lastError: null, reconnectAttempts: 0 });
          break;
        } catch { /* Keep the disconnected state visible during bounded backoff. */ }
      }
    }
  }

  private async consume(owner: AbortController, response: Response): Promise<void> {
    const reader = response.body?.getReader();
    if (!reader) throw new Error('Center event stream body is missing');
    const decoder = new TextDecoder('utf-8', { fatal: true });
    const frames = new SseFrames();
    const cancel = () => { void reader.cancel().catch(() => undefined); };
    owner.signal.addEventListener('abort', cancel, { once: true });
    try {
      while (!owner.signal.aborted && owner === this.abort) {
        let timer: ReturnType<typeof setTimeout> | undefined;
        const read = reader.read();
        const timeout = new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error('Center event heartbeat timed out')), 45_000); });
        const chunk = await Promise.race([read, timeout]).finally(() => clearTimeout(timer));
        if (chunk.done) return;
        if (owner !== this.abort || owner.signal.aborted) return;
        for (const frame of frames.push(decoder.decode(chunk.value, { stream: true }))) {
          try { this.dispatchFrame(frame); }
          catch (error) {
            this.lastId = undefined;
            this.emit({ event: 'resync_required', data: { reason: 'invalid_event' } });
            throw error;
          }
        }
      }
    } finally { owner.signal.removeEventListener('abort', cancel); await reader.cancel().catch(() => undefined); reader.releaseLock(); }
  }

  private dispatchFrame(frame: string): void {
    const data = frame.split(/\r?\n/).filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trimStart()).join('\n');
    if (!data) return;
    const event = envelopeSchema.parse(JSON.parse(data) as unknown);
    if (event.server_id !== getRuntimeConfig().serverId || event.event_id !== `${event.epoch}:${event.sequence}`) {
      throw new Error('Center event identity is invalid');
    }
    const epochChanged = this.epoch !== undefined && event.epoch !== this.epoch;
    if (!epochChanged && event.event_type !== 'resync_required' && event.sequence <= this.sequence) return;
    const gap = !epochChanged && this.sequence >= 0 && event.sequence > this.sequence + 1;
    this.epoch = event.epoch;
    this.sequence = event.sequence;
    this.lastId = event.event_id;
    if (epochChanged || gap) this.emit({ event: 'resync_required', data: { reason: 'event_gap' } });
    if (event.event_type === 'state.changed' || event.event_type === 'resync_required') {
      this.emit({ event: event.event_type, data: event.data });
      return;
    }
    const payload = bridgePayloadSchema.parse(event.data);
    this.emit({ event: event.event_type, data: payload.data,
      streamEvent: event.event_type === 'agent_response_chunk' ? normalizeRealtimeStreamEvent(payload.data) : null });
  }

  private emit(message: RealtimeMessage): void {
    this.listeners.forEach((listener) => { try { listener(message); } catch (error) { console.error('Realtime subscriber failed', error); } });
  }
  private setStatus(next: Partial<Status>): void {
    this.status = { ...this.status, ...next };
    this.statusListeners.forEach((listener) => listener(this.status));
  }
  private delay(owner: AbortController, duration: number): Promise<void> {
    return new Promise((resolve) => {
      const done = () => { clearTimeout(timer); owner.signal.removeEventListener('abort', done); resolve(); };
      const timer = setTimeout(done, duration);
      owner.signal.addEventListener('abort', done, { once: true });
      if (owner.signal.aborted) done();
    });
  }
  disconnect(): void {
    this.abort?.abort(); this.abort = undefined; this.connecting = undefined;
    this.setStatus({ connected: false, lastError: null });
  }
  subscribe(listener: (message: RealtimeMessage) => void): () => void {
    this.listeners.add(listener); return () => { this.listeners.delete(listener); };
  }
  subscribeStatus(listener: (status: Status) => void): () => void {
    this.statusListeners.add(listener); listener(this.status); return () => { this.statusListeners.delete(listener); };
  }
}
