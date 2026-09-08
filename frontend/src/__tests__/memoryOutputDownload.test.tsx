import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
const { invoke } = vi.hoisted(() => ({ invoke: vi.fn() }));
vi.mock('@tauri-apps/api/core', () => ({ invoke }));
vi.mock('@/runtime/config', () => ({ getRuntimeConfig: () => ({ profileId: 'center-profile' }), getRuntimeGeneration: () => 1 }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
import { MemoryOutputDownload } from '@/components/settings/memory-data/MemoryOutputDownload';
beforeEach(() => vi.clearAllMocks());
it('saves by operation identity and allows retry after a failed transfer', async () => {
  invoke.mockRejectedValueOnce(new Error('Interrupted')).mockResolvedValueOnce('/client/backup.magibackup');
  render(<MemoryOutputDownload operationId="operation" />);
  fireEvent.click(screen.getByText('centerFiles.download'));
  expect(await screen.findByRole('alert')).toHaveTextContent('centerFiles.downloadFailed');
  fireEvent.click(screen.getByText('centerFiles.download'));
  expect(await screen.findByRole('status')).toHaveTextContent('centerFiles.downloadSaved');
  expect(invoke).toHaveBeenCalledWith('download_portability_file', { operationId: 'operation', profileId: 'center-profile' });
});
it('ignores completion belonging to a previous operation', async () => {
  let resolve!: (value: string) => void;
  invoke.mockReturnValue(new Promise(done => { resolve = done; }));
  const view = render(<MemoryOutputDownload operationId="old" />);
  fireEvent.click(screen.getByText('centerFiles.download'));
  await waitFor(() => expect(screen.getByRole('button')).toBeDisabled());
  view.rerender(<MemoryOutputDownload operationId="new" />);
  await act(async () => resolve('/client/old.magibackup'));
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
  expect(screen.getByRole('button')).toBeEnabled();
});
