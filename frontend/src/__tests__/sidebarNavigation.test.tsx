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
      user_id: 'web_user',
      count: 0,
    }),
    createNewSession: vi.fn().mockResolvedValue({
      success: true,
      user_id: 'web_user',
      session_id: null,
    }),
    renameSession: vi.fn(),
    deleteSession: vi.fn(),
  },
}));

describe('sidebar navigation', () => {
  const storage = new Map<string, string>();

  const LocationProbe = () => {
    const location = useLocation();
    return <div data-testid="location">{location.pathname}</div>;
  };

  beforeEach(() => {
    vi.clearAllMocks();
    storage.clear();
    Object.defineProperty(window, 'localStorage', {
      value: {
        getItem: (key: string) => storage.get(key) ?? null,
        setItem: (key: string, value: string) => {
          storage.set(key, value);
        },
        removeItem: (key: string) => {
          storage.delete(key);
        },
      },
      configurable: true,
    });
    useChatShellStore.setState({
      currentSessionId: null,
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

  it('uses flat square active states instead of bordered cards', async () => {
    vi.mocked(messagesApi.listSessions).mockResolvedValueOnce({
      sessions: [
        {
          session_id: 'session-a',
          title: '杭州天气',
          last_message_preview: '今天有点冷',
          last_timestamp: 10,
          message_count: 1,
        },
      ],
      user_id: 'web_user',
      count: 1,
    });
    useConversationStore.setState({
      currentSessionId: 'session-a',
      orderedSessionIds: ['session-a'],
      sessionsById: {
        'session-a': {
          session_id: 'session-a',
          title: '杭州天气',
          last_message_preview: '今天有点冷',
          last_timestamp: 10,
          message_count: 1,
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

    const conversationAction = await screen.findByRole('button', { name: 'shell.conversation' });
    const sessionAction = await screen.findByRole('button', { name: '杭州天气' });

    expect(conversationAction.className).toContain('rounded-none');
    expect(conversationAction.className).not.toContain(' border ');
    expect(sessionAction.className).toContain('rounded-none');
  });

  it('keeps the currently selected session when it still exists in the refreshed list', async () => {
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
      user_id: 'web_user',
      count: 2,
    });
    useConversationStore.getState().setCurrentSessionId('session-b');

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <Sidebar />
      </MemoryRouter>
    );

    await screen.findByRole('button', { name: '西湖路线' });
    await waitFor(() => {
      expect(useConversationStore.getState().currentSessionId).toBe('session-b');
    });
  });

  it('creates a new session without triggering redundant sidebar refresh loops', async () => {
    const user = userEvent.setup();
    vi.mocked(messagesApi.listSessions)
      .mockResolvedValueOnce({
        sessions: [
          {
            session_id: 'session-a',
            title: '旧会话',
            last_message_preview: '之前的消息',
            last_timestamp: 10,
            message_count: 1,
          },
        ],
        user_id: 'web_user',
        count: 1,
      })
      .mockResolvedValueOnce({
        sessions: [
          {
            session_id: 'session-new',
            title: '新会话',
            last_message_preview: '',
            last_timestamp: 11,
            message_count: 0,
          },
          {
            session_id: 'session-a',
            title: '旧会话',
            last_message_preview: '之前的消息',
            last_timestamp: 10,
            message_count: 1,
          },
        ],
        user_id: 'web_user',
        count: 2,
      });
    vi.mocked(messagesApi.createNewSession).mockResolvedValueOnce({
      success: true,
      user_id: 'web_user',
      session_id: 'session-new',
    });

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <Sidebar />
      </MemoryRouter>
    );

    await screen.findByRole('button', { name: '旧会话' });

    await user.click(screen.getByRole('button', { name: 'shell.newChat' }));

    await waitFor(() => {
      expect(useConversationStore.getState().currentSessionId).toBe('session-new');
    });
    expect(messagesApi.createNewSession).toHaveBeenCalledTimes(1);
    expect(messagesApi.listSessions).toHaveBeenCalledTimes(2);
  });

  it('opens the session actions menu from the overflow button and right click', async () => {
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
      ],
      user_id: 'web_user',
      count: 1,
    });
    useConversationStore.setState({
      currentSessionId: 'session-a',
      orderedSessionIds: ['session-a'],
      sessionsById: {
        'session-a': {
          session_id: 'session-a',
          title: '杭州天气',
          last_message_preview: '今天有点冷',
          last_timestamp: 10,
          message_count: 1,
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

    await user.click(await screen.findByRole('button', { name: 'shell.sessionActions' }));

    expect(await screen.findByRole('button', { name: 'shell.renameSession' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'shell.deleteSession' })).toBeInTheDocument();

    await user.click(document.body);

    await user.pointer([
      {
        target: screen.getByRole('button', { name: '杭州天气' }),
        keys: '[MouseRight]',
      },
    ]);

    expect(await screen.findByRole('button', { name: 'shell.renameSession' })).toBeInTheDocument();
  });

  it('renames a session through the sidebar menu and keeps the updated label', async () => {
    const user = userEvent.setup();
    vi.mocked(messagesApi.listSessions)
      .mockResolvedValueOnce({
        sessions: [
          {
            session_id: 'session-a',
            title: '杭州天气',
            last_user_message_preview: '杭州天气',
            last_message_preview: '今天有点冷',
            last_timestamp: 10,
            message_count: 1,
          },
        ],
        user_id: 'web_user',
        count: 1,
      })
      .mockResolvedValue({
        sessions: [
          {
            session_id: 'session-a',
            title: '天气追踪',
            title_overridden: true,
            last_user_message_preview: '杭州天气',
            last_message_preview: '今天有点冷',
            last_timestamp: 10,
            message_count: 1,
          },
        ],
        user_id: 'web_user',
        count: 1,
      });
    vi.mocked(messagesApi.renameSession).mockResolvedValue({
      success: true,
      user_id: 'web_user',
      session: {
        session_id: 'session-a',
        title: '天气追踪',
      },
    });

    useConversationStore.setState({
      currentSessionId: 'session-a',
      orderedSessionIds: ['session-a'],
      sessionsById: {
        'session-a': {
          session_id: 'session-a',
          title: '杭州天气',
          last_user_message_preview: '杭州天气',
          last_message_preview: '今天有点冷',
          last_timestamp: 10,
          message_count: 1,
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

    const actionButtons = await screen.findAllByRole('button', { name: 'shell.sessionActions' });
    await user.click(actionButtons[0]);
    await user.click(await screen.findByRole('button', { name: 'shell.renameSession' }));
    await user.clear(screen.getByPlaceholderText('shell.renameSessionPlaceholder'));
    await user.type(screen.getByPlaceholderText('shell.renameSessionPlaceholder'), '天气追踪');
    await user.click(screen.getByRole('button', { name: 'shell.saveRename' }));

    await waitFor(() =>
      expect(messagesApi.renameSession).toHaveBeenCalledWith('web_user', 'session-a', '天气追踪')
    );
    expect(await screen.findByRole('button', { name: '天气追踪' })).toBeInTheDocument();
  });

  it('deletes a session through the sidebar menu', async () => {
    const user = userEvent.setup();
    vi.mocked(messagesApi.listSessions)
      .mockResolvedValueOnce({
        sessions: [
          {
            session_id: 'session-a',
            title: '杭州天气',
            last_user_message_preview: '杭州天气',
            last_message_preview: '今天有点冷',
            last_timestamp: 10,
            message_count: 1,
          },
          {
            session_id: 'session-b',
            title: '西湖路线',
            last_user_message_preview: '西湖路线',
            last_message_preview: '沿湖散步',
            last_timestamp: 9,
            message_count: 1,
          },
        ],
        user_id: 'web_user',
        count: 2,
      })
      .mockResolvedValue({
        sessions: [
          {
            session_id: 'session-b',
            title: '西湖路线',
            last_user_message_preview: '西湖路线',
            last_message_preview: '沿湖散步',
            last_timestamp: 9,
            message_count: 1,
          },
        ],
        user_id: 'web_user',
        count: 1,
      });
    vi.mocked(messagesApi.deleteSession).mockResolvedValue({
      success: true,
      user_id: 'web_user',
      deleted_session_id: 'session-a',
    });

    useConversationStore.setState({
      currentSessionId: 'session-a',
      orderedSessionIds: ['session-a', 'session-b'],
      sessionsById: {
        'session-a': {
          session_id: 'session-a',
          title: '杭州天气',
          last_user_message_preview: '杭州天气',
          last_message_preview: '今天有点冷',
          last_timestamp: 10,
          message_count: 1,
        },
        'session-b': {
          session_id: 'session-b',
          title: '西湖路线',
          last_user_message_preview: '西湖路线',
          last_message_preview: '沿湖散步',
          last_timestamp: 9,
          message_count: 1,
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

    const actionButtons = await screen.findAllByRole('button', { name: 'shell.sessionActions' });
    await user.click(actionButtons[0]);
    await user.click(await screen.findByRole('button', { name: 'shell.deleteSession' }));
    await user.click(await screen.findByRole('button', { name: 'shell.confirmDeleteSession' }));

    await waitFor(() =>
      expect(messagesApi.deleteSession).toHaveBeenCalledWith('web_user', 'session-a')
    );
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: '杭州天气' })).not.toBeInTheDocument()
    );
    expect(screen.getByRole('button', { name: '西湖路线' })).toBeInTheDocument();
  });

  it('refreshes sessions on sync events', async () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <Sidebar />
      </MemoryRouter>
    );

    await waitFor(() => expect(messagesApi.listSessions).toHaveBeenCalled());
    const initialCalls = vi.mocked(messagesApi.listSessions).mock.calls.length;

    await act(async () => {
      window.dispatchEvent(new Event('magi-session-sync'));
    });

    await waitFor(() =>
      expect(vi.mocked(messagesApi.listSessions).mock.calls.length).toBeGreaterThan(initialCalls)
    );
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

    expect(sidebar).toHaveClass('pt-7');
  });

  it('renders a nested conversation rail with compact tools in the polished sidebar hierarchy', async () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <Sidebar />
      </MemoryRouter>
    );

    const conversationRail = await screen.findByTestId('sidebar-conversation-rail');
    const conversationTools = screen.getByTestId('sidebar-conversation-tools');

    expect(conversationRail).toHaveClass('ml-5');
    expect(conversationTools).toHaveClass('gap-1');
  });

  it('renders a memory rail with an independently highlighted active row', async () => {
    render(
      <MemoryRouter initialEntries={['/memory/knowledge']}>
        <Sidebar />
      </MemoryRouter>
    );

    const memoryRail = await screen.findByTestId('sidebar-memory-rail');
    const activeMemoryRow = screen.getByRole('button', { name: 'memory.nav.knowledge' });

    expect(memoryRail).toHaveClass('ml-5');
    expect(activeMemoryRow).toHaveClass('rounded-none');
  });
});
