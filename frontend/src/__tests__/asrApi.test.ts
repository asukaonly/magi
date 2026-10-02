import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { asrApi, createASROperation, transcribeRecording } from '@/api/modules/asr';
const mocked = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), generation: 1 }));
vi.mock('@/api/client', () => ({ apiClient: { get: mocked.get, post: mocked.post } }));
vi.mock('@/runtime/config', () => ({ getRuntimeGeneration: () => mocked.generation,
  getRuntimeConfig: () => ({ dataEpoch: 'data', contentEpoch: 'content' }) }));
vi.mock('@/api/config-contract', () => ({ ApiContractError: class extends Error {} }));
beforeEach(() => { vi.clearAllMocks(); mocked.generation = 1; });
afterEach(() => vi.useRealTimers());
const completed = (requestId: string) => ({ request_id: requestId, runtime_id: 'runtime', state: 'succeeded',
  result: { text: 'hello', language: null, no_speech: false, engine: 'remote', model: 'test' }, error: null, expires_at: 100 });
it('rejects a valid-shaped response owned by another recording', async () => {
  const operation = createASROperation('runtime', 'revision');
  mocked.get.mockResolvedValue({ data: completed('different') });
  await expect(asrApi.get(operation)).rejects.toThrow();
});
it('reconciles an uncertain upload with a read and never replays it', async () => {
  vi.useFakeTimers();
  const operation = createASROperation('runtime', 'revision');
  mocked.post.mockRejectedValue({ code: 'NETWORK_ERROR' });
  mocked.get.mockResolvedValue({ data: completed(operation.requestId) });
  const pending = transcribeRecording(operation, new ArrayBuffer(64), new AbortController().signal);
  await vi.advanceTimersByTimeAsync(501);
  expect((await pending).result?.text).toBe('hello');
  expect(mocked.post).toHaveBeenCalledTimes(1);
  expect(mocked.get).toHaveBeenCalledTimes(1);
  expect(mocked.post.mock.calls[0][2].headers['X-Magi-ASR-Config']).toBe('revision');
});
it('does not submit a cancellation to a newly connected center', async () => {
  const operation = createASROperation('runtime', 'revision');
  mocked.generation = 2;
  await asrApi.cancel(operation);
  expect(mocked.post).not.toHaveBeenCalled();
});
it('rejects malformed transcription results at the network boundary', async () => {
  const operation = createASROperation('runtime', 'revision');
  const response = completed(operation.requestId);
  mocked.get.mockResolvedValue({ data: { ...response, result: { ...response.result, text: 7 } } });
  await expect(asrApi.get(operation)).rejects.toThrow();
});
