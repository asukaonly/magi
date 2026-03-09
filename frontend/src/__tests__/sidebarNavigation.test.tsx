import { MemoryRouter } from 'react-router-dom';
import { act, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, beforeEach, vi } from 'vitest';
import { messagesApi } from '@/api';
import Sidebar from '@/components/layout/Sidebar';
import { useChatShellStore } from '@/stores';

vi.mock('@/api', () => ({
  messagesApi: {
    listSessions: vi.fn().mockResolvedValue({
      sessions: [],
      current_session_id: null,
    }),
    createNewSession: vi.fn(),
  },
}));

describe('sidebar navigation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useChatShellStore.setState({
      currentSessionId: null,
      sidebarCollapsed: false,
      activePanel: 'none',
    });
  });

  it('renders personality, memory, and settings actions', async () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <Sidebar />
      </MemoryRouter>
    );

    expect(await screen.findByRole('button', { name: 'shell.personality' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'shell.memory' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'shell.settings' })).toBeInTheDocument();
  });

  it('refreshes sessions on sync events', async () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <Sidebar />
      </MemoryRouter>
    );

    await waitFor(() => expect(messagesApi.listSessions).toHaveBeenCalledTimes(1));

    await act(async () => {
      window.dispatchEvent(new Event('magi-session-sync'));
    });

    await waitFor(() => expect(messagesApi.listSessions).toHaveBeenCalledTimes(2));
  });
});
