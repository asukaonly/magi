import { MemoryRouter, useLocation } from 'react-router-dom';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, beforeEach, vi } from 'vitest';
import { messagesApi } from '@/api';
import Sidebar from '@/components/layout/Sidebar';
import { useChatShellStore, useConversationStore } from '@/stores';

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
  const LocationProbe = () => {
    const location = useLocation();
    return <div data-testid="location">{location.pathname}</div>;
  };

  beforeEach(() => {
    vi.clearAllMocks();
    useChatShellStore.setState({
      currentSessionId: null,
      sidebarCollapsed: false,
      activePanel: 'none',
    });
    useConversationStore.getState().reset();
  });

  it('renders personality, memory, settings, and timeline actions', async () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <Sidebar />
      </MemoryRouter>
    );

    expect(await screen.findByRole('button', { name: 'shell.personality' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'shell.memory' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'shell.settings' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'shell.timeline' })).toBeInTheDocument();
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

  it('navigates to the timeline route and updates shell state', async () => {
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <Sidebar />
        <LocationProbe />
      </MemoryRouter>
    );

    await user.click(await screen.findByRole('button', { name: 'shell.timeline' }));

    expect(screen.getByTestId('location')).toHaveTextContent('/timeline');
    expect(useChatShellStore.getState().activePanel).toBe('timeline');
  });

  it('renders unread badges for inactive chat sessions', async () => {
    vi.mocked(messagesApi.listSessions).mockResolvedValueOnce({
      sessions: [
        {
          session_id: 'session-a',
          title: 'Session A',
          last_message_preview: 'hello',
          last_timestamp: 10,
          message_count: 1,
        },
        {
          session_id: 'session-b',
          title: 'Session B',
          last_message_preview: 'new message',
          last_timestamp: 11,
          message_count: 2,
        },
      ],
      current_session_id: 'session-a',
      user_id: 'web_user',
      count: 2,
    });
    useConversationStore.setState({
      currentSessionId: 'session-a',
      orderedSessionIds: ['session-a', 'session-b'],
      sessionsById: {
        'session-a': {
          session_id: 'session-a',
          title: 'Session A',
          last_message_preview: 'hello',
          last_timestamp: 10,
          message_count: 1,
        },
        'session-b': {
          session_id: 'session-b',
          title: 'Session B',
          last_message_preview: 'new message',
          last_timestamp: 11,
          message_count: 2,
        },
      },
      messagesBySession: {},
      unreadBySession: {
        'session-b': 3,
      },
    });

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <Sidebar />
      </MemoryRouter>
    );

    expect(await screen.findByText('3')).toBeInTheDocument();
  });

  it('keeps the chat header close to the shell controls', async () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <Sidebar />
      </MemoryRouter>
    );

    const navLabel = await screen.findByText('nav.chat');
    const sidebar = navLabel.closest('aside');

    expect(sidebar).toHaveClass('pt-14');
  });
});
