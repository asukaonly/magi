import { audioFocus, type AudioFocus } from './focus';
import { audioError, AudioIOError, inspectWav } from './format';

export interface PlaybackSnapshot {
  phase: 'idle' | 'starting' | 'waiting' | 'playing' | 'paused' | 'completed' | 'stopped' | 'failed';
  error: AudioIOError | null;
}

/** A bounded queue of complete WAV segments, owned by the current WebView. */
export class SegmentAudioPlayer {
  private snapshot: PlaybackSnapshot = { phase: 'idle', error: null };
  private listeners = new Set<() => void>();
  private generation = 0;
  private context: AudioContext | null = null;
  private source: AudioBufferSourceNode | null = null;
  private queue: { buffer: AudioBuffer | null }[] = [];
  private nextSequence = 0;
  private sealed = false;
  private paused = false;
  private controlling = false;

  constructor(private readonly focus: AudioFocus = audioFocus) {}

  getSnapshot = (): PlaybackSnapshot => this.snapshot;
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  private update(phase: PlaybackSnapshot['phase'], error: AudioIOError | null = null): void {
    this.snapshot = { phase, error };
    this.listeners.forEach((listener) => listener());
  }

  stop = (): void => {
    this.generation += 1;
    if (this.source) { this.source.onended = null; this.source.stop(); this.source.disconnect(); }
    this.source = null;
    this.queue = [];
    this.sealed = false;
    this.paused = false;
    this.controlling = false;
    const context = this.context;
    this.context = null;
    if (context && context.state !== 'closed') void context.close().catch(() => undefined);
    this.focus.release(this);
    this.update('stopped');
  };

  private fail(reason: unknown): void {
    this.stop();
    this.update('failed', audioError(reason, 'playback_failed'));
  }

  /** Call directly from a user gesture. A new session never replays a previous queue. */
  begin = async (): Promise<number | null> => {
    this.stop();
    if (!this.focus.acquire(this, 'playback', this.stop)) {
      this.update('failed', new AudioIOError('recording_active', 'Recording owns audio focus'));
      return null;
    }
    const generation = this.generation;
    this.nextSequence = 0;
    this.update('starting');
    try {
      if (typeof AudioContext === 'undefined') throw new AudioIOError('unsupported', 'Audio playback is unavailable');
      const context = new AudioContext();
      this.context = context;
      await context.resume();
      if (generation !== this.generation) return null;
      if (context.state !== 'running') throw new AudioIOError('playback_blocked', 'Audio context did not start');
      this.update('waiting');
      return generation;
    } catch (reason) {
      if (generation === this.generation) this.fail(reason instanceof AudioIOError
        ? reason : new AudioIOError('playback_blocked', audioError(reason, 'playback_blocked').message));
      return null;
    }
  };

  /** Backpressure and sequence errors reject without altering accepted segments. */
  enqueue = async (session: number, sequence: number, bytes: ArrayBuffer): Promise<void> => {
    const context = this.context;
    if (session !== this.generation || !context || this.snapshot.phase === 'starting' || this.sealed || sequence !== this.nextSequence) {
      throw new AudioIOError('sequence_error', 'Expected the next segment in an open playback session');
    }
    if (this.queue.length >= 2) throw new AudioIOError('queue_full', 'Wait for a queued segment to start');
    inspectWav(bytes);
    const generation = this.generation;
    const entry = { buffer: null as AudioBuffer | null };
    this.queue.push(entry);
    this.nextSequence += 1;
    try {
      // decodeAudioData detaches its input; preserve the caller's reusable recording.
      entry.buffer = await context.decodeAudioData(bytes.slice(0));
      if (generation !== this.generation) return;
      this.pump();
    } catch (reason) {
      if (generation !== this.generation) return;
      this.fail(reason);
      throw audioError(reason, 'playback_failed');
    }
  };

  finish = (session: number): void => {
    if (session !== this.generation || !this.context) return;
    this.sealed = true;
    this.pump();
  };

  private pump(): void {
    if (!this.context || this.paused || this.source) return;
    const entry = this.queue[0];
    if (!entry) {
      if (this.sealed) { this.stop(); this.update('completed'); }
      else this.update('waiting');
      return;
    }
    if (!entry.buffer) return;
    this.queue.shift();
    const source = this.context.createBufferSource();
    source.buffer = entry.buffer;
    source.connect(this.context.destination);
    const generation = this.generation;
    source.onended = () => {
      source.disconnect();
      if (generation !== this.generation) return;
      this.source = null;
      this.pump();
    };
    this.source = source;
    source.start();
    this.update('playing');
  }

  setPaused = async (paused: boolean): Promise<void> => {
    const context = this.context;
    if (!context || this.controlling || this.snapshot.phase === 'starting') return;
    const generation = this.generation;
    this.controlling = true;
    this.paused = paused;
    try {
      if (paused) await context.suspend();
      else await context.resume();
      if (generation !== this.generation) return;
      this.update(paused ? 'paused' : this.source ? 'playing' : 'waiting');
      this.pump();
    } catch (reason) {
      if (generation === this.generation) this.fail(reason);
    } finally {
      if (generation === this.generation) this.controlling = false;
    }
  };
}
