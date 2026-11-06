import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { memoryApi } from '@/api/modules/memory';
import { MemoryProcessingStatus } from '@/components/memory/MemoryProcessingStatus';
import { useChatShellStore } from '@/stores/chat-shell';

vi.mock('@/api/modules/memory', () => ({ memoryApi: { retryFailedL2Extractions: vi.fn(), retryFailedPostTurn: vi.fn(), getL2Failures: vi.fn() } }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string, args?: { count?: number }) => `${key}:${args?.count ?? ''}`, i18n: { language: 'en' } }) }));

describe('MemoryProcessingStatus', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(memoryApi.getL2Failures).mockResolvedValue({ total: 2, other_count: 0, retryable_count: 2, groups: [{ source: 'chat', reason: 'auth', retry_allowed: true, count: 2, last_failed_at: 123, error: 'Access denied' }] });
  });

  it('preserves the failure explanation and permits retry after request failure', async () => {
    const onRetried = vi.fn();
    vi.mocked(memoryApi.retryFailedL2Extractions).mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ queued_count: 2, remaining_count: 0 });
    render(<MemoryProcessingStatus pending={1} failed={2} onRetried={onRetried} />);
    expect(screen.queryByText('memory.processing.help:')).not.toBeInTheDocument();
    expect(memoryApi.getL2Failures).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'memory.processing.details.show:' }));
    expect(await screen.findByText('memory.processing.reasons.auth.title:')).toBeInTheDocument();
    expect(screen.getByText('memory.processing.help:')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'memory.processing.retry:' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('memory.processing.retryFailed');
    expect(onRetried).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'memory.processing.retry:' }));
    expect(await screen.findByRole('status')).toHaveTextContent('memory.processing.queued:2');
    expect(screen.getByRole('status')).not.toHaveTextContent('memory.processing.remaining');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(onRetried).toHaveBeenCalledOnce();
  });

  it('keeps overview recovery available when every failure is a content rejection', async () => {
    vi.mocked(memoryApi.getL2Failures).mockResolvedValueOnce({ total: 2, other_count: 0, retryable_count: 2, groups: [{ source: 'notes', reason: 'content_filter', retry_allowed: true, count: 2, last_failed_at: 123, error: 'Batch rejected' }] });
    vi.mocked(memoryApi.retryFailedL2Extractions).mockResolvedValueOnce({ queued_count: 2, remaining_count: 0 });
    render(<MemoryProcessingStatus pending={0} failed={2} onRetried={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: 'memory.processing.details.show:' }));
    fireEvent.click(await screen.findByRole('button', { name: 'memory.processing.retry:' }));
    expect(await screen.findByRole('status')).toHaveTextContent('memory.processing.queued:2');
    expect(memoryApi.retryFailedL2Extractions).toHaveBeenCalledOnce();
  });

  it('does not admit duplicate clicks while the batch is being queued', async () => {
    let complete: (value: { queued_count: number; remaining_count: number }) => void = () => {};
    vi.mocked(memoryApi.retryFailedL2Extractions).mockImplementation(() => new Promise((resolve) => { complete = resolve; }));
    render(<MemoryProcessingStatus pending={0} failed={150} onRetried={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: 'memory.processing.details.show:' }));
    await screen.findByText('memory.processing.reasons.auth.title:');
    const button = screen.getByRole('button', { name: 'memory.processing.retry:' });
    fireEvent.click(button); fireEvent.click(button);
    expect(button).toBeDisabled();
    expect(memoryApi.retryFailedL2Extractions).toHaveBeenCalledOnce();
    complete({ queued_count: 100, remaining_count: 50 });
    await waitFor(() => expect(screen.getByRole('button', { name: 'memory.processing.retry:' })).not.toBeDisabled());
    expect(screen.getByRole('status')).toHaveTextContent('memory.processing.queued:100 memory.processing.remaining:50');
  });

  it('keeps conversation retries separate from extraction and reports unfinished batches', async () => {
    const onRetried = vi.fn();
    vi.mocked(memoryApi.retryFailedPostTurn).mockRejectedValueOnce(new Error('Offline')).mockResolvedValueOnce({ queued_count: 100, remaining_count: 50 });
    render(<MemoryProcessingStatus pending={2} failed={1} postTurn={{ pending: 3, claimed: 4, failed: 150, error_kinds: ['RuntimeError'] }} onRetried={onRetried} />);
    expect(screen.getByText('memory.processing.postTurn.pending:3')).toBeInTheDocument();
    expect(screen.getByText('memory.processing.postTurn.running:4')).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole('button', { name: 'memory.processing.details.show:' })[1]);
    expect(screen.getByText('RuntimeError')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'memory.processing.postTurn.retry:' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('memory.processing.postTurn.retryFailed');
    expect(memoryApi.retryFailedL2Extractions).not.toHaveBeenCalled();
    expect(onRetried).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'memory.processing.postTurn.retry:' }));
    expect(await screen.findByRole('status')).toHaveTextContent('memory.processing.postTurn.queued:100 memory.processing.postTurn.remaining:50');
    expect(onRetried).toHaveBeenCalledOnce();
  });

  it('shows unknown conversation status as unavailable rather than idle', () => {
    const refresh = vi.fn();
    render(<MemoryProcessingStatus pending={0} failed={0} postTurn={null} onRetried={() => {}} onRefresh={refresh} />);
    expect(screen.getByText('memory.processing.postTurn.unavailable:')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'common.retry:' }));
    expect(refresh).toHaveBeenCalledOnce();
    expect(memoryApi.retryFailedPostTurn).not.toHaveBeenCalled();
  });

  it('keeps healthy status invisible and normal processing free of recovery actions', () => {
    const { rerender } = render(<MemoryProcessingStatus pending={0} failed={0} onRetried={() => {}} />);
    expect(screen.getByRole('button', { name: 'memory.processing.records.title:' })).toBeInTheDocument();
    rerender(<MemoryProcessingStatus pending={2} failed={0} onRetried={() => {}} />);
    expect(screen.getByText('memory.processing.pending:2')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'memory.processing.retry:' })).not.toBeInTheDocument();
    expect(memoryApi.getL2Failures).not.toHaveBeenCalled();
  });

  it('allows diagnostic reload without reprocessing and opens relevant settings', async () => {
    vi.mocked(memoryApi.getL2Failures).mockRejectedValueOnce(new Error('Offline'));
    render(<MemoryProcessingStatus pending={0} failed={2} onRetried={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: 'memory.processing.details.show:' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('memory.processing.details.loadFailed');
    fireEvent.click(screen.getByRole('button', { name: 'common.retry:' }));
    await screen.findByText('memory.processing.reasons.auth.title:');
    expect(memoryApi.retryFailedL2Extractions).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'memory.processing.details.modelSettings:' }));
    expect(useChatShellStore.getState().activePanel).toBe('settings');
    expect(useChatShellStore.getState().settingsNavigationIntent).toEqual({ section: 'llmModels' });
    useChatShellStore.getState().resetPanel();
  });

  it('discards a diagnostic response after collapse and reloads on reopening', async () => {
    let finish: (value: Awaited<ReturnType<typeof memoryApi.getL2Failures>>) => void = () => {};
    vi.mocked(memoryApi.getL2Failures).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    render(<MemoryProcessingStatus pending={0} failed={2} onRetried={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: 'memory.processing.details.show:' }));
    fireEvent.click(screen.getByRole('button', { name: 'memory.processing.details.hide:' }));
    finish({ total: 0, other_count: 0, retryable_count: 0, groups: [] });
    fireEvent.click(screen.getByRole('button', { name: 'memory.processing.details.show:' }));
    expect(await screen.findByText('memory.processing.reasons.auth.title:')).toBeInTheDocument();
    expect(screen.queryByText('memory.processing.details.empty:')).not.toBeInTheDocument();
    expect(memoryApi.getL2Failures).toHaveBeenCalledTimes(2);
  });
});
