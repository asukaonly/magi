import workletUrl from './capture.worklet.ts?worker&url';
import { audioFocus, type AudioFocus } from './focus';
import { audioError, AudioIOError, MAX_AUDIO_SECONDS, normalizeRecording } from './format';

export interface RecordingSnapshot {
  phase: 'idle' | 'requesting' | 'recording' | 'stopping' | 'ready' | 'cancelled' | 'failed';
  seconds: number;
  audio: ArrayBuffer | null;
  error: AudioIOError | null;
}

/** One bounded capture. No permission request or device access occurs in the constructor. */
export class WavRecorder {
  private snapshot: RecordingSnapshot = { phase: 'idle', seconds: 0, audio: null, error: null };
  private listeners = new Set<() => void>();
  private generation = 0;
  private context: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private node: AudioWorkletNode | null = null;
  private chunks: Float32Array[] = [];
  private frames = 0;
  private finishFlush: (() => void) | null = null;
  private stopping: Promise<void> | null = null;
  private limitTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(private readonly focus: AudioFocus = audioFocus) {}

  getSnapshot = (): RecordingSnapshot => this.snapshot;
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  private update(next: Partial<RecordingSnapshot>): void {
    this.snapshot = { ...this.snapshot, ...next };
    this.listeners.forEach((listener) => listener());
  }

  private release(): void {
    if (this.limitTimer !== null) clearTimeout(this.limitTimer);
    this.limitTimer = null;
    this.finishFlush?.();
    this.finishFlush = null;
    if (this.node) {
      this.node.port.onmessage = null;
      this.node.onprocessorerror = null;
      this.node.port.close();
      this.node.disconnect();
    }
    this.node = null;
    this.source?.disconnect();
    this.source = null;
    this.stream?.getTracks().forEach((track) => { track.onended = null; track.stop(); });
    this.stream = null;
    const context = this.context;
    this.context = null;
    // Device tracks are already stopped; a closed browser context needs no further action.
    if (context && context.state !== 'closed') void context.close().catch(() => undefined);
    this.focus.release(this);
  }

  cancel = (): void => {
    this.generation += 1;
    this.release();
    this.chunks = [];
    this.frames = 0;
    this.stopping = null;
    this.update({ phase: 'cancelled', seconds: 0, audio: null, error: null });
  };

  private fail(reason: unknown): void {
    this.cancel();
    this.update({ phase: 'failed', error: audioError(reason, 'capture_failed') });
  }

  start = async (): Promise<void> => {
    this.cancel();
    const generation = this.generation;
    this.focus.acquire(this, 'recording', this.cancel);
    this.update({ phase: 'requesting' });
    try {
      if (!navigator.mediaDevices?.getUserMedia || typeof AudioContext === 'undefined'
        || typeof AudioWorkletNode === 'undefined' || typeof OfflineAudioContext === 'undefined') {
        throw new AudioIOError('unsupported', 'Audio capture is unavailable in this WebView');
      }
      const context = new AudioContext();
      this.context = context;
      if (!context.audioWorklet || context.sampleRate < 8000 || context.sampleRate > 96000) {
        throw new AudioIOError('unsupported', 'AudioWorklet or the device sample rate is unsupported');
      }
      // Resume during the initiating gesture, before waiting for microphone permission.
      const resumed = context.resume();
      void resumed.catch(() => undefined);
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1 } });
      if (generation !== this.generation) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      this.stream = stream;
      await resumed;
      if (generation !== this.generation) return;
      await context.audioWorklet.addModule(workletUrl);
      if (generation !== this.generation) return;
      if (context.state !== 'running') throw new AudioIOError('capture_failed', 'Audio context did not start');
      const tracks = stream.getAudioTracks();
      if (!tracks.length || tracks.some((track) => track.readyState === 'ended')) {
        throw new AudioIOError('device_unavailable', 'Microphone disconnected');
      }
      const node = new AudioWorkletNode(context, 'magi-pcm-capture');
      this.node = node;
      this.source = context.createMediaStreamSource(stream);
      tracks.forEach((track) => {
        track.onended = () => { if (generation === this.generation) this.fail(new AudioIOError('device_unavailable', 'Microphone disconnected')); };
      });
      node.onprocessorerror = () => { if (generation === this.generation) this.fail(new AudioIOError('capture_failed', 'Audio processor failed')); };
      node.port.onmessage = (event: MessageEvent<unknown>) => {
        if (generation !== this.generation) return;
        if (event.data === 'stopped') { this.finishFlush?.(); return; }
        if (!(event.data instanceof Float32Array)) return;
        const remaining = context.sampleRate * MAX_AUDIO_SECONDS - this.frames;
        const chunk = event.data.slice(0, remaining);
        if (chunk.length) { this.chunks.push(chunk); this.frames += chunk.length; }
        const seconds = Math.floor(this.frames / context.sampleRate);
        if (seconds !== this.snapshot.seconds) this.update({ seconds });
        if (remaining <= event.data.length && !this.stopping) void this.stop();
      };
      this.source.connect(node);
      node.connect(context.destination);
      this.update({ phase: 'recording' });
      this.limitTimer = setTimeout(() => { void this.stop(); }, MAX_AUDIO_SECONDS * 1000);
    } catch (reason) {
      if (generation === this.generation) this.fail(reason);
    }
  };

  stop = (): Promise<void> => {
    if (this.stopping) return this.stopping;
    if (this.snapshot.phase !== 'recording' || !this.context || !this.node) return Promise.resolve();
    const generation = this.generation;
    const rate = this.context.sampleRate;
    const node = this.node;
    this.update({ phase: 'stopping' });
    this.stopping = (async () => {
      try {
        await new Promise<void>((resolve, reject) => {
          const timeout = setTimeout(() => reject(new AudioIOError('capture_failed', 'Audio processor did not flush')), 1500);
          this.finishFlush = () => { clearTimeout(timeout); resolve(); };
          node.port.postMessage('stop');
        });
        if (generation !== this.generation) return;
        const samples = new Float32Array(this.frames);
        let offset = 0;
        for (const chunk of this.chunks) { samples.set(chunk, offset); offset += chunk.length; }
        this.chunks = [];
        this.release();
        const audio = await normalizeRecording(samples, rate);
        if (generation !== this.generation) return;
        this.update({ phase: 'ready', seconds: samples.length / rate, audio });
      } catch (reason) {
        if (generation === this.generation) this.fail(reason);
      } finally {
        if (generation === this.generation) this.stopping = null;
      }
    })();
    return this.stopping;
  };
}
