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

  it('renders conversation, timeline, memory, and settings actions without a personality button', async () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <Sidebar />
      </MemoryRouter>
    );

    expect(await screen.findByRole('button', { name: 'shell.conversation' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'shell.memory' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'shell.settings' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'shell.timeline' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'shell.personality' })).not.toBeInTheDocument();
  });

  it('shows conversation search tools and filters visible sessions locally', async () => {
    const user = userEvent.setup();
    vi.mocked(messagesApi.listSessions).mockResolvedValueOnce({
      sessions: [
        {
          session_id: 'session-a',
          title: '杭州天气',
          last_message_preview: '今天有点冷',
          last_timestamp: 10,
          message_count: 1,
        },
        {
          session_id: 'session-b',
          title: '西湖路线',
          last_message_preview: '沿湖散步',
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
          title: '杭州天气',
          last_message_preview: '今天有点冷',
          last_timestamp: 10,
          message_count: 1,
        },
        'session-b': {
          session_id: 'session-b',
          title: '西湖路线',
          last_message_preview: '沿湖散步',
          last_timestamp: 11,
          message_count: 2,
        },
      },
      messagesBySession: {},
      unreadBySession: {},
    });

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <Sidebar />
      </MemoryRouter>
    );

    expect(await screen.findByLabelText('shell.searchSessions')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'shell.newChat' })).toBeInTheDocument();

    await user.type(screen.getByLabelText('shell.searchSessions'), '西湖');

    expect(screen.getByRole('button', { name: '西湖路线' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '杭州天气' })).not.toBeInTheDocument();
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

  it('expands memory destinations and routes to the selected memory page', async () => {
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <Sidebar />
        <LocationProbe />
      </MemoryRouter>
    );

    await user.click(await screen.findByRole('button', { name: 'shell.memory' }));
    await user.click(screen.getByRole('button', { name: 'memory.nav.knowledge' }));

    expect(screen.getByRole('button', { name: 'memory.nav.overview' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.nav.workbench' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.nav.events' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.nav.knowledge' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.nav.reflection' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.nav.skills' })).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/memory/knowledge');
    expect(useChatShellStore.getState().activePanel).toBe('memory');
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

  it('keeps the conversation action close to the shell controls', async () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <Sidebar />
      </MemoryRouter>
    );

    const conversationAction = await screen.findByRole('button', { name: 'shell.conversation' });
    const sidebar = conversationAction.closest('aside');

    expect(sidebar).toHaveClass('pt-14');
  });
});
