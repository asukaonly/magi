import { act } from 'react';
import { MemoryRouter, useLocation } from 'react-router';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import ShellOverlays from '@/components/layout/ShellOverlays';
import DesktopQuitPrompt from '@/components/layout/DesktopQuitPrompt';
import { useChatShellStore } from '@/stores';

const {
  confirmExitAppMock,
  cancelExitRequestMock,
  registerDesktopOpenSettingsHandlerMock,
  registerDesktopQuitHandlerMock,
  syncSkipQuitConfirmationPreferenceMock,
  configApiGetMock,
  configApiUpdateMock,
} = vi.hoisted(() => ({
  confirmExitAppMock: vi.fn(),
  cancelExitRequestMock: vi.fn(),
  registerDesktopOpenSettingsHandlerMock: vi.fn(),
  registerDesktopQuitHandlerMock: vi.fn(),
  syncSkipQuitConfirmationPreferenceMock: vi.fn(),
  configApiGetMock: vi.fn(),
  configApiUpdateMock: vi.fn(),
}));

let openSettingsHandler: (() => void) | null = null;
let requestQuitHandler: (() => void) | null = null;

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock('@/components/layout/SettingsCenterDialog', () => ({
  default: ({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) => (
    <div data-testid="settings-center-dialog">
      {open ? 'open' : 'closed'}
      <button type="button" onClick={() => onOpenChange(false)}>close settings</button>
    </div>
  ),
}));

const LocationProbe = () => {
  const location = useLocation();
  return <div data-testid="location">{`${location.pathname}${location.search}`}</div>;
};

vi.mock('@/runtime/desktop', () => ({
  registerDesktopOpenSettingsHandler: registerDesktopOpenSettingsHandlerMock,
  registerDesktopQuitHandler: registerDesktopQuitHandlerMock,
  confirmExitApp: confirmExitAppMock,
  cancelExitRequest: cancelExitRequestMock,
  syncSkipQuitConfirmationPreference: syncSkipQuitConfirmationPreferenceMock,
}));

vi.mock('@/api/modules/config', async () => {
  const actual = await vi.importActual<typeof import('@/api/modules/config')>('@/api/modules/config');
  return {
    ...actual,
    configApi: {
      ...actual.configApi,
      get: configApiGetMock,
      update: configApiUpdateMock,
    },
  };
});

describe('shell overlays', () => {
  beforeEach(() => {
    openSettingsHandler = null;
    requestQuitHandler = null;
    confirmExitAppMock.mockReset();
    cancelExitRequestMock.mockReset();
    registerDesktopOpenSettingsHandlerMock.mockReset();
    registerDesktopQuitHandlerMock.mockReset();
    syncSkipQuitConfirmationPreferenceMock.mockReset();
    configApiGetMock.mockReset();
    configApiUpdateMock.mockReset();
    registerDesktopOpenSettingsHandlerMock.mockImplementation(async (handler: () => void) => {
      openSettingsHandler = handler;
      return vi.fn();
    });
    registerDesktopQuitHandlerMock.mockImplementation(async (handler: () => void) => {
      requestQuitHandler = handler;
      return vi.fn();
    });
    useChatShellStore.setState({
      currentSessionId: null,
      activePanel: 'none',
      settingsNavigationIntent: null,
    });
  });

  it('opens settings when the desktop shell requests it', async () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ShellOverlays />
      </MemoryRouter>
    );

    expect(await screen.findByTestId('settings-center-dialog')).toHaveTextContent('closed');

    await act(async () => {
      openSettingsHandler?.();
    });

    expect(screen.getByTestId('settings-center-dialog')).toHaveTextContent('open');
  });

  it('closes settings without changing the current route', async () => {
    const user = userEvent.setup();
    useChatShellStore.setState({
      currentSessionId: null,
      activePanel: 'settings',
    });

    render(
      <MemoryRouter initialEntries={[{
        pathname: '/tasks',
        search: '?tab=scheduled',
      }]}
      >
        <ShellOverlays />
        <LocationProbe />
      </MemoryRouter>
    );

    expect(await screen.findByTestId('settings-center-dialog')).toHaveTextContent('open');

    await user.click(screen.getByRole('button', { name: 'close settings' }));

    expect(screen.getByTestId('location')).toHaveTextContent('/tasks?tab=scheduled');
    expect(useChatShellStore.getState().activePanel).toBe('none');
  });

  it('shows quit confirmation and forwards confirm and cancel actions', async () => {
    const user = userEvent.setup();

    render(
      <DesktopQuitPrompt />
    );

    await act(async () => {
      requestQuitHandler?.();
    });

    expect(await screen.findByText('desktop.quitConfirm.title')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'desktop.quitConfirm.cancel' }));
    expect(cancelExitRequestMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      requestQuitHandler?.();
    });

    await user.click(screen.getByRole('button', { name: 'desktop.quitConfirm.confirm' }));
    expect(confirmExitAppMock).toHaveBeenCalledTimes(1);
    expect(syncSkipQuitConfirmationPreferenceMock).not.toHaveBeenCalled();
  });

  it('persists the skip-confirmation preference when the user opts out', async () => {
    const user = userEvent.setup();
    configApiGetMock.mockResolvedValue({
      data: { preferences: { skip_quit_confirmation: false } },
    });
    configApiUpdateMock.mockResolvedValue({ data: { preferences: { skip_quit_confirmation: true } } });

    render(
      <DesktopQuitPrompt />
    );

    await act(async () => {
      requestQuitHandler?.();
    });

    const checkbox = await screen.findByRole('checkbox', { name: 'desktop.quitConfirm.dontAskAgain' });
    await user.click(checkbox);
    await user.click(screen.getByRole('button', { name: 'desktop.quitConfirm.confirm' }));

    expect(syncSkipQuitConfirmationPreferenceMock).toHaveBeenCalledWith(true);
    expect(configApiUpdateMock).toHaveBeenCalledTimes(1);
    const updateArg = configApiUpdateMock.mock.calls[0][0];
    expect(updateArg.preferences.skip_quit_confirmation).toBe(true);
    expect(confirmExitAppMock).toHaveBeenCalledTimes(1);
  });

  it('cancels the pending quit request when the prompt close button is used', async () => {
    const user = userEvent.setup();

    render(
      <DesktopQuitPrompt />
    );

    await act(async () => {
      requestQuitHandler?.();
    });

    await user.click(await screen.findByRole('button', { name: 'desktop.quitConfirm.closeLabel' }));

    expect(cancelExitRequestMock).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('desktop.quitConfirm.title')).not.toBeInTheDocument();
  });
});
