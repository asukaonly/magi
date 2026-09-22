import type { ReactNode } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  invoke: vi.fn(), initialize: vi.fn(), reset: vi.fn(), diagnostics: vi.fn(),
  maintenance: vi.fn(), config: vi.fn(), configure: vi.fn(), savedChats: vi.fn(),
  appMounted: vi.fn(), desktopSync: vi.fn(), updateCheck: vi.fn(),
  runtime: {
    serverId: '84d6906c-a6c3-4d63-ab56-544a1cfd20a0',
    profileId: 'd342e331-8f68-4268-935b-d45840c06581',
    dataEpoch: 'original-data', contentEpoch: 'original-content',
    connectionGeneration: 1, apiBaseUrl: 'https://center.example/api', sessionToken: 'test-session',
  },
}));

vi.mock('@tauri-apps/api/core', () => ({ invoke: mocks.invoke }));
vi.mock('@/runtime/config', () => ({
  initializeRuntime: mocks.initialize,
  resetRuntimeInitialization: mocks.reset,
  readConnectionStartupDiagnostics: mocks.diagnostics,
  getRuntimeConfig: () => mocks.runtime,
  getRuntimeGeneration: () => 1,
  assertRuntimeGeneration: vi.fn(),
  subscribeRuntimeReconnect: () => () => undefined,
}));
vi.mock('@/runtime/service-recovery', () => ({ observeLocalServiceRecovery: () => () => undefined }));
vi.mock('@/api/client', () => ({ configureApiClient: mocks.configure }));
vi.mock('@/api/modules/config', () => ({ configApi: { get: mocks.config } }));
vi.mock('@/hooks/clearAllMemory', () => ({ recoverPendingCenterMaintenance: mocks.maintenance }));
vi.mock('@/runtime/chat-read-cache', () => ({ savedOfflineChats: mocks.savedChats }));
vi.mock('@/runtime/desktop', () => ({
  syncCloseToTrayPreference: mocks.desktopSync,
  syncAutoStartPreference: mocks.desktopSync,
  syncStartMinimizedPreference: mocks.desktopSync,
  syncSkipQuitConfirmationPreference: mocks.desktopSync,
  syncOnboardingCompleted: mocks.desktopSync,
  applyStartMinimized: mocks.desktopSync,
}));
vi.mock('@/runtime/desktop-notifications', () => ({ syncDesktopNotificationPreferences: vi.fn() }));
vi.mock('@/runtime/updater', () => ({ scheduleStartupUpdateCheck: mocks.updateCheck }));
vi.mock('@/App', () => ({ default: () => { mocks.appMounted(); return <main>Live application</main>; } }));
vi.mock('@/components/layout/PreAppWindowFrame', () => ({ PreAppWindowFrame: ({ children }: { children: ReactNode }) => <>{children}</> }));
vi.mock('@/components/onboarding/ConnectionOnboarding', () => ({
  ConnectionOnboarding: ({ initialStep }: { initialStep: string }) => <main>Onboarding: {initialStep}</main>,
}));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }) }));
vi.mock('@/i18n', () => ({ default: { t: (key: string) => key, language: 'en' } }));

import { RuntimeBootstrap } from '@/components/connections/RuntimeBootstrap';
import { centerLocalStorage, setCenterStorageScope } from '@/runtime/center-storage';

const profile = {
  id: mocks.runtime.profileId, mode: 'remote' as const, name: 'Saved center',
  api_base_url: mocks.runtime.apiBaseUrl, server_id: mocks.runtime.serverId,
  client_id: '8c963d0b-e4ba-415c-84a4-342317ab3521',
};
const descriptor = () => ({
  version: 1, profileId: profile.id, mode: 'remote', serverId: profile.server_id,
  dataEpoch: mocks.runtime.dataEpoch, contentEpoch: mocks.runtime.contentEpoch, verifiedAtMs: Date.now(),
});
const blockedKey = `magi.offline.blocked.${profile.server_id}`;

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => { resolve = resolvePromise; reject = rejectPromise; });
  return { promise, resolve, reject };
}

async function openSavedChats() {
  const button = await screen.findByRole('button', { name: 'offline.open' });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  await screen.findByTestId('offline-chat-view');
}

