import { MemoryRouter } from 'react-router-dom';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, beforeEach, vi } from 'vitest';
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
});
