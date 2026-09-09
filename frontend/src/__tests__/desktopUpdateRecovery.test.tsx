import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  invoke: vi.fn(), reconnect: vi.fn(), check: vi.fn(), download: vi.fn(),
  install: vi.fn(), close: vi.fn(), error: vi.fn(),
  t: (key: string) => key,
}));
vi.mock('@tauri-apps/api/core', () => ({ invoke: mocks.invoke }));
vi.mock('@/runtime/config', () => ({ requestRuntimeReconnect: mocks.reconnect }));
vi.mock('@/runtime/updater', () => ({
  checkForAppUpdate: mocks.check,
  DEFAULT_UPDATE_CHECK_TIMEOUT_MS: 15_000,
  getCurrentAppVersion: async () => '0.1.29',
  isUpdaterRuntimeAvailable: () => true,
  restartToApplyUpdate: vi.fn(),
}));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: mocks.t }) }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: mocks.error } }));
import { DesktopUpdateSection } from '@/components/settings/DesktopUpdateSection';

beforeEach(() => {
  vi.clearAllMocks();
  mocks.invoke.mockResolvedValue(undefined);
  mocks.download.mockResolvedValue(undefined);
  mocks.install.mockResolvedValue(undefined);
  mocks.close.mockResolvedValue(undefined);
  mocks.check.mockResolvedValue({
    currentVersion: '0.1.29',
    update: { version: '0.1.30', download: mocks.download, install: mocks.install, close: mocks.close },
  });
});
afterEach(() => vi.useRealTimers());

async function installUpdate() {
  render(<DesktopUpdateSection />);
  fireEvent.click(screen.getByRole('button', { name: 'settings.updates.checkAction' }));
  const install = await screen.findByRole('button', { name: 'settings.updates.installAction' });
  await waitFor(() => expect(install).not.toBeDisabled());
  vi.useFakeTimers();
  await act(async () => {
    fireEvent.click(install);
    await vi.advanceTimersByTimeAsync(600);
  });
}

describe('desktop update connection recovery', () => {
  it('restarts app bootstrap after an installer failure instead of bypassing client initialization', async () => {
    mocks.install.mockRejectedValue(new Error('Installer could not replace files'));
    await installUpdate();
    expect(mocks.invoke.mock.calls.map(([command]) => command)).toEqual(['disconnect_service']);
    expect(mocks.install).toHaveBeenCalledOnce();
    expect(mocks.error).toHaveBeenCalledWith('settings.updates.installFailed');
    expect(mocks.reconnect).toHaveBeenCalledOnce();
  });

  it('keeps the existing connection when download fails before disconnect', async () => {
    mocks.download.mockRejectedValue(new Error('Download interrupted'));
    await installUpdate();
    expect(mocks.invoke).not.toHaveBeenCalled();
    expect(mocks.install).not.toHaveBeenCalled();
    expect(mocks.reconnect).not.toHaveBeenCalled();
  });

  it('does not restart a service when installation succeeds', async () => {
    await installUpdate();
    expect(mocks.invoke).toHaveBeenCalledWith('disconnect_service');
    expect(mocks.install).toHaveBeenCalledOnce();
    expect(mocks.reconnect).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'settings.updates.restartAction' })).toBeInTheDocument();
  });
});
