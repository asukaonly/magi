import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import AppShellProviders from '@/components/layout/AppShellProviders';

vi.mock('@/runtime/config', () => ({
  getRuntimeConfig: () => ({
    isDesktop: false,
    apiBaseUrl: 'http://localhost:8000/api',
    wsBaseUrl: 'ws://localhost:8000',
    sessionToken: 'test-token',
  }),
}));

describe('realtime provider', () => {
  const socketMock = {
    readyState: 0,
    send: vi.fn(),
    close: vi.fn(),
    onopen: null as ((event: Event) => void) | null,
    onmessage: null as ((event: MessageEvent) => void) | null,
    onclose: null as ((event: CloseEvent) => void) | null,
    onerror: null as ((event: Event) => void) | null,
  };

  beforeEach(() => {
    socketMock.readyState = 0;
    socketMock.send.mockReset();
    socketMock.close.mockReset();
    vi.stubGlobal('WebSocket', vi.fn(() => socketMock));
  });

  const NavigationHarness = () => {
    const navigate = useNavigate();
    return (
      <button type="button" onClick={() => navigate('/timeline')}>
        go-timeline
      </button>
    );
  };

  const renderShell = (initialEntry: string) =>
    render(
      <MemoryRouter initialEntries={[initialEntry]}>
        <AppShellProviders>
          <NavigationHarness />
          <Routes>
            <Route path="/chat" element={<div>chat-page</div>} />
            <Route path="/timeline" element={<div>timeline-page</div>} />
          </Routes>
        </AppShellProviders>
      </MemoryRouter>
    );

  it('opens exactly one websocket for the shell', () => {
    renderShell('/chat');

    expect(globalThis.WebSocket).toHaveBeenCalledTimes(1);
  });

  it('keeps the websocket connected when navigating away from chat', async () => {
    const user = userEvent.setup();

    renderShell('/chat');

    expect(globalThis.WebSocket).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('button', { name: 'go-timeline' }));

    expect(globalThis.WebSocket).toHaveBeenCalledTimes(1);
    expect(socketMock.close).not.toHaveBeenCalled();
  });
});
