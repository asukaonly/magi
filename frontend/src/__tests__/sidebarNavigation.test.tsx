import { MemoryRouter, useLocation } from 'react-router-dom';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, beforeEach, vi } from 'vitest';
import { configApi, messagesApi } from '@/api';
import Sidebar from '@/components/layout/Sidebar';
import { useChatShellStore, useConversationStore } from '@/stores';

vi.mock('@/api', () => ({
  configApi: {
    get: vi.fn().mockResolvedValue({
      data: {
        preferences: {
          user_mode: null,
        },
      },
    }),
  },
  messagesApi: {
    listSessions: vi.fn().mockResolvedValue({
      sessions: [],
      user_id: 'local_user',
      count: 0,
    }),
    createNewSession: vi.fn().mockResolvedValue({
      success: true,
      user_id: 'local_user',
      session_id: null,
    }),
    renameSession: vi.fn(),
    deleteSession: vi.fn(),
  },
}));

vi.mock('@/api/modules/personas', async () => {
  const actual = await vi.importActual<typeof import('@/api/modules/personas')>(
    '@/api/modules/personas',
  );
  // PersonaHeader (host of the new chat "+" button after the title-bar
  // refactor) only renders when there's an active persona — so the test
  // mock must surface one or every sidebar test loses access to the
  // create-chat button.
  return {
    ...actual,
    personasApi: {
      ...actual.personasApi,
      getActive: vi.fn().mockResolvedValue({ success: true, persona_id: 'p1' }),
      get: vi.fn().mockResolvedValue({
        success: true,
        data: {
          persona_id: 'p1',
          name: 'Test',
          slug: 'test',
          locale: 'en',
          config: { name: 'Test' },
          avatar_path: '',
          group_name: 'general',
          sort_order: 0,
          is_builtin: false,
          seed_slug: null,
          created_at: 0,
          updated_at: 0,
        },
      }),
    },
  };
});

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
    vi.mocked(configApi.get).mockResolvedValue({
      data: {
        preferences: {
          user_mode: null,
        },
      },
    } as any);
  });

  it('renders conversation, timeline, memory, and settings actions without a personality button', async () => {
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <Sidebar />
      </MemoryRouter>
    );

    const conversationButton = await screen.findByRole('button', { name: 'shell.conversation' });
    expect(conversationButton).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'shell.memory' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'shell.settings' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'shell.timeline' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'shell.tasks.label' })).toBeInTheDocument();
    expect(screen.queryByTestId('sidebar-conversation-rail')).not.toBeInTheDocument();

    await user.click(conversationButton);
    expect(screen.getByTestId('sidebar-conversation-rail')).toBeInTheDocument();

    await user.click(conversationButton);
    expect(screen.queryByTestId('sidebar-conversation-rail')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'shell.personality' })).not.toBeInTheDocument();
  });

  it('does not fetch or auto-create sessions on the settings route', async () => {
    render(
      <MemoryRouter initialEntries={['/settings']}>
        <Sidebar />
      </MemoryRouter>
    );

    expect(await screen.findByRole('button', { name: 'shell.settings' })).toBeInTheDocument();
    expect(messagesApi.listSessions).not.toHaveBeenCalled();
    expect(messagesApi.createNewSession).not.toHaveBeenCalled();
  });

  it('opens settings without replacing the current activity side panel', async () => {
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <Sidebar />
      </MemoryRouter>
    );

    await user.click(await screen.findByRole('button', { name: 'shell.conversation' }));
    expect(screen.getByTestId('sidebar-conversation-rail')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'shell.settings' }));

    expect(useChatShellStore.getState().activePanel).toBe('settings');
    expect(screen.getByTestId('sidebar-conversation-rail')).toBeInTheDocument();
    expect(screen.queryByTestId('sidebar-settings-panel')).not.toBeInTheDocument();
  });

  it('renders conversation sessions without search controls', async () => {
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
      user_id: 'local_user',
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

    await user.click(await screen.findByRole('button', { name: 'shell.conversation' }));
    expect(screen.getByRole('button', { name: 'shell.newChat' })).toBeInTheDocument();
    expect(screen.queryByRole('searchbox')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '杭州天气' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '西湖路线' })).toBeInTheDocument();
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
      user_id: 'local_user',
      count: 2,
    });
    useConversationStore.getState().setCurrentSessionId('session-b');

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <Sidebar />
      </MemoryRouter>
    );

    await userEvent.click(await screen.findByRole('button', { name: 'shell.conversation' }));
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
        user_id: 'local_user',
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
        user_id: 'local_user',
        count: 2,
      });
    vi.mocked(messagesApi.createNewSession).mockResolvedValueOnce({
      success: true,
      user_id: 'local_user',
      session_id: 'session-new',
    });

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <Sidebar />
      </MemoryRouter>
    );

    await user.click(await screen.findByRole('button', { name: 'shell.conversation' }));
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
      user_id: 'local_user',
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

    await user.click(await screen.findByRole('button', { name: 'shell.conversation' }));
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
        user_id: 'local_user',
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
        user_id: 'local_user',
        count: 1,
      });
    vi.mocked(messagesApi.renameSession).mockResolvedValue({
      success: true,
      user_id: 'local_user',
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

    await user.click(await screen.findByRole('button', { name: 'shell.conversation' }));
    const actionButtons = await screen.findAllByRole('button', { name: 'shell.sessionActions' });
    await user.click(actionButtons[0]);
    await user.click(await screen.findByRole('button', { name: 'shell.renameSession' }));
    await user.clear(screen.getByPlaceholderText('shell.renameSessionPlaceholder'));
    await user.type(screen.getByPlaceholderText('shell.renameSessionPlaceholder'), '天气追踪');
    await user.click(screen.getByRole('button', { name: 'shell.saveRename' }));

    await waitFor(() =>
      expect(messagesApi.renameSession).toHaveBeenCalledWith('local_user', 'session-a', '天气追踪')
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
        user_id: 'local_user',
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
        user_id: 'local_user',
        count: 1,
      });
    vi.mocked(messagesApi.deleteSession).mockResolvedValue({
      success: true,
      user_id: 'local_user',
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

    await user.click(await screen.findByRole('button', { name: 'shell.conversation' }));
    const actionButtons = await screen.findAllByRole('button', { name: 'shell.sessionActions' });
    await user.click(actionButtons[0]);
    await user.click(await screen.findByRole('button', { name: 'shell.deleteSession' }));
    await user.click(await screen.findByRole('button', { name: 'shell.confirmDeleteSession' }));

    await waitFor(() =>
      expect(messagesApi.deleteSession).toHaveBeenCalledWith('local_user', 'session-a')
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

  it('renders memory destinations and routes to the selected memory page', async () => {
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <Sidebar />
        <LocationProbe />
      </MemoryRouter>
    );

    await user.click(await screen.findByRole('button', { name: 'shell.memory' }));
    await user.click(screen.getByRole('button', { name: 'memory.nav.knowledge' }));

    expect(screen.getByTestId('sidebar-memory-panel')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.nav.overview' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.nav.workbench' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.nav.events' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.nav.knowledge' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.nav.reflection' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.nav.skills' })).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/memory/knowledge');
    expect(useChatShellStore.getState().activePanel).toBe('memory');
  });

  it('renders all memory destinations without loading user mode', async () => {
    const user = userEvent.setup();
    vi.mocked(configApi.get).mockResolvedValue({
      data: {
        preferences: {
          user_mode: 'quick',
        },
      },
    } as any);

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <Sidebar />
        <LocationProbe />
      </MemoryRouter>
    );

    await user.click(await screen.findByRole('button', { name: 'shell.memory' }));

    expect(configApi.get).not.toHaveBeenCalled();
    expect(screen.getByTestId('sidebar-memory-panel')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.nav.overview' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.nav.workbench' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.nav.events' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.nav.knowledge' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.nav.reflection' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.nav.skills' })).toBeInTheDocument();
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
      user_id: 'local_user',
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

    await userEvent.click(await screen.findByRole('button', { name: 'shell.conversation' }));
    expect(await screen.findByText('3')).toBeInTheDocument();
  });

});
