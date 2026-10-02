import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { TTSController } from '../tts-controller';
import { SegmentAudioPlayer } from '../player';
import { audioFocus } from '../focus';
import { encodeMonoWav } from '../format';
import type { ttsApi, TTSJob } from '@/api/modules/tts';

vi.mock('@/runtime/config', () => ({ getRuntimeGeneration: () => 0 }));
vi.mock('@/api/modules/tts', () => ({ ttsApi: {} }));

class Source {
  buffer = null;
  onended: (() => void) | null = null;
  connect = vi.fn(); disconnect = vi.fn(); start = vi.fn(); stop = vi.fn();
}
class Context {
  static instances: Context[] = [];
  state = 'suspended'; destination = {}; sources: Source[] = [];
  constructor() { Context.instances.push(this); }
  resume = async () => { this.state = 'running'; };
  suspend = async () => { this.state = 'suspended'; };
  close = async () => { this.state = 'closed'; };
  decodeAudioData = async () => ({});
  createBufferSource() { const source = new Source(); this.sources.push(source); return source; }
}
const flush = async () => { for (let i = 0; i < 25; i += 1) await Promise.resolve(); };
const controllers: TTSController[] = [];
const job = (segments = 4): TTSJob => ({ job_id: 'job', request_id: 'request', state: 'ready', engine: 'local', model: 'kokoro', voice: 'zf_xiaobei',
  speed: 1, content_hash: 'hash', cleaner_version: '1', total_segments: segments, ready_segments: 0, expires_at: Date.now() / 1000 + 600, error: null });
function fixture(count = 4) {
  let current = job(count);
  const api = {
    create: vi.fn(async () => current),
    byRequest: vi.fn(async () => current),
    get: vi.fn(async () => current),
    advance: vi.fn(async (_id: string, seq: number) => { current = { ...current, ready_segments: seq + 1, state: seq + 1 === count ? 'completed' : 'ready' }; return current; }),
    audio: vi.fn(async () => encodeMonoWav(new Float32Array(1600).fill(0.2))),
    cancel: vi.fn(async () => ({ ...current, state: 'cancelled' as const })),
  };
  const player = new SegmentAudioPlayer();
  const controller = new TTSController(player, api as unknown as typeof ttsApi);
  controllers.push(controller);
  return { controller, player, api };
}
beforeEach(() => { vi.useFakeTimers(); Context.instances = []; vi.stubGlobal('AudioContext', Context); });
afterEach(() => { controllers.splice(0).forEach((value) => value.dispose()); vi.useRealTimers(); vi.unstubAllGlobals(); });

it('prefetches one segment, preserves order and only finishes after the last source ends', async () => {
  const { controller, player, api } = fixture();
  const task = controller.speak({ kind: 'text', text: 'One. Two. Three. Four.' });
  await flush();
  expect(api.advance.mock.calls.map((call) => call[1])).toEqual([0, 1]);
  expect(player.getBufferedSegmentCount()).toBe(2);
  const context = Context.instances[0];
  context.sources[0].onended?.();
  await vi.advanceTimersByTimeAsync(160);
  expect(api.advance.mock.calls.map((call) => call[1])).toEqual([0, 1, 2]);
  context.sources[1].onended?.();
  await vi.advanceTimersByTimeAsync(160);
  await task;
  expect(controller.getSnapshot().phase).toBe('playing');
  context.sources[2].onended?.(); context.sources[3].onended?.();
  expect(controller.getSnapshot().phase).toBe('completed');
});

it('pausing stops further admission, and resuming expires instead of regenerating', async () => {
  const { controller, api } = fixture();
  const task = controller.speak({ kind: 'text', text: 'Test' });
  await flush(); await controller.pause();
  Context.instances[0].sources[0].onended?.();
  await vi.advanceTimersByTimeAsync(300);
  expect(api.advance).toHaveBeenCalledTimes(2);
  vi.setSystemTime(Date.now() + 601_000);
  await controller.pause(); await task;
  expect(controller.getSnapshot().error).toBe('audio_expired');
  expect(api.create).toHaveBeenCalledTimes(1);
});

