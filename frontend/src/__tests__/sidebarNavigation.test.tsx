import { MemoryRouter, useLocation } from 'react-router';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, beforeEach, vi } from 'vitest';
import { toast } from 'sonner';
import { configApi, messagesApi } from '@/api';
import Sidebar from '@/components/layout/Sidebar';
import { useChatShellStore, useConversationStore } from '@/stores';
import { useNotificationStore } from '@/stores/notifications';
import {
  loadRetryableChatSends,
  loadRetryableInlineSkillOperations,
  saveRetryableChatSends,
  saveRetryableInlineSkillOperations,
  type RetryableChatSendOperation,
  type RetryableInlineSkillOperation,
} from '@/hooks/chatRetryableSendStorage';

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
    warning: vi.fn(),
  },
}));

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

  const buildComposerRetry = (
    sessionId: string,
    turnId: string,
  ): RetryableChatSendOperation => ({
    sessionId,
    turnId,
    createdAtMs: Date.now(),
    draftIdentity: `identity:${turnId}`,
    draftSignature: `signature:${turnId}`,
    draftKind: 'normal',
    request: {
      user_id: 'local_user',
      session_id: sessionId,
      message: `message:${turnId}`,
      client_turn_id: turnId,
    },
    confirmation: { kind: 'turn', sessionId, turnId },
    pendingTurn: {
      sessionId,
      input: `message:${turnId}`,
      turnId,
      timestamp: Date.now(),
      pendingLabel: 'Pending',
    },
  });

  const buildInlineRetry = (
    sessionId: string,
    turnId: string,
  ): RetryableInlineSkillOperation => ({
    retryKey: JSON.stringify([sessionId, null, 'summarize', [turnId]]),
    createdAtMs: Date.now(),
    request: {
      user_id: 'local_user',
      session_id: sessionId,
      message: `/summarize ${turnId}\n\nExpanded prompt`,
      workspace_path: null,
      client_turn_id: turnId,
    },
    confirmation: { kind: 'turn', sessionId, turnId },
  });

  const seedSessionRetries = () => {
    const composerA = buildComposerRetry('session-a', 'turn-a');
    const composerB = buildComposerRetry('session-b', 'turn-b');
    const inlineA = buildInlineRetry('session-a', 'skill-turn-a');
    const inlineB = buildInlineRetry('session-b', 'skill-turn-b');
    saveRetryableChatSends(new Map([
      [composerA.sessionId, composerA],
      [composerB.sessionId, composerB],
    ]));
    saveRetryableInlineSkillOperations(new Map([
      [inlineA.retryKey, inlineA],
      [inlineB.retryKey, inlineB],
    ]));
  };

  const LocationProbe = () => {
    const location = useLocation();
    return <div data-testid="location">{location.pathname}</div>;
  };

  beforeEach(() => {
    vi.clearAllMocks();
    storage.clear();
    window.sessionStorage.clear();
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
      timelinePanel: {
        ...useChatShellStore.getState().timelinePanel,
        monthForCalendar: '2026-06',
        selectedDate: '2026-06-20',
        selectedRangeStart: '2026-06-20',
        selectedRangeEnd: '2026-06-20',
      },
    });
    useConversationStore.getState().reset();
    useNotificationStore.setState({
      items: [],
      unreadCount: 0,
      loading: false,
    });
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
    expect(screen.queryByRole('button', { name: 'shell.sessionActions' })).not.toBeInTheDocument();
    expect(screen.queryByRole('searchbox')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '杭州天气' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '西湖路线' })).toBeInTheDocument();
  });

  it('creates a new session from the persona header action', async () => {
    const user = userEvent.setup();
    vi.mocked(messagesApi.listSessions)
      .mockResolvedValueOnce({
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
      })
      .mockResolvedValue({
        sessions: [
          {
            session_id: 'session-new',
            title: 'New Session',
            last_message_preview: '',
            last_timestamp: 12,
            message_count: 0,
          },
          {
            session_id: 'session-a',
            title: '杭州天气',
            last_message_preview: '今天有点冷',
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
    await user.click(await screen.findByRole('button', { name: 'shell.newChat' }));

    await waitFor(() => {
      expect(messagesApi.createNewSession).toHaveBeenCalledWith('local_user');
    });
    await waitFor(() => {
      expect(useConversationStore.getState().currentSessionId).toBe('session-new');
    });
    expect(storage.get('chat_session_local_user')).toBe('session-new');
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

  it('opens the session actions menu from right click', async () => {
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
    expect(screen.queryByRole('button', { name: 'shell.sessionActions' })).not.toBeInTheDocument();

    await user.pointer([
      {
        target: screen.getByRole('button', { name: '杭州天气' }),
        keys: '[MouseRight]',
      },
    ]);

    expect(await screen.findByRole('button', { name: 'shell.renameSession' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'shell.deleteSession' })).toBeInTheDocument();
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
    await user.pointer([
      {
        target: await screen.findByRole('button', { name: '杭州天气' }),
        keys: '[MouseRight]',
      },
    ]);
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
      cleanup_pending: true,
    });
    seedSessionRetries();

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
    await user.pointer([
      {
        target: await screen.findByRole('button', { name: '杭州天气' }),
        keys: '[MouseRight]',
      },
    ]);
    await user.click(await screen.findByRole('button', { name: 'shell.deleteSession' }));
    await user.click(await screen.findByRole('button', { name: 'shell.confirmDeleteSession' }));

    await waitFor(() =>
      expect(messagesApi.deleteSession).toHaveBeenCalledWith('local_user', 'session-a')
    );
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: '杭州天气' })).not.toBeInTheDocument()
    );
    expect(screen.getByRole('button', { name: '西湖路线' })).toBeInTheDocument();
    expect(loadRetryableChatSends().has('session-a')).toBe(false);
    expect(loadRetryableChatSends().has('session-b')).toBe(true);
    expect([...loadRetryableInlineSkillOperations().values()].some(
      (operation) => operation.request.session_id === 'session-a',
    )).toBe(false);
    expect([...loadRetryableInlineSkillOperations().values()].some(
      (operation) => operation.request.session_id === 'session-b',
    )).toBe(true);
    expect(useConversationStore.getState().currentSessionId).toBe('session-b');
    expect(window.localStorage.getItem('chat_session_local_user')).toBe('session-b');
    expect(toast.warning).toHaveBeenCalledWith(
      'shell.deleteSessionCleanupPending',
    );
  });

  it('keeps the current session and retries when session deletion fails', async () => {
    const user = userEvent.setup();
    const sessions = [
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
    ];
    vi.mocked(messagesApi.listSessions).mockResolvedValue({
      sessions,
      user_id: 'local_user',
      count: sessions.length,
    });
    vi.mocked(messagesApi.deleteSession).mockRejectedValue(new Error('offline'));
    seedSessionRetries();
    useConversationStore.setState({
      currentSessionId: 'session-a',
      orderedSessionIds: ['session-a', 'session-b'],
      sessionsById: Object.fromEntries(
        sessions.map((session) => [session.session_id, session]),
      ),
      messagesBySession: {},
      unreadBySession: {},
    });

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <Sidebar />
      </MemoryRouter>
    );

    await user.click(await screen.findByRole('button', { name: 'shell.conversation' }));
    await user.pointer([{
      target: await screen.findByRole('button', { name: '杭州天气' }),
      keys: '[MouseRight]',
    }]);
    await user.click(await screen.findByRole('button', { name: 'shell.deleteSession' }));
    await user.click(await screen.findByRole('button', { name: 'shell.confirmDeleteSession' }));

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith('shell.deleteSessionFailed');
    });
    expect(loadRetryableChatSends().has('session-a')).toBe(true);
    expect([...loadRetryableInlineSkillOperations().values()].some(
      (operation) => operation.request.session_id === 'session-a',
    )).toBe(true);
    expect(useConversationStore.getState().currentSessionId).toBe('session-a');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('keeps a confirmed deletion committed when the session list refresh fails', async () => {
    const user = userEvent.setup();
    const sessionA = {
      session_id: 'session-a',
      title: '杭州天气',
      last_user_message_preview: '杭州天气',
      last_message_preview: '今天有点冷',
      last_timestamp: 10,
      message_count: 1,
    };
    vi.mocked(messagesApi.listSessions)
      .mockResolvedValueOnce({
        sessions: [sessionA],
        user_id: 'local_user',
        count: 1,
      })
      .mockRejectedValueOnce(new Error('refresh failed'));
    vi.mocked(messagesApi.deleteSession).mockResolvedValue({
      success: true,
      user_id: 'local_user',
      deleted_session_id: 'session-a',
      cleanup_pending: false,
    });
    seedSessionRetries();
    useConversationStore.setState({
      currentSessionId: 'session-a',
      orderedSessionIds: ['session-a'],
      sessionsById: { 'session-a': sessionA },
      messagesBySession: {},
      unreadBySession: {},
    });

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <Sidebar />
      </MemoryRouter>
    );

    await user.click(await screen.findByRole('button', { name: 'shell.conversation' }));
    await user.pointer([{
      target: await screen.findByRole('button', { name: '杭州天气' }),
      keys: '[MouseRight]',
    }]);
    await user.click(await screen.findByRole('button', { name: 'shell.deleteSession' }));
    await user.click(await screen.findByRole('button', { name: 'shell.confirmDeleteSession' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    expect(toast.error).not.toHaveBeenCalledWith('shell.deleteSessionFailed');
    expect(loadRetryableChatSends().has('session-a')).toBe(false);
    expect([...loadRetryableInlineSkillOperations().values()].some(
      (operation) => operation.request.session_id === 'session-a',
    )).toBe(false);
    expect(useConversationStore.getState().currentSessionId).toBeNull();
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

  it('navigates to the timeline route before timeline shell state is hydrated', async () => {
    const user = userEvent.setup();
    useChatShellStore.setState({
      timelinePanel: {
        ...useChatShellStore.getState().timelinePanel,
        monthForCalendar: '',
        selectedDate: '',
        selectedRangeStart: '',
        selectedRangeEnd: '',
      },
    });

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <Sidebar />
        <LocationProbe />
      </MemoryRouter>
    );

    await user.click(await screen.findByRole('button', { name: 'shell.timeline' }));

    expect(screen.getByTestId('location')).toHaveTextContent('/timeline');
    expect(useChatShellStore.getState().activePanel).toBe('timeline');
    expect(screen.getByTestId('sidebar-timeline-panel')).toBeInTheDocument();
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

    expect(screen.getByTestId('location')).toHaveTextContent('/memory/overview');
    expect(screen.getByRole('button', { name: 'memory.nav.overview' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.nav.sources' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.nav.overview' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByTestId('sidebar-memory-icon-overview')).toBeInTheDocument();

    const sidebarRoot = document.querySelector('aside');
    expect(sidebarRoot).toHaveClass('w-[248px]');

    await user.click(screen.getByRole('button', { name: 'memory.nav.episodes' }));

    expect(screen.getByTestId('sidebar-memory-panel')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.nav.overview' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.nav.sources' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.nav.pending' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.nav.stories' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.nav.episodes' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'memory.nav.knowledge' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.nav.portrait' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.nav.recall' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.nav.governance' })).toBeInTheDocument();
    expect(screen.getByTestId('sidebar-memory-icon-episodes')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.nav.episodes' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByTestId('location')).toHaveTextContent('/memory/episodes');
    expect(useChatShellStore.getState().activePanel).toBe('memory');

    await user.click(screen.getByRole('button', { name: 'memory.nav.sources' }));

    expect(screen.getByTestId('location')).toHaveTextContent('/memory/sources');
    expect(screen.getByRole('button', { name: 'memory.nav.sources' })).toHaveAttribute('aria-current', 'page');
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
    expect(screen.getByRole('button', { name: 'memory.nav.sources' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.nav.pending' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.nav.stories' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.nav.episodes' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'memory.nav.knowledge' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.nav.portrait' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.nav.recall' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.nav.governance' })).toBeInTheDocument();
  });

  it('shows a pending memory badge when profile conflicts need review', async () => {
    const user = userEvent.setup();
    useNotificationStore.setState({
      items: [
        {
          id: 42,
          kind: 'suggestion',
          dedupe_key: 'profile_conflict:interest.anime:topic:anime',
          title: '偏好冲突：interest.anime',
          body: '你最近常关注「安静圣地巡礼」，但你说过「城市热门路线」—— 要更新偏好吗？',
          payload: {
            conflict_type: 'profile_conflict',
            shadow_id: 'assert-shadow-1',
          },
          status: 'read',
          created_at_ms: 1710000000000,
          read_at_ms: 1710000001000,
        },
      ],
      unreadCount: 0,
      loading: false,
    });

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <Sidebar />
        <LocationProbe />
      </MemoryRouter>
    );

    await user.click(await screen.findByRole('button', { name: 'shell.memory' }));

    const pendingButton = screen.getByRole('button', { name: 'memory.nav.pending' });
    expect(within(pendingButton).getByText('1')).toBeInTheDocument();
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
    act(() => {
      useConversationStore.setState({
        unreadBySession: {
          'session-b': 3,
        },
      });
    });
    expect(within(screen.getByRole('button', { name: 'shell.conversation' })).getByText('3')).toBeInTheDocument();
    expect(screen.getAllByText('3')).toHaveLength(2);
  });

});
