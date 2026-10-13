import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { memoryArchivesApi, archiveSearchSchema } from '@/api/modules/memoryArchives';
import { MemoryArchiveHistory } from '@/pages/memory-pages/MemoryArchiveHistory';

const { translate } = vi.hoisted(() => ({ translate: (key: string) => key }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: translate, i18n: { language: 'en' } }) }));
vi.mock('@/api/modules/memoryArchives', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/api/modules/memoryArchives')>(), memoryArchivesApi: { search: vi.fn() },
}));

const record = (id: string, layer: 'l1' | 'l3' = 'l1') => ({ record_id: id, layer, content: `Historical ${id}`, source: 'user_authored', event_type: 'manual', occurred_at: 1700000000, period_end: null, archived_at: 1700000100, evidence_event_ids: [], archived: true as const });
const result = { items: [record('one'), record('summary', 'l3')], total: 21, limit: 20, offset: 0, partial: false, issues: [] };
beforeEach(() => { vi.clearAllMocks(); });

describe('archived history', () => {
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
