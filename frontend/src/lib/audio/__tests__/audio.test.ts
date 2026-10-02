import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AudioFocus } from '../focus';
import { encodeMonoWav, inspectWav, MAX_AUDIO_BYTES, normalizeRecording } from '../format';
import { SegmentAudioPlayer } from '../player';
import { WavRecorder } from '../recorder';
import { useAudioIO } from '@/hooks/useAudioIO';

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

class MockSource {
  buffer: AudioBuffer | null = null;
  onended: (() => void) | null = null;
  connect = vi.fn();
  disconnect = vi.fn();
  start = vi.fn();
  stop = vi.fn();
}

class MockContext {
  static instances: MockContext[] = [];
  state = 'suspended';
  sampleRate = 16000;
  destination = {};
  audioWorklet = { addModule: vi.fn().mockResolvedValue(undefined) };
  sources: MockSource[] = [];
  input = { connect: vi.fn(), disconnect: vi.fn() };
  close = vi.fn(async () => { this.state = 'closed'; });
  resume = vi.fn(async () => { this.state = 'running'; });
  suspend = vi.fn(async () => { this.state = 'suspended'; });
  decodeAudioData = vi.fn(async (_bytes: ArrayBuffer) => ({} as AudioBuffer));
  createMediaStreamSource = vi.fn(() => this.input);
  createBufferSource() { const source = new MockSource(); this.sources.push(source); return source; }
  constructor() { MockContext.instances.push(this); }
}

class MockWorklet {
  static instances: MockWorklet[] = [];
  onprocessorerror: (() => void) | null = null;
  connect = vi.fn();
  disconnect = vi.fn();
  port = { onmessage: null as ((event: { data: unknown }) => void) | null, postMessage: vi.fn(), close: vi.fn() };
  emit(data: unknown) { this.port.onmessage?.({ data }); }
  constructor() { MockWorklet.instances.push(this); }
}

function streamFixture() {
  const track = { stop: vi.fn(), onended: null as (() => void) | null, readyState: 'live' };
  return { track, stream: { getTracks: () => [track], getAudioTracks: () => [track] } as unknown as MediaStream };
}

const clip = () => encodeMonoWav(new Float32Array(1600).fill(0.25));

