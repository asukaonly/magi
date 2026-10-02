import { MAX_AUDIO_SECONDS } from './format';

/** AudioWorklet globals are not part of TypeScript's window DOM declarations. */
declare class AudioWorkletProcessor {
  readonly port: MessagePort;
}
declare function registerProcessor(name: string, processor: typeof AudioWorkletProcessor): void;
declare const sampleRate: number;

class CaptureProcessor extends AudioWorkletProcessor {
  private buffer = new Float32Array(2048);
  private used = 0;
  private active = true;
  private frames = 0;

  constructor() {
    super();
    this.port.onmessage = (event: MessageEvent<unknown>) => {
      if (event.data !== 'stop') return;
      this.flush();
      this.active = false;
      this.port.postMessage('stopped');
    };
  }

  private flush(): void {
    if (!this.used) return;
    const samples = this.buffer.slice(0, this.used);
    this.port.postMessage(samples, [samples.buffer]);
    this.used = 0;
  }

  process(inputs: Float32Array[][]): boolean {
    if (!this.active) return false;
    const channels = inputs[0];
    if (!channels?.length) return true;
    for (let frame = 0; frame < channels[0].length; frame += 1) {
      let sample = 0;
      for (const channel of channels) sample += channel[frame] ?? 0;
      this.buffer[this.used++] = sample / channels.length;
      if (this.used === this.buffer.length) this.flush();
      this.frames += 1;
      // Also bound capture off the main thread, where UI timers can be delayed.
      if (this.frames >= sampleRate * MAX_AUDIO_SECONDS) {
        this.flush();
        this.active = false;
        this.port.postMessage('stopped');
        return false;
      }
    }
    // Outputs stay silent: connecting the worklet must never monitor the microphone.
    return true;
  }
}

registerProcessor('magi-pcm-capture', CaptureProcessor);

export {};
