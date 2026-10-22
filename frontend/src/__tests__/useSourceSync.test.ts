import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { useSourceSync } from '@/hooks/useSourceSync';
import { sourcesApi, type SourceStatusItem, type SourceSyncActivity } from '@/api/modules/sources';

vi.mock('@/api/modules/sources', () => ({ sourcesApi: { getStatus: vi.fn(), requestSync: vi.fn() } }));
const source = (connection = 'a', activity?: SourceSyncActivity): SourceStatusItem => ({
  connection_id: connection, source_name: 'browser', sync_activity: activity,
} as SourceStatusItem);
const job = (job_id: string, status: string, mode: 'latest' | 'backfill' = 'latest'): SourceSyncActivity => ({ job_id, status, mode });
const tick = async () => { await act(async () => { await vi.advanceTimersByTimeAsync(1000); }); };
beforeEach(() => {
  vi.useFakeTimers(); vi.clearAllMocks();
  vi.mocked(sourcesApi.requestSync).mockResolvedValue({ queued: true, connection_id: 'a', source_name: 'browser' });
});
afterEach(() => { vi.useRealTimers(); });

it('deduplicates admission and ignores an older completed job until the new job finishes', async () => {
  const input = source('a', job('old', 'success'));
  const complete = vi.fn();
  const { result } = renderHook(() => useSourceSync(input, { onComplete: complete }));
  await act(async () => {
    const first = result.current.request();
    expect(await result.current.request()).toBe(false);
    expect(await first).toBe(true);
  });
  expect(sourcesApi.requestSync).toHaveBeenCalledOnce();
  vi.mocked(sourcesApi.getStatus).mockResolvedValue({ sources: [input] });
  await tick();
  expect(result.current.busy).toBe('latest');
  expect(complete).not.toHaveBeenCalled();
  vi.mocked(sourcesApi.getStatus).mockResolvedValue({ sources: [source('a', job('new', 'retrying'))] });
  await tick();
  vi.mocked(sourcesApi.getStatus).mockRejectedValueOnce(new Error('offline'));
  await tick();
  expect(result.current.busy).toBe('latest');
  vi.mocked(sourcesApi.getStatus).mockResolvedValue({ sources: [source('a', job('new', 'success'))] });
  await tick();
  expect(result.current.busy).toBeNull();
  expect(complete).toHaveBeenCalledOnce();
});

it('tracks an already running backfill by exact connection and job', async () => {
  const input = source('a', job('backfill', 'continuing', 'backfill'));
  const complete = vi.fn();
  const { result } = renderHook(() => useSourceSync(input, { onComplete: complete }));
  vi.mocked(sourcesApi.getStatus).mockResolvedValue({ sources: [source('b', job('backfill', 'success', 'backfill'))] });
  await tick();
  expect(complete).not.toHaveBeenCalled();
  vi.mocked(sourcesApi.getStatus).mockResolvedValue({ sources: [source('a', job('backfill', 'failed', 'backfill'))] });
  await tick();
  expect(result.current.busy).toBeNull();
  expect(complete).toHaveBeenCalledOnce();
});

it('retires requests and poll responses when the connection changes', async () => {
  let finish!: (value: Awaited<ReturnType<typeof sourcesApi.getStatus>>) => void;
  vi.mocked(sourcesApi.getStatus).mockReturnValue(new Promise(resolve => { finish = resolve; }));
  const complete = vi.fn(); const status = vi.fn();
  const { result, rerender } = renderHook(({ input }) => useSourceSync(input, { onComplete: complete, onStatus: status }), {
    initialProps: { input: source('a', job('active', 'running')) },
  });
  await tick();
  rerender({ input: source('b') });
  await act(async () => { finish({ sources: [source('a', job('active', 'success'))] }); });
  expect(result.current.source?.connection_id).toBe('b');
  expect(result.current.busy).toBeNull();
  expect(status).not.toHaveBeenCalled(); expect(complete).not.toHaveBeenCalled();
});

it('expires unobserved admission without claiming completion and allows retry after request failure', async () => {
  const input = source(); const complete = vi.fn();
  const { result } = renderHook(() => useSourceSync(input, { onComplete: complete }));
  vi.mocked(sourcesApi.requestSync).mockRejectedValueOnce(new Error('offline'));
  await act(async () => { await expect(result.current.request()).rejects.toThrow('offline'); });
  expect(result.current.busy).toBeNull();
  await act(async () => { await result.current.request(); });
  vi.mocked(sourcesApi.getStatus).mockResolvedValue({ sources: [input] });
  await act(async () => { await vi.advanceTimersByTimeAsync(91_000); });
  expect(result.current.busy).toBeNull(); expect(complete).not.toHaveBeenCalled();
});
