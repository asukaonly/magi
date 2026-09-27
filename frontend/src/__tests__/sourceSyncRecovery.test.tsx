import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SourceSyncIssue } from '@/components/sources/SourceSyncIssue';
import { SourceSyncHistory } from '@/components/sources/SourceSyncHistory';
import { sourcesApi, type SourceSyncHistory as SyncHistory } from '@/api/modules/sources';
import { api } from '@/api/client';
import { openExternalUrl } from '@/runtime/desktop';

const env = vi.hoisted(() => ({ mode: 'local' }));
vi.mock('@/runtime/config', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/runtime/config')>();
  return { ...actual, getRuntimeConfig: () => ({ ...actual.getRuntimeConfig(), mode: env.mode }) };
});
vi.mock('@/runtime/desktop', () => ({ openExternalUrl: vi.fn() }));
vi.mock('@/hooks/useCenterRefresh', () => ({ useCenterRefresh: vi.fn() }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }) }));
const history = (connectionId = 'account-a'): SyncHistory => ({
  source_name: 'chrome', connection_id: connectionId, total: 1,
  items: [{ job_id: 'job', mode: 'latest', status: 'failed', created_at: 123, started_at: 123,
    finished_at: 124, next_attempt_at: 124, attempt_count: 1, error: 'PermissionError: protected History database',
    failure: { code: 'file_access_denied', platform: 'darwin' } }],
});
beforeEach(() => { env.mode = 'local'; vi.clearAllMocks(); });
afterEach(() => vi.restoreAllMocks());

describe('source sync recovery', () => {
  it('opens only the targeted macOS settings pane on explicit click', async () => {
    render(<SourceSyncIssue message="denied" failure={{ code: 'file_access_denied', platform: 'darwin' }} />);
    expect(openExternalUrl).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'sourceRecovery.openSettings' }));
    await waitFor(() => expect(openExternalUrl).toHaveBeenCalledExactlyOnceWith('x-apple.systempreferences:com.apple.preference.security?Privacy_FilesAndFolders'));
    expect(screen.getByText('denied')).toBeInTheDocument();
  });
  it('directs remote permissions to the center device and never opens client settings', () => {
    env.mode = 'remote';
    render(<SourceSyncIssue message="denied" failure={{ code: 'file_access_denied', platform: 'darwin' }} />);
    expect(screen.getByText('sourceRecovery.remote')).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
  it('does not send Windows or Linux file errors to macOS settings', () => {
    render(<SourceSyncIssue message="denied" failure={{ code: 'file_access_denied', platform: 'win32' }} />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(screen.getByText('sourceRecovery.permissionHelp')).toBeInTheDocument();
  });
  it('uses a declared authorization action and surfaces failures', async () => {
    const authorize = vi.fn().mockRejectedValue(new Error('Authorization declined'));
    render(<SourceSyncIssue message="denied" failure={{ code: 'permission_required', platform: 'darwin' }} onAuthorize={authorize} />);
    fireEvent.click(screen.getByRole('button', { name: 'sourceRecovery.authorize' }));
    expect(await screen.findByText('Authorization declined')).toBeInTheDocument();
    expect(authorize).toHaveBeenCalledOnce();
  });
  it('keeps failure detail available in the sync ledger', async () => {
    vi.spyOn(sourcesApi, 'getSyncHistory').mockResolvedValue(history());
    render(<SourceSyncHistory sourceName="chrome" connectionId="account-a" refreshKey="failed" />);
    expect(await screen.findByText('sourceRecovery.status.failed')).toBeInTheDocument();
    fireEvent.click(screen.getByText('sourceRecovery.permissionTitle'));
    expect(screen.getByText('PermissionError: protected History database')).toBeVisible();
  });
  it('does not let a late previous connection overwrite the current history', async () => {
    let resolve!: (value: SyncHistory) => void;
    vi.spyOn(sourcesApi, 'getSyncHistory').mockReturnValueOnce(new Promise(yes => { resolve = yes; }))
      .mockResolvedValueOnce({ ...history('account-b'), items: [] });
    const view = render(<SourceSyncHistory key="a" sourceName="chrome" connectionId="account-a" refreshKey="" />);
    view.rerender(<SourceSyncHistory key="b" sourceName="chrome" connectionId="account-b" refreshKey="" />);
    await screen.findByText('sourceRecovery.historyEmpty');
    await act(async () => resolve(history()));
    expect(screen.queryByText('sourceRecovery.status.failed')).not.toBeInTheDocument();
  });
  it('validates history identity and rejects malformed response data', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({ success: true, message: '', data: history() });
    await expect(sourcesApi.getSyncHistory('chrome', 'account-a', 20)).resolves.toEqual(history());
    expect(get).toHaveBeenCalledWith('/sources/chrome/sync-history', { params: { connection_id: 'account-a', limit: 20, offset: 20 } });
    await expect(sourcesApi.getSyncHistory('chrome', 'wrong-account')).rejects.toThrow('identity mismatch');
    get.mockResolvedValue({ success: true, message: '', data: { ...history(), total: 'invalid' } });
    await expect(sourcesApi.getSyncHistory('chrome', 'account-a')).rejects.toThrow();
  });
});