beforeEach(() => {
  MockContext.instances = [];
  MockWorklet.instances = [];
  vi.stubGlobal('AudioContext', MockContext);
  vi.stubGlobal('AudioWorkletNode', MockWorklet);
  vi.stubGlobal('OfflineAudioContext', class {});
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe('bounded PCM contract', () => {
  it('encodes real sample values and validates duration independently of metadata', () => {
    const bytes = encodeMonoWav(new Float32Array([-1, 0, 0.5, 1]));
    expect(inspectWav(bytes)).toEqual({ sampleRate: 16000, channels: 1, frames: 4 });
    const view = new DataView(bytes);
    expect([44, 46, 48, 50].map((offset) => view.getInt16(offset, true))).toEqual([-32768, 0, 16384, 32767]);
  });
  it('rejects truncated, compressed, misaligned, oversized, and forged headers', () => {
    expect(() => inspectWav(clip().slice(0, 44))).toThrow();
    expect(() => inspectWav(new ArrayBuffer(MAX_AUDIO_BYTES + 1))).toThrow();
    for (const [offset, value] of [[20, 3], [22, 3], [32, 4], [34, 8]]) {
      const bytes = clip(); new DataView(bytes).setUint16(offset, value, true);
      expect(() => inspectWav(bytes)).toThrow();
    }
    const bytes = clip(); new DataView(bytes).setUint32(28, 1, true);
    expect(() => inspectWav(bytes)).toThrow();
    expect(() => encodeMonoWav(new Float32Array([NaN]))).toThrow();
    expect(() => encodeMonoWav(new Float32Array(16000 * 60 + 1))).toThrow();
  });
  it('preserves the captured sample count at the canonical rate', async () => {
    expect(inspectWav(await normalizeRecording(new Float32Array(16000), 16000)).frames).toBe(16000);
  });
});

describe('playback ownership and segment lifecycle', () => {
  it('distinguishes an unsupported runtime from blocked playback', async () => {
    const player = new SegmentAudioPlayer(new AudioFocus());
    vi.stubGlobal('AudioContext', undefined);
    expect(await player.begin()).toBeNull();
    expect(player.getSnapshot().error?.code).toBe('unsupported');
    vi.stubGlobal('AudioContext', class extends MockContext {
      resume = vi.fn().mockRejectedValue(new DOMException('Blocked', 'NotAllowedError'));
    });
    expect(await player.begin()).toBeNull();
    expect(player.getSnapshot().error?.code).toBe('playback_blocked');
    expect(MockContext.instances[0].close).toHaveBeenCalledOnce();
  });
  it('waits for earlier decoding, plays in order, and distinguishes temporary emptiness from completion', async () => {
    const player = new SegmentAudioPlayer(new AudioFocus());
    const session = (await player.begin())!;
    const context = MockContext.instances[0];
    const first = deferred<AudioBuffer>(); const second = deferred<AudioBuffer>();
    const a = { duration: 1 } as AudioBuffer; const b = { duration: 2 } as AudioBuffer;
    context.decodeAudioData.mockImplementationOnce(() => first.promise).mockImplementationOnce(() => second.promise);
    const left = player.enqueue(session, 0, clip()); const right = player.enqueue(session, 1, clip());
    second.resolve(b); await right;
    expect(context.sources).toHaveLength(0);
    first.resolve(a); await left;
    expect(context.sources[0].buffer).toBe(a);
    context.sources[0].onended?.();
    expect(context.sources[1].buffer).toBe(b);
    context.sources[1].onended?.();
    expect(player.getSnapshot().phase).toBe('waiting');
    player.finish(session);
    expect(player.getSnapshot().phase).toBe('completed');
    expect(context.close).toHaveBeenCalledOnce();
  });
  it('bounds outstanding segments, rejects repeats, and permits a backpressure retry', async () => {
    const player = new SegmentAudioPlayer(new AudioFocus()); const session = (await player.begin())!;
    const pending = deferred<AudioBuffer>();
    MockContext.instances[0].decodeAudioData.mockImplementation(() => pending.promise);
    const first = player.enqueue(session, 0, clip()); const second = player.enqueue(session, 1, clip());
    await expect(player.enqueue(session, 2, clip())).rejects.toMatchObject({ code: 'queue_full' });
    await expect(player.enqueue(session, 0, clip())).rejects.toMatchObject({ code: 'sequence_error' });
    pending.resolve({} as AudioBuffer); await Promise.all([first, second]);
    await player.enqueue(session, 2, clip());
    expect(player.getSnapshot().phase).toBe('playing');
    player.stop();
  });
  it('ignores old decode and finish after stopping and opening a new session', async () => {
    const player = new SegmentAudioPlayer(new AudioFocus()); const old = (await player.begin())!;
    const context = MockContext.instances[0]; const pending = deferred<AudioBuffer>();
    context.decodeAudioData.mockImplementation(() => pending.promise);
    const queued = player.enqueue(old, 0, clip());
    player.stop(); const current = (await player.begin())!;
    pending.resolve({} as AudioBuffer); await queued;
    player.finish(old);
    expect(context.sources).toHaveLength(0);
    expect(player.getSnapshot().phase).toBe('waiting');
    await expect(player.enqueue(old, 0, clip())).rejects.toMatchObject({ code: 'sequence_error' });
    player.finish(current);
    expect(player.getSnapshot().phase).toBe('completed');
  });
  it('pauses the context and silences the active source immediately on stop', async () => {
    const player = new SegmentAudioPlayer(new AudioFocus()); const session = (await player.begin())!;
    await player.enqueue(session, 0, clip());
    await player.setPaused(true); expect(player.getSnapshot().phase).toBe('paused');
    await player.setPaused(false); expect(player.getSnapshot().phase).toBe('playing');
    const context = MockContext.instances[0]; const onended = context.sources[0].onended;
    player.stop(); onended?.();
    expect(context.sources[0].stop).toHaveBeenCalledOnce();
    expect(player.getSnapshot().phase).toBe('stopped');
  });
  it('does not let a late pause resurrect a stopped session', async () => {
    const player = new SegmentAudioPlayer(new AudioFocus()); await player.begin();
    const paused = deferred<void>(); MockContext.instances[0].suspend.mockImplementation(() => paused.promise);
    const operation = player.setPaused(true); player.stop(); paused.resolve(); await operation;
    expect(player.getSnapshot().phase).toBe('stopped');
  });
  it('allows recording to preempt playback, but blocks playback during recording', async () => {
    const focus = new AudioFocus(); const player = new SegmentAudioPlayer(focus);
    const session = (await player.begin())!; await player.enqueue(session, 0, clip());
    const recording = {}; focus.acquire(recording, 'recording', vi.fn());
    expect(player.getSnapshot().phase).toBe('stopped');
    expect(MockContext.instances[0].sources[0].stop).toHaveBeenCalledOnce();
    expect(await player.begin()).toBeNull();
    expect(player.getSnapshot().error?.code).toBe('recording_active');
    focus.release(recording);
  });
  it('reports decode failure and releases all resources', async () => {
    const player = new SegmentAudioPlayer(new AudioFocus()); const session = (await player.begin())!;
    MockContext.instances[0].decodeAudioData.mockRejectedValue(new Error('Decoder failed'));
    await expect(player.enqueue(session, 0, clip())).rejects.toMatchObject({ code: 'playback_failed' });
    expect(player.getSnapshot().phase).toBe('failed');
    expect(MockContext.instances[0].close).toHaveBeenCalledOnce();
  });
});

describe('capture resource lifecycle', () => {
  it('stops permission results arriving after cancellation without opening a worklet', async () => {
    const pending = deferred<MediaStream>(); const { stream, track } = streamFixture();
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: () => pending.promise } });
    const recorder = new WavRecorder(new AudioFocus()); const start = recorder.start();
    recorder.cancel(); pending.resolve(stream); await start;
    expect(track.stop).toHaveBeenCalledOnce();
    expect(MockWorklet.instances).toHaveLength(0);
    expect(recorder.getSnapshot().phase).toBe('cancelled');
    expect(MockContext.instances[0].close).toHaveBeenCalledOnce();
  });
  it('flushes the final samples, releases the device, and produces valid canonical WAV', async () => {
    const { stream, track } = streamFixture();
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: async () => stream } });
    const recorder = new WavRecorder(new AudioFocus()); await recorder.start();
    const node = MockWorklet.instances[0]; node.emit(new Float32Array(1600));
    const stop = recorder.stop(); expect(recorder.stop()).toBe(stop);
    node.emit(new Float32Array(16)); node.emit('stopped'); await stop;
    expect(inspectWav(recorder.getSnapshot().audio!)).toEqual({ frames: 1616, channels: 1, sampleRate: 16000 });
    expect(track.stop).toHaveBeenCalledOnce();
    expect(node.port.close).toHaveBeenCalledOnce();
    expect(recorder.getSnapshot().phase).toBe('ready');
  });
  it('releases the device on permission rejection, disconnect, and flush timeout', async () => {
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: async () => { throw new DOMException('', 'NotAllowedError'); } } });
    const recorder = new WavRecorder(new AudioFocus()); await recorder.start();
    expect(recorder.getSnapshot().error?.code).toBe('permission_denied');
    expect(MockContext.instances[0].close).toHaveBeenCalledOnce();
    const { stream, track } = streamFixture();
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: async () => stream } });
    await recorder.start(); track.onended?.();
    expect(recorder.getSnapshot().error?.code).toBe('device_unavailable');
    expect(track.stop).toHaveBeenCalledOnce();
    vi.useFakeTimers(); await recorder.start(); const stopped = recorder.stop();
    await vi.advanceTimersByTimeAsync(1500); await stopped;
    expect(recorder.getSnapshot().error?.code).toBe('capture_failed');
    expect(track.stop).toHaveBeenCalledTimes(2);
  });
  it('stops at the duration bound without retaining overflowing samples', async () => {
    const { stream } = streamFixture(); vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: async () => stream } });
    const recorder = new WavRecorder(new AudioFocus()); await recorder.start();
    MockWorklet.instances[0].emit(new Float32Array(16000 * 60 + 10));
    expect(recorder.getSnapshot().phase).toBe('stopping');
    MockWorklet.instances[0].emit('stopped'); await recorder.stop();
    expect(inspectWav(recorder.getSnapshot().audio!).frames).toBe(16000 * 60);
    expect(recorder.getSnapshot().audio!.byteLength).toBeLessThan(MAX_AUDIO_BYTES);
  });
  it('cleans up when the owning feature changes scope or unmounts', async () => {
    const { stream, track } = streamFixture(); vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: async () => stream } });
    const { result, rerender, unmount } = renderHook(({ scope }) => useAudioIO(scope), { initialProps: { scope: 'center-a' } });
    await act(async () => { await result.current.recorder.start(); });
    rerender({ scope: 'center-b' }); expect(track.stop).toHaveBeenCalledOnce();
    await act(async () => { await result.current.recorder.start(); });
    unmount(); expect(track.stop).toHaveBeenCalledTimes(2);
  });
});
