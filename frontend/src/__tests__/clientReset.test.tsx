import type { ReactNode } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ invoke: vi.fn(), resetRuntime: vi.fn() }));
vi.mock('@tauri-apps/api/core', () => ({ invoke: mocks.invoke }));
vi.mock('@/runtime/config', () => ({ resetRuntimeInitialization: mocks.resetRuntime }));
vi.mock('@/components/layout/PreAppWindowFrame', () => ({ PreAppWindowFrame: ({ children }: { children: ReactNode }) => <>{children}</> }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

const contentKey = 'magi.center.first.epoch.magi.chat.text-drafts.v1';
const secondKey = 'magi.center.second.epoch.magi.chat.read-cache.v1';
const deferred = () => {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => { resolve = done; });
  return { promise, resolve };
};

async function load() {
  const reset = await import('@/runtime/client-reset');
  const navigation = vi.spyOn(reset, 'reopenClientWelcome').mockImplementation(() => undefined);
  const { ClientResetBoundary } = await import('@/components/connections/ClientResetBoundary');
  const { ClientResetAction } = await import('@/components/connections/ClientResetAction');
  render(<ClientResetBoundary><main>Live client<ClientResetAction /></main></ClientResetBoundary>);
  return { reset, navigation };
}

async function confirm() {
  fireEvent.click(await screen.findByRole('button', { name: 'clientReset.title' }));
  const button = screen.getByRole('button', { name: 'clientReset.confirm' });
  expect(button).toBeDisabled();
  fireEvent.click(screen.getByRole('checkbox', { name: 'clientReset.acknowledge' }));
  fireEvent.click(button);
}

describe('device connection and cache reset', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    window.localStorage.clear();
    window.sessionStorage.clear();
    window.localStorage.setItem(contentKey, 'draft');
    window.localStorage.setItem(secondKey, 'cached transcript');
    window.localStorage.setItem('magi.offline.blocked.server', 'true');
    window.localStorage.setItem('magi_language', 'zh');
    window.localStorage.setItem('magi.device.preferences.v1', 'device preferences');
    window.sessionStorage.setItem(secondKey, 'session data');
    mocks.invoke.mockImplementation(async (command: string) => {
      if (command === 'client_reset_pending') return false;
      return undefined;
    });
  });
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it('cancelling confirmation preserves data and does not disconnect', async () => {
    await load();
    fireEvent.click(await screen.findByRole('button', { name: 'clientReset.title' }));
    fireEvent.click(screen.getByRole('button', { name: 'clientReset.cancel' }));
    expect(mocks.invoke).toHaveBeenCalledTimes(1);
    expect(mocks.resetRuntime).not.toHaveBeenCalled();
    expect(window.localStorage.getItem(contentKey)).toBe('draft');
  });

  it('unmounts the live app before resetting and clears all centers only after native success', async () => {
    const native = deferred();
    mocks.invoke.mockImplementation(async (command: string) => command === 'client_reset_pending' ? false
      : command === 'reset_client_connections' ? native.promise : undefined);
    const { navigation } = await load();
    await confirm();
    expect(screen.queryByText('Live client')).not.toBeInTheDocument();
    await waitFor(() => expect(mocks.invoke).toHaveBeenCalledWith('reset_client_connections', { discardPending: true }));
    expect(window.localStorage.getItem(contentKey)).toBe('draft');
    expect(mocks.invoke).not.toHaveBeenCalledWith('complete_client_reset');
    await act(async () => { native.resolve(); await native.promise; });
    await waitFor(() => expect(navigation).toHaveBeenCalledTimes(1));
    expect(window.localStorage.getItem(contentKey)).toBeNull();
    expect(window.localStorage.getItem(secondKey)).toBeNull();
    expect(window.sessionStorage.getItem(secondKey)).toBeNull();
    expect(window.localStorage.getItem('magi.offline.blocked.server')).toBeNull();
    expect(window.localStorage.getItem('magi_language')).toBe('zh');
    expect(window.localStorage.getItem('magi.device.preferences.v1')).toBe('device preferences');
    expect(mocks.invoke.mock.calls.map(([command]) => command)).toEqual([
      'client_reset_pending', 'reset_client_connections', 'complete_client_reset',
    ]);
  });

  it('keeps the cleanup boundary on a browser storage failure and retries safely', async () => {
    const { navigation } = await load();
    const remove = vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => { throw new Error('Denied'); });
    await confirm();
    await screen.findByText('clientReset.failed');
    expect(navigation).not.toHaveBeenCalled();
    expect(mocks.invoke).not.toHaveBeenCalledWith('complete_client_reset');
    expect(screen.queryByText('Live client')).not.toBeInTheDocument();
    remove.mockRestore();
    fireEvent.click(screen.getByRole('button', { name: 'clientReset.retry' }));
    await waitFor(() => expect(navigation).toHaveBeenCalledTimes(1));
    expect(window.localStorage.getItem(contentKey)).toBeNull();
  });

  it('does not claim success or clear browser content when native cleanup fails', async () => {
    mocks.invoke.mockImplementation(async (command: string) => {
      if (command === 'client_reset_pending') return false;
      throw new Error('Storage failed');
    });
    const { navigation } = await load();
    await confirm();
    await screen.findByText('clientReset.failed');
    expect(window.localStorage.getItem(contentKey)).toBe('draft');
    expect(navigation).not.toHaveBeenCalled();
    expect(mocks.invoke).not.toHaveBeenCalledWith('complete_client_reset');
  });

  it('resumes interrupted cleanup before the app can connect on next startup', async () => {
    const native = deferred();
    mocks.invoke.mockImplementation(async (command: string) => command === 'client_reset_pending' ? true
      : command === 'reset_client_connections' ? native.promise : undefined);
    const { navigation } = await load();
    await screen.findByText('clientReset.progress');
    expect(screen.queryByText('Live client')).not.toBeInTheDocument();
    await act(async () => { native.resolve(); await native.promise; });
    await waitFor(() => expect(navigation).toHaveBeenCalledTimes(1));
    expect(window.localStorage.getItem(contentKey)).toBeNull();
  });

  it('keeps failed finalization retryable after local content is already cleared', async () => {
    let completions = 0;
    mocks.invoke.mockImplementation(async (command: string) => {
      if (command === 'client_reset_pending') return false;
      if (command === 'complete_client_reset' && completions++ === 0) throw new Error('Disk unavailable');
    });
    const { navigation } = await load();
    await confirm();
    await screen.findByText('clientReset.failed');
    expect(window.localStorage.getItem(contentKey)).toBeNull();
    expect(navigation).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'clientReset.retry' }));
    await waitFor(() => expect(navigation).toHaveBeenCalledTimes(1));
  });

  it('keeps startup closed when reset status cannot be inspected, then retries inspection', async () => {
    mocks.invoke.mockRejectedValueOnce(new Error('Unavailable'));
    await load();
    await screen.findByText('clientReset.checkFailed');
    expect(screen.queryByText('Live client')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'clientReset.retry' }));
    await screen.findByText('Live client');
    expect(mocks.invoke).not.toHaveBeenCalledWith('reset_client_connections', expect.anything());
  });
});
