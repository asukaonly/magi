import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { memoryApi } from '@/api/modules/memory';
import { MemoryProcessingStatus } from '@/components/memory/MemoryProcessingStatus';

vi.mock('@/api/modules/memory', () => ({ memoryApi: { retryFailedL2Extractions: vi.fn() } }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string, args?: { count?: number }) => `${key}:${args?.count ?? ''}` }) }));

describe('MemoryProcessingStatus', () => {
  beforeEach(() => { vi.mocked(memoryApi.retryFailedL2Extractions).mockReset(); });

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
    expect(screen.getByRole('status')).toHaveTextContent('memory.processing.queued:100');
  });
});
