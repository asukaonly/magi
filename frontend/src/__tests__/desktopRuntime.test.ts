import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// vi.hoisted because vi.mock factories are hoisted above the const
// declaration; runtime/desktop now statically imports these modules, so
// the mock factory runs during the test file's module-evaluation and
// would otherwise hit a TDZ on invokeMock/listenMock.
const { invokeMock, listenMock, dialogOpenMock, autostart } = vi.hoisted(() => ({
  invokeMock: vi.fn(),
  listenMock: vi.fn(),
  dialogOpenMock: vi.fn(),
  autostart: { enable: vi.fn(), disable: vi.fn(), isEnabled: vi.fn() },
}));
vi.mock('@tauri-apps/plugin-autostart', () => autostart);
import { useDesktopPreferencesStore } from '@/stores/desktop-preferences';

vi.mock('@tauri-apps/api/core', () => ({
  invoke: invokeMock,
}));

vi.mock('@tauri-apps/api/event', () => ({
  listen: listenMock,
}));

vi.mock('@tauri-apps/plugin-dialog', () => ({
  open: dialogOpenMock,
}));

import {
  cancelExitRequest,
  clearDesktopLogHistory,
  confirmExitApp,
  openExternalUrl,
  pickMemoryBackupFile,
  registerDesktopOpenSettingsHandler,
  registerDesktopQuitHandler,
  syncCloseToTrayPreference,
  syncAutoStartPreference,
  syncOnboardingCompleted,
} from '@/runtime/desktop';

describe('desktop runtime bridge', () => {
  beforeEach(() => {
    invokeMock.mockReset();
    listenMock.mockReset();
    dialogOpenMock.mockReset();
    Object.values(autostart).forEach(mock => mock.mockReset());
    useDesktopPreferencesStore.setState({ autoStartSyncFailed: false });
    delete (window as Window & { __TAURI__?: object }).__TAURI__;
    delete (window as Window & { __TAURI_INTERNALS__?: object }).__TAURI_INTERNALS__;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('registers independent open-settings and quit listeners', async () => {
    (window as Window & { __TAURI_INTERNALS__?: object }).__TAURI_INTERNALS__ = {};

    const unlisten = vi.fn();
    const listeners = new Map<string, (event: { payload?: unknown }) => void>();
    listenMock.mockImplementation(async (eventName: string, handler: (event: { payload?: unknown }) => void) => {
      listeners.set(eventName, handler);
      return unlisten;
    });

    const onOpenSettings = vi.fn();
    const onRequestQuit = vi.fn();

    const disposeOpenSettings = await registerDesktopOpenSettingsHandler(onOpenSettings);
    const disposeQuit = await registerDesktopQuitHandler(onRequestQuit);

    expect(listenMock).toHaveBeenCalledTimes(2);
    listeners.get('desktop-presence://open-settings')?.({});
    listeners.get('desktop-presence://quit-requested')?.({});

    expect(onOpenSettings).toHaveBeenCalledTimes(1);
    expect(onRequestQuit).toHaveBeenCalledTimes(1);

    await disposeOpenSettings();
    await disposeQuit();
    expect(unlisten).toHaveBeenCalledTimes(2);
  });

  it('forwards the close-to-tray preference and quit commands to the desktop shell', async () => {
    (window as Window & { __TAURI_INTERNALS__?: object }).__TAURI_INTERNALS__ = {};

    await syncCloseToTrayPreference(false);
    await confirmExitApp();
    await cancelExitRequest();

    expect(invokeMock).toHaveBeenNthCalledWith(1, 'set_close_to_tray_enabled', { enabled: false });
    expect(invokeMock).toHaveBeenNthCalledWith(2, 'confirm_exit_app');
    expect(invokeMock).toHaveBeenNthCalledWith(3, 'cancel_exit_request');
  });

  it('propagates autostart failures and clears pending status only after verified retry', async () => {
    Object.assign(window, { __TAURI_INTERNALS__: {} });
    autostart.enable.mockRejectedValueOnce(new Error('System denied autostart'));
    await expect(syncAutoStartPreference(true)).rejects.toThrow('System denied autostart');
    expect(useDesktopPreferencesStore.getState().autoStartSyncFailed).toBe(true);
    autostart.isEnabled.mockResolvedValueOnce(false);
    await expect(syncAutoStartPreference(true)).rejects.toThrow('System autostart state did not match');
    expect(useDesktopPreferencesStore.getState().autoStartSyncFailed).toBe(true);
    autostart.isEnabled.mockResolvedValueOnce(true);
    await expect(syncAutoStartPreference(true)).resolves.toBeUndefined();
    expect(useDesktopPreferencesStore.getState().autoStartSyncFailed).toBe(false);
    autostart.isEnabled.mockResolvedValueOnce(false);
    await syncAutoStartPreference(false);
    expect(autostart.disable).toHaveBeenCalledOnce();
  });

  it('forwards the onboarding completion state to the desktop shell', async () => {
    (window as Window & { __TAURI_INTERNALS__?: object }).__TAURI_INTERNALS__ = {};

    await syncOnboardingCompleted(true);

    expect(invokeMock).toHaveBeenCalledWith('set_onboarding_completed', { completed: true });
  });

  it('hands external URLs to the validated desktop command', async () => {
    (window as Window & { __TAURI_INTERNALS__?: object }).__TAURI_INTERNALS__ = {};

    await openExternalUrl('  https://example.com/docs?q=a&next=b|c  ');

    expect(invokeMock).toHaveBeenCalledOnce();
    expect(invokeMock).toHaveBeenCalledWith('open_url', {
      url: 'https://example.com/docs?q=a&next=b|c',
    });
  });

  it('asks the desktop owner to erase its active log files', async () => {
    (window as Window & { __TAURI_INTERNALS__?: object }).__TAURI_INTERNALS__ = {};
    invokeMock.mockResolvedValue({ clearedEntries: 3, failedEntries: 0 });

    await expect(clearDesktopLogHistory()).resolves.toEqual({
      clearedEntries: 3,
      failedEntries: 0,
    });
    expect(invokeMock).toHaveBeenCalledWith('clear_desktop_log_history');
  });

  it('opens the native picker with the Magi backup extension only', async () => {
    (window as Window & { __TAURI_INTERNALS__?: object }).__TAURI_INTERNALS__ = {};
    dialogOpenMock.mockResolvedValue('/Users/example/Memory copy.magibackup');

    await expect(
      pickMemoryBackupFile('Magi memory backup', '/Users/example'),
    ).resolves.toBe('/Users/example/Memory copy.magibackup');

    expect(dialogOpenMock).toHaveBeenCalledWith({
      directory: false,
      multiple: false,
      defaultPath: '/Users/example',
      filters: [{ name: 'Magi memory backup', extensions: ['magibackup'] }],
    });
  });

  it('does not open a backup file picker outside the desktop runtime', async () => {
    await expect(pickMemoryBackupFile('Magi memory backup')).resolves.toBeUndefined();
    expect(dialogOpenMock).not.toHaveBeenCalled();
  });


});
