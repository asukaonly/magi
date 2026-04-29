import { act } from 'react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import ShellOverlays from '@/components/layout/ShellOverlays';
import { useChatShellStore } from '@/stores';

const {
  confirmExitAppMock,
  cancelExitRequestMock,
  registerDesktopShellHandlersMock,
} = vi.hoisted(() => ({
  confirmExitAppMock: vi.fn(),
  cancelExitRequestMock: vi.fn(),
  registerDesktopShellHandlersMock: vi.fn(),
}));

let desktopHandlers: {
  onOpenSettings: () => void;
  onRequestQuit: () => void;
} | null = null;

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
  registerDesktopShellHandlers: registerDesktopShellHandlersMock,
  confirmExitApp: confirmExitAppMock,
  cancelExitRequest: cancelExitRequestMock,
}));

describe('shell overlays', () => {
  beforeEach(() => {
    desktopHandlers = null;
    confirmExitAppMock.mockReset();
    cancelExitRequestMock.mockReset();
    registerDesktopShellHandlersMock.mockReset();
    registerDesktopShellHandlersMock.mockImplementation(async (handlers: typeof desktopHandlers) => {
      desktopHandlers = handlers;
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
      desktopHandlers?.onOpenSettings();
    });

    expect(screen.getByTestId('settings-center-dialog')).toHaveTextContent('open');
  });

  it('returns to the opening route when settings closes', async () => {
    const user = userEvent.setup();
    useChatShellStore.setState({
      currentSessionId: null,
      activePanel: 'settings',
    });

    render(
      <MemoryRouter initialEntries={[{
        pathname: '/settings',
        search: '?section=timeline&source=screen_time',
        state: { returnTo: '/tasks?tab=scheduled' },
      }]}
      >
        <ShellOverlays />
        <LocationProbe />
      </MemoryRouter>
    );

    expect(await screen.findByTestId('settings-center-dialog')).toHaveTextContent('open');

    await user.click(screen.getByRole('button', { name: 'close settings' }));

    expect(screen.getByTestId('location')).toHaveTextContent('/tasks?tab=scheduled');
  });

  it('shows quit confirmation and forwards confirm and cancel actions', async () => {
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ShellOverlays />
      </MemoryRouter>
    );

    await act(async () => {
      desktopHandlers?.onRequestQuit();
    });

    expect(await screen.findByText('desktop.quitConfirm.title')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'desktop.quitConfirm.cancel' }));
    expect(cancelExitRequestMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      desktopHandlers?.onRequestQuit();
    });

    await user.click(screen.getByRole('button', { name: 'desktop.quitConfirm.confirm' }));
    expect(confirmExitAppMock).toHaveBeenCalledTimes(1);
  });
});