describe('offline startup boundary', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    window.localStorage.clear();
    window.sessionStorage.clear();
    mocks.runtime.dataEpoch = 'original-data';
    mocks.runtime.contentEpoch = 'original-content';
    setCenterStorageScope(profile.server_id, mocks.runtime.contentEpoch);
    mocks.initialize.mockRejectedValue('center_network_unavailable');
    mocks.diagnostics.mockResolvedValue(null);
    mocks.maintenance.mockResolvedValue(false);
    mocks.config.mockResolvedValue({ data: { preferences: { onboarding_completed: true } } });
    mocks.desktopSync.mockResolvedValue(undefined);
    mocks.updateCheck.mockResolvedValue(undefined);
    mocks.savedChats.mockReturnValue([{
      sessionId: 'saved-session', title: 'Saved conversation', checkedAt: Date.now(),
      history: {
        data: { has_more: false, messages: [{ message_id: 'saved-message', role: 'assistant', timestamp: 1, content: 'Saved reply' }] },
      },
    }]);
    mocks.invoke.mockImplementation(async (command: string) => {
      if (command === 'list_connection_profiles') return { state: { version: 1, active_profile_id: profile.id, profiles: [profile] }, supports_remote: true };
      if (command === 'read_offline_connection' || command === 'confirm_offline_connection') return descriptor();
      if (command === 'invalidate_offline_connection') return undefined;
      throw new Error(`Unexpected native command: ${command}`);
    });
  });

  afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });

  it('offers saved chats without automatically mounting either chat surface', async () => {
    render(<RuntimeBootstrap />);
    await screen.findByRole('button', { name: 'offline.open' });
    expect(screen.queryByTestId('offline-chat-view')).not.toBeInTheDocument();
    expect(screen.queryByText('Live application')).not.toBeInTheDocument();
    expect(mocks.savedChats).not.toHaveBeenCalled();
    expect(mocks.config).not.toHaveBeenCalled();
    expect(mocks.maintenance).not.toHaveBeenCalled();
    expect(mocks.appMounted).not.toHaveBeenCalled();
  });

  it.each(['absent', 'wrong-center', 'blocked', 'pending-maintenance'] as const)('does not offer an unauthorized %s snapshot', async (reason) => {
    const invoke = mocks.invoke.getMockImplementation()!;
    mocks.invoke.mockImplementation(async (command: string) => {
      if (command === 'read_offline_connection' && reason === 'absent') return null;
      if (command === 'read_offline_connection' && reason === 'wrong-center') return { ...descriptor(), serverId: '5b3b0920-e8e0-4687-900d-ea39b9719646' };
      return invoke(command);
    });
    if (reason === 'blocked') window.localStorage.setItem(blockedKey, 'true');
    if (reason === 'pending-maintenance') centerLocalStorage().setItem('maintenance.pending-clear', 'pending-operation');
    render(<RuntimeBootstrap />);
    await screen.findByRole('heading', { name: 'bootstrap.startupFailed' });
    await waitFor(() => expect(mocks.diagnostics).toHaveBeenCalledOnce());
    expect(screen.queryByRole('button', { name: 'offline.open' })).not.toBeInTheDocument();
    expect(mocks.savedChats).not.toHaveBeenCalled();
    expect(mocks.appMounted).not.toHaveBeenCalled();
  });

  it('opens the dedicated saved-chat view only after an explicit choice', async () => {
    render(<RuntimeBootstrap />);
    await openSavedChats();
    expect(screen.getByText('Saved reply')).toBeInTheDocument();
    expect(screen.getByText('offline.notice')).toBeInTheDocument();
    expect(screen.getByText('Saved center')).toBeInTheDocument();
    expect(screen.queryByText('Live application')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /send|delete|clear|settings/i })).not.toBeInTheDocument();
    expect(mocks.config).not.toHaveBeenCalled();
    expect(mocks.desktopSync).not.toHaveBeenCalled();
    expect(mocks.invoke.mock.calls.map(([command]) => command)).toEqual(['list_connection_profiles', 'read_offline_connection']);
  });

  it('keeps the saved snapshot mounted during and after a failed reconnect', async () => {
    render(<RuntimeBootstrap />);
    await openSavedChats();
    const pending = deferred<typeof mocks.runtime>();
    mocks.initialize.mockReturnValueOnce(pending.promise);
    fireEvent.click(screen.getByRole('button', { name: 'offline.reconnect' }));
    await waitFor(() => expect(mocks.initialize).toHaveBeenCalledTimes(2));
    expect(screen.getByText('Saved reply')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'offline.reconnecting' })).toBeDisabled();
    await act(async () => { pending.reject('center_network_unavailable'); });
    await waitFor(() => expect(screen.getByRole('button', { name: 'offline.reconnect' })).toBeEnabled());
    expect(screen.getByText('Saved reply')).toBeInTheDocument();
    expect(mocks.savedChats).toHaveBeenCalledOnce();
    expect(mocks.appMounted).not.toHaveBeenCalled();
    expect(mocks.reset).toHaveBeenCalledOnce();
  });

  it('closes saved chats when reconnect refuses authentication and native authorization is revoked', async () => {
    render(<RuntimeBootstrap />);
    await openSavedChats();
    mocks.initialize.mockRejectedValueOnce('invalid_client_credential');
    const invoke = mocks.invoke.getMockImplementation()!;
    mocks.invoke.mockImplementation(async (command: string) => command === 'read_offline_connection' ? null : invoke(command));
    fireEvent.click(screen.getByRole('button', { name: 'offline.reconnect' }));
    await screen.findByText('connections.errors.deviceCredential');
    await waitFor(() => expect(screen.queryByTestId('offline-chat-view')).not.toBeInTheDocument());
    expect(screen.queryByRole('button', { name: 'offline.open' })).not.toBeInTheDocument();
    expect(mocks.appMounted).not.toHaveBeenCalled();
  });

  it('allows changing connections during a pending reconnect and ignores its late success', async () => {
    render(<RuntimeBootstrap />);
    await openSavedChats();
    const pending = deferred<typeof mocks.runtime>();
    mocks.initialize.mockReturnValueOnce(pending.promise);
    fireEvent.click(screen.getByRole('button', { name: 'offline.reconnect' }));
    await waitFor(() => expect(mocks.initialize).toHaveBeenCalledTimes(2));
    expect(screen.getByRole('button', { name: 'offline.reconnecting' })).toBeDisabled();
    const changeConnection = screen.getByRole('button', { name: 'connections.change' });
    expect(changeConnection).toBeEnabled();
    fireEvent.click(changeConnection);
    await screen.findByText('Onboarding: location');
    expect(screen.queryByTestId('offline-chat-view')).not.toBeInTheDocument();
    await act(async () => { pending.resolve(mocks.runtime); });
    expect(screen.getByText('Onboarding: location')).toBeInTheDocument();
    expect(mocks.appMounted).not.toHaveBeenCalled();
    expect(mocks.maintenance).not.toHaveBeenCalled();
    expect(mocks.config).not.toHaveBeenCalled();
    expect(mocks.invoke).not.toHaveBeenCalledWith('invalidate_offline_connection', expect.anything());
    expect(mocks.invoke).not.toHaveBeenCalledWith('confirm_offline_connection', expect.anything());
    expect(mocks.reset).toHaveBeenCalledTimes(2);
  });

  it('allows verified live access when browser storage is full after native invalidation succeeds', async () => {
    mocks.initialize.mockResolvedValue(mocks.runtime);
    const invalidation = deferred<void>();
    const invoke = mocks.invoke.getMockImplementation()!;
    mocks.invoke.mockImplementation(async (command: string) => command === 'invalidate_offline_connection' ? invalidation.promise : invoke(command));
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('Storage is full', 'QuotaExceededError');
    });
    render(<RuntimeBootstrap />);
    await waitFor(() => expect(mocks.invoke).toHaveBeenCalledWith('invalidate_offline_connection', { connectionGeneration: 1 }));
    expect(setItem).toHaveBeenCalledWith(blockedKey, 'true');
    expect(mocks.maintenance).not.toHaveBeenCalled();
    expect(mocks.appMounted).not.toHaveBeenCalled();
    await act(async () => { invalidation.resolve(); });
    await screen.findByText('Live application');
    expect(mocks.maintenance).toHaveBeenCalledOnce();
    expect(mocks.invoke).toHaveBeenCalledWith('confirm_offline_connection', { connectionGeneration: 1 });
    expect(screen.queryByRole('heading', { name: 'bootstrap.startupFailed' })).not.toBeInTheDocument();
  });

  it('waits for maintenance and durable confirmation before replacing saved chats with the live application', async () => {
    render(<RuntimeBootstrap />);
    await openSavedChats();
    const maintenance = deferred<boolean>();
    const confirmation = deferred<ReturnType<typeof descriptor>>();
    mocks.initialize.mockResolvedValue(mocks.runtime);
    mocks.maintenance.mockReturnValue(maintenance.promise);
    const invoke = mocks.invoke.getMockImplementation()!;
    mocks.invoke.mockImplementation(async (command: string) => command === 'confirm_offline_connection' ? confirmation.promise : invoke(command));
    fireEvent.click(screen.getByRole('button', { name: 'offline.reconnect' }));
    await waitFor(() => expect(mocks.maintenance).toHaveBeenCalledOnce());
    expect(window.localStorage.getItem(blockedKey)).toBe('true');
    expect(mocks.invoke).not.toHaveBeenCalledWith('confirm_offline_connection', expect.anything());
    expect(mocks.appMounted).not.toHaveBeenCalled();
    expect(screen.queryByTestId('offline-chat-view')).not.toBeInTheDocument();
    await act(async () => { maintenance.resolve(false); });
    await waitFor(() => expect(mocks.invoke).toHaveBeenCalledWith('confirm_offline_connection', { connectionGeneration: 1 }));
    expect(mocks.appMounted).not.toHaveBeenCalled();
    expect(mocks.config).not.toHaveBeenCalled();
    await act(async () => { confirmation.resolve(descriptor()); });
    await screen.findByText('Live application');
    expect(window.localStorage.getItem(blockedKey)).toBeNull();
    expect(mocks.config).toHaveBeenCalledOnce();
  });

  it('removes the previous content epoch and finishes device cleanup before entering the live application', async () => {
    centerLocalStorage().setItem('chat_session_active', 'old-private-history');
    const oldKey = `magi.center.${profile.server_id}.original-content.chat_session_active`;
    const maintenance = deferred<boolean>();
    mocks.runtime.contentEpoch = 'cleared-content';
    mocks.runtime.dataEpoch = 'cleared-data';
    mocks.initialize.mockResolvedValue(mocks.runtime);
    mocks.maintenance.mockReturnValue(maintenance.promise);
    render(<RuntimeBootstrap />);
    await waitFor(() => expect(mocks.maintenance).toHaveBeenCalledOnce());
    expect(window.localStorage.getItem(oldKey)).toBeNull();
    expect(centerLocalStorage().getItem('maintenance.device-cleanup')).toBe('pending');
    expect(window.localStorage.getItem(blockedKey)).toBe('true');
    expect(mocks.appMounted).not.toHaveBeenCalled();
    await act(async () => {
      centerLocalStorage().removeItem('maintenance.device-cleanup');
      maintenance.resolve(false);
    });
    await screen.findByText('Live application');
    expect(window.localStorage.getItem(oldKey)).toBeNull();
    expect(window.localStorage.getItem(blockedKey)).toBeNull();
  });

  it('keeps both the application and saved chats closed when maintenance fails', async () => {
    mocks.initialize.mockResolvedValue(mocks.runtime);
    mocks.maintenance.mockRejectedValue(new Error('Device cleanup is incomplete'));
    render(<RuntimeBootstrap />);
    await screen.findByText('Device cleanup is incomplete');
    await waitFor(() => expect(mocks.diagnostics).toHaveBeenCalledOnce());
    expect(window.localStorage.getItem(blockedKey)).toBe('true');
    expect(screen.queryByRole('button', { name: 'offline.open' })).not.toBeInTheDocument();
    expect(mocks.invoke).not.toHaveBeenCalledWith('confirm_offline_connection', expect.anything());
    expect(mocks.appMounted).not.toHaveBeenCalled();
  });

  it('keeps startup blocked when confirmed offline identity no longer matches the live connection', async () => {
    mocks.initialize.mockResolvedValue(mocks.runtime);
    const invoke = mocks.invoke.getMockImplementation()!;
    mocks.invoke.mockImplementation(async (command: string) => {
      if (command === 'confirm_offline_connection') return { ...descriptor(), dataEpoch: 'unexpected-data' };
      if (command === 'invalidate_offline_connection') return undefined;
      return invoke(command);
    });
    render(<RuntimeBootstrap />);
    await screen.findByText('Center data changed during connection; reconnect to refresh it');
    await waitFor(() => expect(mocks.diagnostics).toHaveBeenCalledOnce());
    expect(mocks.invoke).toHaveBeenCalledWith('invalidate_offline_connection', { connectionGeneration: 1 });
    expect(window.localStorage.getItem(blockedKey)).toBe('true');
    expect(screen.queryByRole('button', { name: 'offline.open' })).not.toBeInTheDocument();
    expect(mocks.appMounted).not.toHaveBeenCalled();
  });

  it('opens onboarding without attempting live or saved access when no profile is selected', async () => {
    mocks.invoke.mockResolvedValue({ state: { version: 1, active_profile_id: null, profiles: [] }, supports_remote: true });
    render(<RuntimeBootstrap />);
    await screen.findByText('Onboarding: welcome');
    expect(mocks.initialize).not.toHaveBeenCalled();
    expect(mocks.invoke).toHaveBeenCalledExactlyOnceWith('list_connection_profiles');
    expect(screen.queryByRole('button', { name: 'offline.open' })).not.toBeInTheDocument();
    expect(mocks.appMounted).not.toHaveBeenCalled();
  });
});