it('pausing during audio activation is visible and prevents the first segment admission', async () => {
  const { controller, api } = fixture(1);
  const task = controller.speak({ kind: 'text', text: 'Test' });
  await controller.pause(); await flush();
  expect(controller.getSnapshot().phase).toBe('paused');
  expect(api.advance).not.toHaveBeenCalled();
  await controller.pause(); await vi.advanceTimersByTimeAsync(160); await task;
  expect(api.advance).toHaveBeenCalledOnce();
});

it('cancels by request before a late creation response and never plays the result', async () => {
  const { controller, api } = fixture(1);
  let complete!: (value: TTSJob) => void;
  api.create.mockImplementation(() => new Promise((resolve) => { complete = resolve; }));
  const task = controller.speak({ kind: 'text', text: 'Test' });
  await flush(); controller.stop(); await flush();
  expect(api.cancel).toHaveBeenCalledTimes(1);
  complete(job(1)); await task;
  expect(api.advance).not.toHaveBeenCalled();
  expect(Context.instances[0].sources).toHaveLength(0);
  expect(controller.getSnapshot().phase).toBe('stopped');
});

it('recording preempts playback and cancels synthesis without resuming it', async () => {
  const { controller, api } = fixture();
  const task = controller.speak({ kind: 'text', text: 'Test' });
  await flush();
  const recorder = {};
  expect(audioFocus.acquire(recorder, 'recording', () => undefined)).toBe(true);
  await task; await flush();
  expect(Context.instances[0].sources[0].stop).toHaveBeenCalled();
  expect(api.cancel).toHaveBeenCalledOnce();
  audioFocus.release(recorder);
  expect(controller.getSnapshot().phase).toBe('stopped');
});

it('skips automatic speech while recording owns focus', async () => {
  const { controller, api } = fixture();
  const recorder = {};
  audioFocus.acquire(recorder, 'recording', () => undefined);
  await controller.speak({ kind: 'text', text: 'Test' }, null, 'auto');
  expect(api.create).not.toHaveBeenCalled();
  audioFocus.release(recorder);
});

it('unknown create outcomes only query the existing receipt and do not resubmit', async () => {
  const { controller, api } = fixture(1);
  api.create.mockRejectedValue(new Error('timeout'));
  api.byRequest.mockResolvedValue({ ...job(1), state: 'unknown', error: 'provider_outcome_unknown' });
  api.advance.mockResolvedValue({ ...job(1), state: 'unknown', error: 'provider_outcome_unknown' });
  await controller.speak({ kind: 'text', text: 'Test' });
  expect(api.create).toHaveBeenCalledOnce();
  expect(api.byRequest).toHaveBeenCalledOnce();
  expect(controller.getSnapshot().phase).toBe('failed');
});

it('audio activation failure is explicit and makes no synthesis request', async () => {
  vi.stubGlobal('AudioContext', undefined);
  const { controller, api } = fixture();
  await controller.speak({ kind: 'text', text: 'Test' });
  expect(api.create).not.toHaveBeenCalled();
  expect(controller.getSnapshot().phase).toBe('failed');
});

it('a new operation retires the old pending source without closing the new player', async () => {
  const { controller, api } = fixture(1);
  let complete!: (value: ArrayBuffer) => void;
  api.audio.mockImplementationOnce(() => new Promise((resolve) => { complete = resolve; }));
  const old = controller.speak({ kind: 'text', text: 'Old' }); await flush();
  const next = controller.speak({ kind: 'text', text: 'New' }); await flush();
  complete(encodeMonoWav(new Float32Array(1600))); await old; await next;
  expect(Context.instances[0].sources).toHaveLength(0);
  expect(Context.instances[1].sources).toHaveLength(1);
  expect(controller.getSnapshot().phase).toBe('playing');
});
