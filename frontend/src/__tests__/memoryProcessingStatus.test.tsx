import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { memoryApi } from '@/api/modules/memory';
import { MemoryProcessingStatus } from '@/components/memory/MemoryProcessingStatus';

vi.mock('@/api/modules/memory', () => ({ memoryApi: { retryFailedL2Extractions: vi.fn(), retryFailedPostTurn: vi.fn() } }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string, args?: { count?: number }) => `${key}:${args?.count ?? ''}` }) }));

describe('MemoryProcessingStatus', () => {
  beforeEach(() => { vi.resetAllMocks(); });

  it('preserves the failure explanation and permits retry after request failure', async () => {
    const onRetried = vi.fn();
    vi.mocked(memoryApi.retryFailedL2Extractions).mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ queued_count: 2, remaining_count: 0 });
    render(<MemoryProcessingStatus pending={1} failed={2} onRetried={onRetried} />);
    expect(screen.getByText('memory.processing.help:')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button'));
    expect(await screen.findByRole('alert')).toHaveTextContent('memory.processing.retryFailed');
    expect(onRetried).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button'));
    expect(await screen.findByRole('status')).toHaveTextContent('memory.processing.queued:2');
    expect(screen.getByRole('status')).not.toHaveTextContent('memory.processing.remaining');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(onRetried).toHaveBeenCalledOnce();
  });

  it('does not admit duplicate clicks while the batch is being queued', async () => {
    let complete: (value: { queued_count: number; remaining_count: number }) => void = () => {};
    vi.mocked(memoryApi.retryFailedL2Extractions).mockImplementation(() => new Promise((resolve) => { complete = resolve; }));
    render(<MemoryProcessingStatus pending={0} failed={150} onRetried={() => {}} />);
    const button = screen.getByRole('button');
    fireEvent.click(button); fireEvent.click(button);
    expect(button).toBeDisabled();
    expect(memoryApi.retryFailedL2Extractions).toHaveBeenCalledOnce();
    complete({ queued_count: 100, remaining_count: 50 });
    await waitFor(() => expect(button).not.toBeDisabled());
    expect(screen.getByRole('status')).toHaveTextContent('memory.processing.queued:100 memory.processing.remaining:50');
  });

  it('keeps conversation retries separate from extraction and reports unfinished batches', async () => {
    const onRetried = vi.fn();
    vi.mocked(memoryApi.retryFailedPostTurn).mockRejectedValueOnce(new Error('Offline')).mockResolvedValueOnce({ queued_count: 100, remaining_count: 50 });
    render(<MemoryProcessingStatus pending={2} failed={1} postTurn={{ pending: 3, claimed: 4, failed: 150, error_kinds: ['RuntimeError'] }} onRetried={onRetried} />);
    expect(screen.getByText('memory.processing.postTurn.pending:3')).toBeInTheDocument();
    expect(screen.getByText('memory.processing.postTurn.running:4')).toBeInTheDocument();
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
});
