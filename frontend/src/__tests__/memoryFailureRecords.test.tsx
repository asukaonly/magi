import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { memoryApi, type MemoryFailureRecord } from '@/api/modules/memory';
import { MemoryFailureRecords } from '@/components/memory/MemoryFailureRecords';

vi.mock('@/api/modules/memory', () => ({ memoryApi: { getL2FailureRecords: vi.fn(), setL2FailureDisposition: vi.fn(), retryFailedL2Extractions: vi.fn() } }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string, args?: { count?: number }) => `${key}:${args?.count ?? ''}`, i18n: { language: 'en' } }) }));

const blocked: MemoryFailureRecord = {
  event_id: 'blocked', source: 'notes', reason: 'content_filter', retry_allowed: true,
  status: 'failed', attempt_count: 1, last_failed_at: 10, updated_at: 20,
  content: 'A preview of the original', content_truncated: true, recorded_at: 5, error: 'Request rejected',
};
const page = (items: MemoryFailureRecord[], total = items.length) => ({ items, total, limit: 20, offset: 0 });

describe('MemoryFailureRecords', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(memoryApi.getL2FailureRecords).mockResolvedValue(page([blocked]));
    vi.mocked(memoryApi.setL2FailureDisposition).mockResolvedValue({ changed_count: 1, unchanged_count: 0 });
  });

  it('shows affected originals and offers explicit individual recovery without auto-retrying', async () => {
    render(<MemoryFailureRecords initialFilter={{ source: 'notes', reason: 'content_filter' }} onClose={() => {}} onChanged={() => {}} />);
    expect(await screen.findByText('A preview of the original…')).toBeInTheDocument();
    expect(screen.getByText('memory.processing.records.contentNotice:')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'common.retry:' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.processing.records.retryIndividually:' })).toBeInTheDocument();
    expect(memoryApi.getL2FailureRecords).toHaveBeenCalledWith({ status: 'failed', source: 'notes', reason: 'content_filter', limit: 20, offset: 0 });
    vi.mocked(memoryApi.getL2FailureRecords).mockResolvedValueOnce(page([{ ...blocked, content: 'The complete original text', content_truncated: false }]));
    fireEvent.click(screen.getByRole('button', { name: 'memory.processing.records.viewContent:' }));
    expect(await screen.findByText('The complete original text')).toBeInTheDocument();
    expect(memoryApi.getL2FailureRecords).toHaveBeenLastCalledWith({ event_id: 'blocked', status: 'failed', include_content: true, limit: 1 });
    expect(memoryApi.retryFailedL2Extractions).not.toHaveBeenCalled();
  });

  it('ignores a reviewed snapshot and allows undo without scheduling work', async () => {
    const changed = vi.fn();
    render(<MemoryFailureRecords initialFilter={{}} onClose={() => {}} onChanged={changed} />);
    await screen.findByText('A preview of the original…');
    vi.mocked(memoryApi.getL2FailureRecords).mockResolvedValueOnce(page([]));
    fireEvent.click(screen.getByRole('button', { name: 'memory.processing.records.ignore:' }));
    expect(await screen.findByText('memory.processing.records.ignoredFeedback:1')).toBeInTheDocument();
    expect(memoryApi.setL2FailureDisposition).toHaveBeenCalledWith('ignore', [blocked]);
    await waitFor(() => expect(screen.getByRole('button', { name: 'memory.processing.records.ignored:' })).toBeEnabled());
    const ignored = { ...blocked, status: 'ignored' as const, updated_at: 30 };
    vi.mocked(memoryApi.getL2FailureRecords).mockResolvedValueOnce(page([ignored]));
    fireEvent.click(screen.getByRole('button', { name: 'memory.processing.records.ignored:' }));
    await screen.findByText('A preview of the original…');
    vi.mocked(memoryApi.getL2FailureRecords).mockResolvedValueOnce(page([]));
    fireEvent.click(screen.getByRole('button', { name: 'memory.processing.records.restore:' }));
    expect(await screen.findByText('memory.processing.records.restoredFeedback:1')).toBeInTheDocument();
    expect(memoryApi.setL2FailureDisposition).toHaveBeenLastCalledWith('restore', [ignored]);
    expect(memoryApi.retryFailedL2Extractions).not.toHaveBeenCalled();
    expect(changed).toHaveBeenCalledTimes(2);
  });

  it('retries only eligible records on the visible page and prevents double submission', async () => {
    const timeout = { ...blocked, event_id: 'timeout', reason: 'timeout' as const, retry_allowed: true };
    const missing = { ...blocked, event_id: 'missing', reason: 'missing_source' as const, retry_allowed: false, content: null };
    vi.mocked(memoryApi.getL2FailureRecords).mockResolvedValue(page([blocked, timeout, missing]));
    let complete: (value: { queued_count: number; remaining_count: number }) => void = () => {};
    vi.mocked(memoryApi.retryFailedL2Extractions).mockImplementation(() => new Promise((resolve) => { complete = resolve; }));
    render(<MemoryFailureRecords initialFilter={{}} onClose={() => {}} onChanged={() => {}} />);
    const retry = await screen.findByRole('button', { name: 'memory.processing.records.retryPage:2' });
    fireEvent.click(retry); fireEvent.click(retry);
    expect(retry).toBeDisabled();
    expect(memoryApi.retryFailedL2Extractions).toHaveBeenCalledExactlyOnceWith({ event_ids: ['blocked', 'timeout'] });
    vi.mocked(memoryApi.getL2FailureRecords).mockResolvedValueOnce(page([missing]));
    complete({ queued_count: 2, remaining_count: 1 });
    expect(await screen.findByText('memory.processing.queued:2')).toBeInTheDocument();
  });

  it('keeps the remaining batch member retryable after ignoring a suspect record', async () => {
    const peer = { ...blocked, event_id: 'peer', content: 'Another record from the rejected batch' };
    vi.mocked(memoryApi.getL2FailureRecords).mockResolvedValueOnce(page([blocked, peer]));
    render(<MemoryFailureRecords initialFilter={{}} onClose={() => {}} onChanged={() => {}} />);
    await screen.findByText('A preview of the original…');
    vi.mocked(memoryApi.getL2FailureRecords).mockResolvedValueOnce(page([peer]));
    fireEvent.click(screen.getAllByRole('button', { name: 'memory.processing.records.ignore:' })[0]);
    expect(await screen.findByText('memory.processing.records.ignoredFeedback:1')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: 'memory.processing.records.retryIndividually:' })).toBeEnabled());
    vi.mocked(memoryApi.retryFailedL2Extractions).mockResolvedValueOnce({ queued_count: 1, remaining_count: 0 });
    vi.mocked(memoryApi.getL2FailureRecords).mockResolvedValueOnce(page([]));
    fireEvent.click(screen.getByRole('button', { name: 'memory.processing.records.retryIndividually:' }));
    expect(await screen.findByText('memory.processing.queued:1')).toBeInTheDocument();
    expect(memoryApi.retryFailedL2Extractions).toHaveBeenCalledExactlyOnceWith({ event_ids: ['peer'] });
  });

  it('paginates the complete filtered list and recovers from a read failure', async () => {
    vi.mocked(memoryApi.getL2FailureRecords).mockRejectedValueOnce(new Error('Offline')).mockResolvedValue(page([blocked], 21));
    render(<MemoryFailureRecords initialFilter={{ reason: 'content_filter' }} onClose={() => {}} onChanged={() => {}} />);
    await screen.findByRole('alert');
    fireEvent.click(screen.getByRole('button', { name: 'common.retry:' }));
    await screen.findByText('A preview of the original…');
    fireEvent.click(screen.getByRole('button', { name: 'memory.pagination.next:' }));
    await waitFor(() => expect(memoryApi.getL2FailureRecords).toHaveBeenLastCalledWith({ status: 'failed', reason: 'content_filter', limit: 20, offset: 20 }));
    expect(memoryApi.setL2FailureDisposition).not.toHaveBeenCalled();
  });

  it('preserves the record after an action failure and reports concurrent changes honestly', async () => {
    vi.mocked(memoryApi.setL2FailureDisposition).mockRejectedValueOnce(new Error('Offline')).mockResolvedValueOnce({ changed_count: 0, unchanged_count: 1 });
    render(<MemoryFailureRecords initialFilter={{}} onClose={() => {}} onChanged={() => {}} />);
    await screen.findByText('A preview of the original…');
    fireEvent.click(screen.getByRole('button', { name: 'memory.processing.records.ignore:' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('memory.processing.records.actionFailed');
    expect(screen.getByText('A preview of the original…')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'memory.processing.records.ignore:' }));
    expect(await screen.findByText('memory.processing.records.changedMeanwhile:0')).toBeInTheDocument();
    expect(screen.queryByText('memory.processing.records.ignoredFeedback:1')).not.toBeInTheDocument();
  });
});
