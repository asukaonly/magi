import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { memoryArchivesApi, archiveSearchSchema } from '@/api/modules/memoryArchives';
import { MemoryArchiveHistory } from '@/pages/memory-pages/MemoryArchiveHistory';
import { APP_EVENTS } from '@/constants/events';
import { subscribeCenterRefresh } from '@/realtime/center-refresh';

const { translate } = vi.hoisted(() => ({ translate: (key: string) => key }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: translate, i18n: { language: 'en' } }) }));
vi.mock('@/api/modules/memoryArchives', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/api/modules/memoryArchives')>(), memoryArchivesApi: { search: vi.fn() },
}));

const record = (id: string, layer: 'l1' | 'l3' = 'l1') => ({ record_id: id, layer, content: `Historical ${id}`, source: 'user_authored', event_type: 'manual', occurred_at: 1700000000, period_end: null, archived_at: 1700000100, evidence_event_ids: [], archived: true as const });
const result = { items: [record('one'), record('summary', 'l3')], total: 21, limit: 20, offset: 0, partial: false, issues: [] };
beforeEach(() => { vi.clearAllMocks(); });

describe('archived history', () => {
  it('finishes a governed refresh when the shared listener was registered before the archive view', async () => {
    const unsubscribe = subscribeCenterRefresh(() => undefined, ['memory']);
    try {
      vi.mocked(memoryArchivesApi.search).mockResolvedValueOnce({ ...result, items: [record('before-refresh')] })
        .mockResolvedValue({ ...result, items: [record('after-refresh')], total: 1 });
      render(<MemoryArchiveHistory />);
      await screen.findByText('Historical before-refresh');
      act(() => window.dispatchEvent(new CustomEvent(APP_EVENTS.CENTER_STATE_CHANGED, { detail: { resource: 'memory' } })));
      expect(screen.queryByText('Historical before-refresh')).not.toBeInTheDocument();
      expect(await screen.findByText('Historical after-refresh')).toBeInTheDocument();
      expect(screen.queryByText('memory.recall.searching')).not.toBeInTheDocument();
      expect(memoryArchivesApi.search).toHaveBeenCalledTimes(2);
    } finally { unsubscribe(); }
  });

  it('withdraws cached archive content immediately and refreshes after a governance change', async () => {
    vi.mocked(memoryArchivesApi.search).mockResolvedValueOnce({ ...result, items: [record('forgotten')] })
      .mockResolvedValue({ ...result, items: [], total: 0 });
    render(<MemoryArchiveHistory />);
    await screen.findByText('Historical forgotten');
    act(() => window.dispatchEvent(new CustomEvent(APP_EVENTS.CENTER_STATE_CHANGED, { detail: { resource: 'memory' } })));
    expect(screen.queryByText('Historical forgotten')).not.toBeInTheDocument();
    expect(await screen.findByText('memory.recall.history.empty')).toBeInTheDocument();
    expect(memoryArchivesApi.search).toHaveBeenCalledTimes(2);
  });

  it.each([APP_EVENTS.CENTER_STATE_CHANGED, APP_EVENTS.MEMORY_CLEAR_STARTED])('rejects a late archive response after %s', async (eventName) => {
    let resolveOld: (value: unknown) => void = () => undefined;
    vi.mocked(memoryArchivesApi.search)
      .mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }) as never)
      .mockRejectedValue(new Error('Unavailable governance'));
    render(<MemoryArchiveHistory />);
    await waitFor(() => expect(memoryArchivesApi.search).toHaveBeenCalledTimes(1));
    act(() => window.dispatchEvent(new CustomEvent(eventName, { detail: { resource: 'memory' } })));
    await act(async () => resolveOld({ ...result, items: [record('late-forgotten')] }));
    expect(screen.queryByText('Historical late-forgotten')).not.toBeInTheDocument();
    if (eventName === APP_EVENTS.MEMORY_CLEAR_STARTED) {
      act(() => window.dispatchEvent(new CustomEvent(APP_EVENTS.CENTER_STATE_CHANGED, { detail: { resource: 'memory' } })));
    }
    expect(await screen.findByText('memory.recall.history.failed')).toBeInTheDocument();
    expect(screen.queryByText('Historical late-forgotten')).not.toBeInTheDocument();
    expect(screen.queryByText('memory.recall.history.empty')).not.toBeInTheDocument();
  });

  it('reconciles archives when the window regains focus', async () => {
    vi.mocked(memoryArchivesApi.search).mockResolvedValueOnce({ ...result, items: [record('before-focus')] })
      .mockResolvedValue({ ...result, items: [], total: 0 });
    render(<MemoryArchiveHistory />);
    await screen.findByText('Historical before-focus');
    act(() => window.dispatchEvent(new Event('focus')));
    expect(await screen.findByText('memory.recall.history.empty')).toBeInTheDocument();
    expect(screen.queryByText('Historical before-focus')).not.toBeInTheDocument();
  });

  it('browses archives separately and identifies source records versus summaries', async () => {
    vi.mocked(memoryArchivesApi.search).mockResolvedValueOnce(result).mockResolvedValueOnce({ ...result, items: [record('last')], offset: 20 });
    render(<MemoryArchiveHistory />);
    await screen.findByText('Historical one');
    expect(memoryArchivesApi.search).toHaveBeenCalledWith('', 0, 20);
    expect(screen.getByText('memory.recall.history.original')).toBeInTheDocument();
    expect(screen.getByText('memory.recall.history.summary')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'memory.evidence.next' }));
    await screen.findByText('Historical last');
    expect(memoryArchivesApi.search).toHaveBeenLastCalledWith('', 20, 20);
    expect(screen.queryByText('Historical one')).not.toBeInTheDocument();
  });

  it('does not present partial results as an exhaustive empty result and allows retry', async () => {
    vi.mocked(memoryArchivesApi.search).mockResolvedValueOnce({ ...result, items: [], total: 0, partial: true, issues: [{ code: 'archive_unreadable', count: 1 }] }).mockResolvedValueOnce({ ...result, items: [], total: 0 });
    render(<MemoryArchiveHistory />);
    await screen.findByText('memory.recall.history.partial');
    expect(screen.queryByText('memory.recall.history.empty')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'common.retry' }));
    expect(await screen.findByText('memory.recall.history.empty')).toBeInTheDocument();
  });

  it('submits user keywords and owns failure state', async () => {
    vi.mocked(memoryArchivesApi.search).mockResolvedValueOnce({ ...result, items: [], total: 0 }).mockRejectedValueOnce(new Error('Offline'));
    render(<MemoryArchiveHistory />);
    await screen.findByText('memory.recall.history.empty');
    await userEvent.type(screen.getByRole('textbox'), '爵士');
    await userEvent.click(screen.getByRole('button', { name: 'common.search' }));
    await screen.findByText('memory.recall.history.failed');
    await waitFor(() => expect(memoryArchivesApi.search).toHaveBeenLastCalledWith('爵士', 0, 20));
    expect(screen.queryByText('memory.recall.history.empty')).not.toBeInTheDocument();
  });

  it('rejects invalid archive responses at the API contract boundary', () => {
    expect(archiveSearchSchema.safeParse(result).success).toBe(true);
    expect(archiveSearchSchema.safeParse({ ...result, partial: 'false' }).success).toBe(false);
    expect(archiveSearchSchema.safeParse({ ...result, items: [{ ...record('one'), archived: false }] }).success).toBe(false);
    expect(archiveSearchSchema.safeParse({ ...result, issues: [{ code: 'secret/path', count: 1 }] }).success).toBe(false);
  });
});
