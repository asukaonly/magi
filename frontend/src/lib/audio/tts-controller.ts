import { ttsApi, type TTSSource, type TTSJob } from '@/api/modules/tts';
import { getRuntimeGeneration } from '@/runtime/config';
import type { SegmentAudioPlayer } from './player';
import { audioFocus } from './focus';

export interface SpeechSnapshot {
  phase: 'idle' | 'generating' | 'playing' | 'paused' | 'stopped' | 'completed' | 'failed';
  error: string | null;
  messageId: string | null;
  acceptedSegments: number;
  cancellation: 'none' | 'pending' | 'confirmed' | 'unknown';
}
type Operation = { requestId: string; generation: number; abort: AbortController; job: TTSJob | null; mode: 'manual' | 'auto' };

const delay = (signal: AbortSignal) => new Promise<void>((resolve, reject) => {
  if (signal.aborted) { reject(new DOMException('Stopped', 'AbortError')); return; }
  const cancel = () => { clearTimeout(timer); reject(new DOMException('Stopped', 'AbortError')); };
  const timer = setTimeout(() => { signal.removeEventListener('abort', cancel); resolve(); }, 150);
  signal.addEventListener('abort', cancel, { once: true });
});

export class TTSController {
  private state: SpeechSnapshot = { phase: 'idle', error: null, messageId: null, acceptedSegments: 0, cancellation: 'none' };
  private listeners = new Set<() => void>();
  private current: Operation | null = null;
  private latest: Operation | null = null;
  private paused = false;
  private changingPause = false;
  private unsubscribe: () => void;
  constructor(private player: SegmentAudioPlayer, private api = ttsApi) {
    this.unsubscribe = player.subscribe(() => {
      if (!this.current) return;
      const phase = player.getSnapshot().phase;
      if (phase === 'stopped') this.stop();
      else if (phase === 'failed') this.fail(player.getSnapshot().error?.code ?? 'playback_failed');
      else if (phase === 'completed') { this.current = null; this.update({ phase: 'completed' }); }
      else if (phase === 'playing' || phase === 'paused') this.update({ phase });
    });
  }
  getSnapshot = (): SpeechSnapshot => this.state;
  canAutoplay = (): boolean => this.current?.mode === 'auto' || (!this.current && audioFocus.canAutoPlay());
  subscribe = (listener: () => void): (() => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  private update(value: Partial<SpeechSnapshot>): void {
    this.state = { ...this.state, ...value }; this.listeners.forEach((listener) => listener());
  }
  private valid(op: Operation): boolean { return this.current === op && op.generation === getRuntimeGeneration() && !op.abort.signal.aborted; }
  private async cancel(op: Operation): Promise<void> {
    if (op.generation !== getRuntimeGeneration()) return;
    try {
      let result = await this.api.cancel(op.requestId);
      const deadline = Date.now() + 180_000;
      const polling = new AbortController();
      while (result.state === 'cancelling' && this.latest === op && !this.current && op.generation === getRuntimeGeneration() && Date.now() < deadline) {
        await delay(polling.signal);
        result = await this.api.get(result.job_id, polling.signal);
      }
      if (this.latest === op && !this.current) this.update({ cancellation: result.state === 'cancelled' ? 'confirmed' : 'unknown' });
    } catch { if (this.latest === op && !this.current) this.update({ cancellation: 'unknown' }); }
  }
  stop = (): void => {
    const op = this.current; this.current = null; this.paused = false;
    op?.abort.abort(); this.player.stop();
    this.update({ phase: 'stopped', cancellation: op ? 'pending' : this.state.cancellation });
    if (op) void this.cancel(op);
  };
  private fail(error: string): void { this.stop(); this.update({ phase: 'failed', error }); }
  dispose = (): void => { this.stop(); this.unsubscribe(); };
  pause = async (): Promise<void> => {
    const op = this.current;
    if (!op || this.changingPause) return;
    this.paused = !this.paused;
    if (!this.paused && this.current?.job && Date.now() / 1000 >= this.current.job.expires_at) { this.fail('audio_expired'); return; }
    this.changingPause = true;
    try {
      await this.player.setPaused(this.paused);
      if (this.valid(op)) this.update({ phase: this.paused ? 'paused'
        : this.player.getSnapshot().phase === 'playing' ? 'playing' : 'generating' });
    } finally { this.changingPause = false; }
  };

  /** Start audio activation before awaiting source hashing or the network. */
  speak = async (source: TTSSource | Promise<TTSSource>, messageId: string | null = null, mode: 'manual' | 'auto' = 'manual'): Promise<void> => {
    if (mode === 'auto' && !this.canAutoplay()) return;
    this.stop();
    // begin() synchronously stops the old player, before installing the new operation.
    const activation = this.player.begin();
    const op: Operation = { requestId: crypto.randomUUID(), generation: getRuntimeGeneration(), abort: new AbortController(), job: null, mode };
    this.current = op;
    this.latest = op;
    this.update({ phase: 'generating', error: null, messageId, acceptedSegments: 0, cancellation: 'none' });
    try {
      const session = await activation;
      if (!this.valid(op)) return;
      if (session === null) { this.fail(this.player.getSnapshot().error?.code ?? 'playback_blocked'); return; }
      if (this.paused) await this.player.setPaused(true);
      if (!this.valid(op)) return;
      const resolved = await source;
      if (!this.valid(op)) return;
      try { op.job = await this.api.create(op.requestId, resolved, op.abort.signal); }
      catch (error) {
        if (!this.valid(op)) return;
        // Only read the original receipt. Never resubmit an uncertain paid operation.
        try { op.job = await this.api.byRequest(op.requestId, op.abort.signal); }
        catch { throw error; }
      }
      if (!this.valid(op)) return;
      for (let seq = 0; seq < op.job.total_segments; seq += 1) {
        while (this.valid(op) && (this.paused || this.player.getBufferedSegmentCount() >= 2)) {
          if (Date.now() / 1000 >= op.job.expires_at) throw new Error('audio_expired');
          await delay(op.abort.signal);
        }
        if (!this.valid(op)) return;
        op.job = await this.api.advance(op.job.job_id, seq, op.abort.signal);
        while (op.job.ready_segments <= seq) {
          if (Date.now() / 1000 >= op.job.expires_at) throw new Error('audio_expired');
          if (['failed', 'unknown', 'cancelled', 'cancelling'].includes(op.job.state)) throw new Error(op.job.error ?? 'synthesis_failed');
          await delay(op.abort.signal);
          op.job = await this.api.get(op.job.job_id, op.abort.signal);
        }
        if (!this.valid(op)) return;
        const wav = await this.api.audio(op.job.job_id, seq, op.abort.signal);
        if (!this.valid(op)) return;
        await this.player.enqueue(session, seq, wav);
        if (!this.valid(op)) return;
        this.update({ acceptedSegments: seq + 1 });
      }
      if (this.valid(op)) this.player.finish(session);
    } catch (error) {
      if (this.valid(op)) {
        const code = error instanceof Error ? error.message : typeof error === 'object' && error !== null
          && 'details' in error && typeof error.details === 'string' ? error.details : 'synthesis_failed';
        this.fail(code);
      }
    }
  };
}

export async function messageSource(sessionId: string, messageId: string, content: string): Promise<TTSSource> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(content));
  const revision = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
  return { kind: 'message', session_id: sessionId, message_id: messageId, revision };
}
