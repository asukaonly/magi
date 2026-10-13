import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import axios from 'axios';
import { api } from '@/api/client';
import { memoryArchivesApi } from '@/api/modules/memoryArchives';
import { MemoryArchiveHistory } from '@/pages/memory-pages/MemoryArchiveHistory';
import { APP_EVENTS } from '@/constants/events';

const { translate } = vi.hoisted(() => ({ translate: (key: string) => key }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: translate, i18n: { language: 'en' } }) }));
vi.mock('@/api/client', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/api/client')>(), api: { get: vi.fn(), post: vi.fn() },
}));

const result = {
  items: [{ record_id: 'source', layer: 'l1', content: 'Historical source', source: 'user_authored', event_type: 'manual', occurred_at: 1700000000, period_end: null, archived_at: 1700000100, evidence_event_ids: [], archived: true }],
  total: 1, limit: 20, offset: 0, partial: false, issues: [],
};

beforeEach(() => { vi.clearAllMocks(); });
afterEach(() => { vi.useRealTimers(); });

describe('archive read transport', () => {
  it('requests only bounded exact evidence identifiers as repeated query parameters', async () => {
    vi.mocked(api.get).mockResolvedValue({ success: true, message: '', data: result });
    await memoryArchivesApi.getEvents(['one', 'two', 'one']);
    expect(api.get).toHaveBeenCalledWith('/memory/archives/search', {
      params: { event_ids: ['one', 'two'], limit: 2 }, paramsSerializer: { indexes: null },
    });
    const [url, config] = vi.mocked(api.get).mock.calls[0];
    const query = new URL(axios.getUri({ ...config, url, baseURL: 'http://local.test/api' })).searchParams;
    expect(query.getAll('event_ids')).toEqual(['one', 'two']);
    expect(query.has('event_ids[]')).toBe(false);
    await expect(memoryArchivesApi.getEvents([])).rejects.toThrow();
    await expect(memoryArchivesApi.getEvents(Array.from({ length: 101 }, (_, index) => String(index)))).rejects.toThrow();
    expect(api.get).toHaveBeenCalledTimes(1);
  });

  it('uses validated query parameters and preserves the typed response boundary', async () => {
    vi.mocked(api.get).mockResolvedValue({ success: true, message: '', data: result });
    expect(await memoryArchivesApi.search('京都', 20, 20)).toEqual(result);
    expect(api.get).toHaveBeenCalledWith('/memory/archives/search', { params: { query: '京都', offset: 20, limit: 20 } });
    expect(api.post).not.toHaveBeenCalled();
    vi.mocked(api.get).mockResolvedValue({ success: true, message: '', data: { ...result, partial: 'false' } });
    await expect(memoryArchivesApi.search('')).rejects.toThrow();
  });

  it('does not self-invalidate under the gateway mutation notification contract', async () => {
    vi.useFakeTimers();
    vi.mocked(api.get).mockResolvedValue({ success: true, message: '', data: result });
    vi.mocked(api.post).mockImplementation(async () => {
      await Promise.resolve();
      // The gateway emits state.changed for successful non-read HTTP methods.
      window.dispatchEvent(new CustomEvent(APP_EVENTS.CENTER_STATE_CHANGED, { detail: { resource: 'memory' } }));
      return { success: true, message: '', data: result };
    });
    await act(async () => { render(<MemoryArchiveHistory />); });
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    expect(screen.getByText('Historical source')).toBeInTheDocument();
    expect(screen.queryByText('memory.recall.searching')).not.toBeInTheDocument();
    expect(api.get).toHaveBeenCalledTimes(1);
    expect(api.post).not.toHaveBeenCalled();
  });
});
