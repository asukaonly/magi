import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// vi.hoisted because vi.mock factories are hoisted above the const
// declaration; runtime/desktop now statically imports these modules, so
// the mock factory runs during the test file's module-evaluation and
// would otherwise hit a TDZ on invokeMock/listenMock.
const { invokeMock, listenMock, dialogOpenMock } = vi.hoisted(() => ({
  invokeMock: vi.fn(),
  listenMock: vi.fn(),
  dialogOpenMock: vi.fn(),
}));

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
  beginFullDataClear,
  cancelExitRequest,
  clearDesktopLogHistory,
  completeFullDataClear,
  confirmExitApp,
  openExternalUrl,
  pickMemoryBackupFile,
  registerDesktopOpenSettingsHandler,
  registerDesktopQuitHandler,
  readPendingFullDataClear,
  syncCloseToTrayPreference,
  syncOnboardingCompleted,
} from '@/runtime/desktop';

describe('desktop runtime bridge', () => {
  beforeEach(() => {
    invokeMock.mockReset();
    listenMock.mockReset();
    dialogOpenMock.mockReset();
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

  it('persists, reads, and completes the desktop-owned full clear marker', async () => {
    (window as Window & { __TAURI_INTERNALS__?: object }).__TAURI_INTERNALS__ = {};
    const marker = { version: 1, transactionId: 'clear-transaction-1234' };
    invokeMock
      .mockResolvedValueOnce(marker)
      .mockResolvedValueOnce(marker)
      .mockResolvedValueOnce(undefined);

    await expect(beginFullDataClear()).resolves.toEqual(marker);
    await expect(readPendingFullDataClear()).resolves.toEqual(marker);
    await expect(completeFullDataClear(marker.transactionId)).resolves.toBeUndefined();

    expect(invokeMock).toHaveBeenNthCalledWith(1, 'begin_full_data_clear');
    expect(invokeMock).toHaveBeenNthCalledWith(2, 'read_pending_full_data_clear');
    expect(invokeMock).toHaveBeenNthCalledWith(3, 'complete_full_data_clear', {
      transactionId: marker.transactionId,
    });
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

  it('refuses to acknowledge a full clear without the desktop owner', async () => {
    await expect(completeFullDataClear('clear-transaction-1234')).rejects.toThrow(
      'Desktop full data clear owner is unavailable',
    );
    expect(invokeMock).not.toHaveBeenCalled();
  });
});
