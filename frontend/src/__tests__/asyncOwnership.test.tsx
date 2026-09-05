import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { toast } from 'sonner';
import { asEventHandler } from '@/utils/as-event-handler';
import { useManagedEmbeddingModels } from '@/components/config-forms/llm-model-download-hooks';
import { localEmbeddingApi, type DownloadStatusResponse, type LocalEmbeddingModelInfo } from '@/api/modules/local-embedding';

vi.mock('@/api/modules/local-embedding', () => ({ localEmbeddingApi: { listModels: vi.fn(), downloadModel: vi.fn(), deleteModel: vi.fn(), getDownloadStatus: vi.fn() } }));
vi.mock('sonner', () => ({ toast: { error: vi.fn() } }));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(localEmbeddingApi.listModels).mockResolvedValue([]);
  vi.mocked(localEmbeddingApi.downloadModel).mockResolvedValue();
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

it('starts an event operation synchronously and reports both rejected promises and thrown errors', async () => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  const readEvent = vi.fn(() => Promise.reject(new Error('Rejected')));
  const handler = asEventHandler(readEvent);
  expect(handler()).toBeUndefined();
  expect(readEvent).toHaveBeenCalledTimes(1);
  await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(1));
  asEventHandler(() => { throw new Error('Thrown'); })();
  expect(toast.error).toHaveBeenCalledTimes(2);
});

const options = { enabled: true, downloadFailedMessage: 'Download failed' };
it('shows a failed model list and supports a successful refresh', async () => {
  vi.mocked(localEmbeddingApi.listModels).mockRejectedValueOnce(new Error('List unavailable'));
  const { result } = renderHook(() => useManagedEmbeddingModels(options));
  await waitFor(() => expect(result.current.downloadError).toBe('List unavailable'));
  await act(async () => { await result.current.refreshPresetModels(); });
  expect(result.current.downloadError).toBeNull();
});

it('preserves the model list on delete failure and explains a rejected download', async () => {
  const models = [{ id: 'model-a' }] as LocalEmbeddingModelInfo[];
  vi.mocked(localEmbeddingApi.listModels).mockResolvedValue(models);
  vi.mocked(localEmbeddingApi.deleteModel).mockRejectedValueOnce(new Error('Delete failed'));
  vi.mocked(localEmbeddingApi.downloadModel).mockRejectedValueOnce(new Error('Download refused'));
  const { result } = renderHook(() => useManagedEmbeddingModels(options));
  await waitFor(() => expect(result.current.presetModels).toEqual(models));
  await act(async () => { await result.current.handleDeleteModel('model-a'); });
  expect(result.current.presetModels).toEqual(models);
  expect(result.current.downloadError).toBe('Delete failed');
  await act(async () => { await result.current.handleDownloadModel('model-b'); });
  expect(result.current.downloadingModelId).toBeNull();
  expect(result.current.downloadError).toBe('Download refused');
});

it('deduplicates download starts, serializes polling and ignores a completion after unmount', async () => {
  vi.useFakeTimers();
  let finish!: (value: DownloadStatusResponse) => void;
  vi.mocked(localEmbeddingApi.getDownloadStatus).mockReturnValue(new Promise((resolve) => { finish = resolve; }));
  const { result, unmount } = renderHook(() => useManagedEmbeddingModels(options));
  await act(async () => {
    await Promise.all([result.current.handleDownloadModel('model-a'), result.current.handleDownloadModel('model-a')]);
  });
  expect(localEmbeddingApi.downloadModel).toHaveBeenCalledTimes(1);
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(localEmbeddingApi.getDownloadStatus).toHaveBeenCalledTimes(1);
  unmount();
  await act(async () => { finish({ model_id: 'model-a', status: 'completed', progress_pct: 100, error: null }); });
  expect(localEmbeddingApi.listModels).toHaveBeenCalledTimes(1);
  expect(vi.getTimerCount()).toBe(0);
});
