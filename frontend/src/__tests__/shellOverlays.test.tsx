import { act } from 'react';
import { MemoryRouter } from 'react-router-dom';
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
  default: ({ open }: { open: boolean }) => (
    <div data-testid="settings-center-dialog">{open ? 'open' : 'closed'}</div>
  ),
}));

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
