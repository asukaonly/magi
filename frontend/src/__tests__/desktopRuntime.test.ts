import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// vi.hoisted because vi.mock factories are hoisted above the const
// declaration; runtime/desktop now statically imports these modules, so
// the mock factory runs during the test file's module-evaluation and
// would otherwise hit a TDZ on invokeMock/listenMock.
const { invokeMock, listenMock } = vi.hoisted(() => ({
  invokeMock: vi.fn(),
  listenMock: vi.fn(),
}));

vi.mock('@tauri-apps/api/core', () => ({
  invoke: invokeMock,
}));

vi.mock('@tauri-apps/api/event', () => ({
  listen: listenMock,
}));

import {
  cancelExitRequest,
  clearDesktopLogHistory,
  confirmExitApp,
  openExternalUrl,
  registerDesktopShellHandlers,
  syncCloseToTrayPreference,
} from '@/runtime/desktop';

describe('desktop runtime bridge', () => {
  beforeEach(() => {
    invokeMock.mockReset();
    listenMock.mockReset();
    delete (window as Window & { __TAURI__?: object }).__TAURI__;
    delete (window as Window & { __TAURI_INTERNALS__?: object }).__TAURI_INTERNALS__;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('registers shell event listeners and forwards open-settings and quit requests', async () => {
    (window as Window & { __TAURI_INTERNALS__?: object }).__TAURI_INTERNALS__ = {};

    const unlisten = vi.fn();
    const listeners = new Map<string, (event: { payload?: unknown }) => void>();
    listenMock.mockImplementation(async (eventName: string, handler: (event: { payload?: unknown }) => void) => {
      listeners.set(eventName, handler);
      return unlisten;
    });

    const onOpenSettings = vi.fn();
    const onRequestQuit = vi.fn();

    const dispose = await registerDesktopShellHandlers({
      onOpenSettings,
      onRequestQuit,
    });

    expect(listenMock).toHaveBeenCalledTimes(2);
    listeners.get('desktop-presence://open-settings')?.({});
    listeners.get('desktop-presence://quit-requested')?.({});

    expect(onOpenSettings).toHaveBeenCalledTimes(1);
    expect(onRequestQuit).toHaveBeenCalledTimes(1);

    await dispose();
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
});
