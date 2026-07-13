import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ChatPage } from '@/pages/Chat';
import { useConversationStore } from '@/stores/conversation-store';
import { useChatTraceStore } from '@/stores';
import { normalizeHistoryMessages, shouldShowTraceEntry } from '@/domain/chat/state';
import { messagesApi } from '@/api';
import { getPlanState, getTodos, respondAsk, respondPermission, updateSessionSettings } from '@/api/modules/control';
import { configApi, DEFAULT_SYSTEM_CONFIG } from '@/api/modules/config';
import { personasApi } from '@/api/modules/personas';
import { applyRealtimeStoreProjection } from '@/realtime/store-projection';

let realtimeListener: ((message: Record<string, unknown>) => void) | null = null;
const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
const { pickDirectoryMock, openExternalUrlMock, convertFileSrcMock, toastWarningMock } = vi.hoisted(() => ({
  pickDirectoryMock: vi.fn(),
  openExternalUrlMock: vi.fn().mockResolvedValue(undefined),
  convertFileSrcMock: vi.fn((path: string) => `asset://${path}`),
  toastWarningMock: vi.fn(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'zh-CN' },
  }),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => vi.fn(),
  };
});

vi.mock('sonner', () => ({
  toast: {
    warning: toastWarningMock,
    error: vi.fn(),
    success: vi.fn(),
  },
}));

vi.mock('@/realtime/provider', async () => {
  const actual = await vi.importActual<typeof import('@/realtime/provider')>('@/realtime/provider');
  return {
    ...actual,
    useRealtime: () => ({
      subscribe: (listener: (message: Record<string, unknown>) => void) => {
        realtimeListener = (message: Record<string, unknown>) => {
          applyRealtimeStoreProjection(message);
          listener(message);
        };
        return () => {
          realtimeListener = null;
        };
      },
    }),
  };
});

vi.mock('@/runtime/config', () => ({
  getRuntimeConfig: () => ({
    apiBaseUrl: 'http://127.0.0.1:8000/api',
  }),
}));

vi.mock('@/api/modules/control', () => ({
  getControlSettings: vi.fn().mockResolvedValue({
    permission_mode: 'high_only',
    plan_approval_required: false,
  }),
  getSessionSettings: vi.fn().mockResolvedValue({
    base: { permission_mode: 'high_only', plan_approval_required: false },
    override: null,
    effective: { permission_mode: 'high_only', plan_approval_required: false },
  }),
  listPermissionRules: vi.fn().mockResolvedValue([]),
  updateControlSettings: vi.fn(),
  updateSessionSettings: vi.fn().mockResolvedValue({
    base: { permission_mode: 'high_only', plan_approval_required: false },
    override: { permission_mode: 'off', plan_approval_required: null },
    effective: { permission_mode: 'off', plan_approval_required: false },
  }),
  getPlanState: vi.fn().mockResolvedValue({
    active: false,
    plan_text: null,
    entered_at_ms: null,
    exited_at_ms: null,
  }),
  getTodos: vi.fn().mockResolvedValue([]),
  respondAsk: vi.fn().mockResolvedValue(undefined),
  respondPermission: vi.fn().mockResolvedValue(undefined),
  deletePermissionRule: vi.fn(),
  clearSessionPermissionRules: vi.fn(),
}));

vi.mock('@/api/modules/personas', async () => {
  const actual = await vi.importActual<typeof import('@/api/modules/personas')>('@/api/modules/personas');
  return {
    ...actual,
    personasApi: {
      ...actual.personasApi,
      list: vi.fn().mockResolvedValue({ success: true, data: [] }),
      getGreeting: vi.fn().mockResolvedValue({ success: true, data: { name: 'AI', greeting: '', needs_bootstrap: false } }),
      bootstrapInit: vi.fn().mockResolvedValue({ success: true, data: { bootstrap_active: false, opening: null } }),
    },
  };
});

vi.mock('@/runtime/desktop', () => ({
  pickDirectory: pickDirectoryMock,
  openExternalUrl: openExternalUrlMock,
}));

vi.mock('@tauri-apps/api/core', () => ({
  convertFileSrc: convertFileSrcMock,
}));

// Persona bootstrap is gated behind the one-time product tour (shouldFireBootstrap).
// These tests exercise bootstrap mechanics, not the tour, so treat the tour as
// already resolved (as it is for any returning user) and let bootstrap fire.
vi.mock('@/hooks/useProductTourFlag', () => ({
  useProductTourFlag: () => ({ completed: true, loaded: true, markCompleted: vi.fn() }),
}));

vi.mock('@/api/modules/config', async () => {
  const actual = await vi.importActual<typeof import('@/api/modules/config')>('@/api/modules/config');
  return {
    ...actual,
    configApi: {
      ...actual.configApi,
      get: vi.fn(),
    },
  };
});

vi.mock('@/api', () => ({
  messagesApi: {
    getTrace: vi.fn(),
    uploadAttachment: vi.fn(),
    updateSessionWorkspace: vi.fn(),
    getRecentWorkspaces: vi.fn().mockResolvedValue({ paths: [] }),
    rememberWorkspace: vi.fn().mockResolvedValue({ paths: [] }),
    cancelRun: vi.fn(),
    detachRun: vi.fn(),
    labelMessage: vi.fn(),
    deleteMessage: vi.fn(),
    sendMessage: vi.fn().mockResolvedValue({ success: true, message: 'ok', data: { user_id: 'local_user', session_id: 'session-1', message_length: 0, timestamp: Date.now() / 1000 } }),
    getHistory: vi.fn().mockReturnValue(new Promise(() => {})),
  },
  sensorsApi: {
    getStatus: vi.fn().mockResolvedValue({ sources: [] }),
    getTodaySummary: vi.fn().mockResolvedValue({ date: '2026-05-16', weekday: 5, sources: [] }),
    requestSync: vi.fn(),
    requestStateFlush: vi.fn(),
    requestAuthorization: vi.fn(),
  },
}));

vi.mock('@/components/chat/ToolchainDrawer', () => ({
  default: () => null,
}));

describe('ChatPage', () => {
  const setMockFileSize = (file: File, size: number) => {
    Object.defineProperty(file, 'size', {
      value: size,
      configurable: true,
    });
    return file;
  };

  const buildConfigWithVision = (vision: boolean) => ({
    data: {
      ...structuredClone(DEFAULT_SYSTEM_CONFIG),
      llm: {
        ...structuredClone(DEFAULT_SYSTEM_CONFIG.llm),
        selections: {
          ...structuredClone(DEFAULT_SYSTEM_CONFIG.llm.selections),
          core: {
            ...structuredClone(DEFAULT_SYSTEM_CONFIG.llm.selections.core),
            capabilities: {
              ...structuredClone(DEFAULT_SYSTEM_CONFIG.llm.selections.core.capabilities),
              vision,
            },
            limits: {
              ...structuredClone(DEFAULT_SYSTEM_CONFIG.llm.selections.core.limits),
              context_window: 1_000_000,
            },
          },
        },
      },
    },
  });

  afterAll(() => {
    consoleErrorSpy.mockRestore();
  });

  afterEach(() => {
    realtimeListener = null;
    useConversationStore.getState().reset();
    useChatTraceStore.getState().reset();
    cleanup();
    document.body.innerHTML = '';
  });

  beforeEach(() => {
    realtimeListener = null;
    consoleErrorSpy.mockClear();
    pickDirectoryMock.mockReset();
    pickDirectoryMock.mockResolvedValue(undefined);
    openExternalUrlMock.mockReset();
    openExternalUrlMock.mockResolvedValue(undefined);
    toastWarningMock.mockReset();
    vi.mocked(personasApi.list).mockReset().mockResolvedValue({ success: true, data: [] } as any);
    vi.mocked(personasApi.getGreeting).mockReset().mockResolvedValue({ success: true, data: { name: 'AI', greeting: '', needs_bootstrap: false } } as any);
    vi.mocked(personasApi.bootstrapInit).mockReset().mockResolvedValue({ success: true, data: { bootstrap_active: false, opening: null } } as any);
    vi.mocked(messagesApi.getTrace).mockReset().mockResolvedValue({
      success: true,
      user_id: 'local_user',
      session_id: 'session-1',
      turn_id: 'turn-default',
      trace: null,
    } as any);
    vi.mocked(messagesApi.getRecentWorkspaces).mockReset().mockResolvedValue({ paths: [] } as any);
    vi.mocked(messagesApi.rememberWorkspace).mockReset().mockResolvedValue({ paths: [] } as any);
    vi.mocked(messagesApi.labelMessage).mockReset();
    vi.mocked(messagesApi.deleteMessage).mockReset();
    vi.mocked(respondAsk).mockClear();
    vi.mocked(respondPermission).mockClear();
    vi.mocked(updateSessionSettings).mockClear();
    vi.mocked(getPlanState).mockReset().mockResolvedValue({
      active: false,
      plan_text: null,
      entered_at_ms: null,
      exited_at_ms: null,
    } as any);
    vi.mocked(getTodos).mockReset().mockResolvedValue([]);
    vi.mocked(messagesApi.sendMessage).mockReset().mockResolvedValue({ success: true, message: 'ok', data: { user_id: 'local_user', session_id: 'session-1', message_length: 0, timestamp: Date.now() / 1000 } });
    vi.mocked(messagesApi.getHistory).mockReset().mockReturnValue(new Promise(() => {}));
    vi.mocked(configApi.get).mockResolvedValue(buildConfigWithVision(true) as any);
    Element.prototype.scrollIntoView = vi.fn();
    URL.createObjectURL = vi.fn(() => 'blob:chat-attachment');
    URL.revokeObjectURL = vi.fn();
    useConversationStore.getState().reset();
    useChatTraceStore.getState().reset();
    useConversationStore.getState().setCurrentSessionId('session-1');
  });

  it('renders historical assistant messages with their stored persona identity', async () => {
    vi.mocked(personasApi.list).mockResolvedValue({
      success: true,
      data: [
        {
          persona_id: 'persona-archived',
          name: 'Archived Persona',
          slug: 'archived-persona',
          locale: 'en',
          avatar_path: '/avatars/archived.png',
          group_name: 'custom',
          sort_order: 0,
          is_builtin: false,
          description: '',
          deleted_at: 1234,
        },
      ],
    } as any);
    useConversationStore.getState().receiveHistory(
      'session-1',
      normalizeHistoryMessages([
        {
          role: 'assistant',
          content: 'Stored persona answer',
          timestamp: 1000,
          turn_id: 't-persona',
          kind: 'assistant',
          persona_id: 'persona-archived',
        },
      ])
    );

    render(<ChatPage />);

    expect(await screen.findByText('Archived Persona')).toBeInTheDocument();
    expect(screen.getByText('Stored persona answer')).toBeInTheDocument();
    expect(personasApi.list).toHaveBeenCalledWith({ includeDeleted: true });
  });

  it('shows the configured context window before runtime updates arrive', async () => {
    render(<ChatPage />);

    expect(await screen.findByRole('meter', {
      name: 'chat.contextUsage.label',
    })).toHaveAttribute('aria-valuemax', '1000000');
  });

  it('does not show first-conversation starter chips in empty sessions', () => {
    render(<ChatPage />);

    expect(screen.queryByText('firstConversation.chips.refineText')).not.toBeInTheDocument();
    expect(screen.queryByText('firstConversation.chips.plan')).not.toBeInTheDocument();
  });

  it('re-fetches history when switching back to a session', async () => {
    vi.mocked(messagesApi.getHistory)
      .mockResolvedValue({ messages: [] } as any)
      .mockResolvedValue({ messages: [] } as any)
      .mockResolvedValue({ messages: [] } as any);

    useConversationStore.getState().hydrateSessions([
      {
        session_id: 'session-1',
        title: 'Session 1',
        last_message_preview: '',
        last_user_message_preview: '',
        title_overridden: false,
        last_timestamp: 0,
        message_count: 0,
        workspace_path: null,
      },
      {
        session_id: 'session-2',
        title: 'Session 2',
        last_message_preview: '',
        last_user_message_preview: '',
        title_overridden: false,
        last_timestamp: 0,
        message_count: 0,
        workspace_path: null,
      },
    ], 'session-1');

    render(<ChatPage />);

    await waitFor(() => {
      expect(messagesApi.getHistory).toHaveBeenCalledWith('local_user', 'session-1');
    });

    act(() => {
      useConversationStore.getState().setCurrentSessionId('session-2');
    });

    await waitFor(() => {
      expect(messagesApi.getHistory).toHaveBeenCalledWith('local_user', 'session-2');
    });

    act(() => {
      useConversationStore.getState().setCurrentSessionId('session-1');
    });

    await waitFor(() => {
      expect(messagesApi.getHistory).toHaveBeenCalledTimes(3);
      expect(messagesApi.getHistory).toHaveBeenLastCalledWith('local_user', 'session-1');
    });
  });

  it('opens a session safety popover from the composer toolbar and applies mode changes immediately', async () => {
    const user = userEvent.setup();

    render(<ChatPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.session_trigger' }));

    expect(await screen.findByTestId('chat-session-settings-popover')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'settings.mode.off' }));

    await waitFor(() => {
      expect(updateSessionSettings).toHaveBeenCalledWith('session-1', {
        permission_mode: 'off',
        plan_approval_required: null,
      });
    });
  });

  it('renders a permission request as a chat status card', async () => {
    useConversationStore.getState().hydrateSessions([
      {
        session_id: 'session-1',
        title: 'New Chat',
        last_message_preview: '',
        last_user_message_preview: '',
        title_overridden: false,
        last_timestamp: 0,
        message_count: 0,
        workspace_path: null,
      },
    ], 'session-1');
    useConversationStore.getState().upsertMessage('session-1', {
      id: 'permission:req-1',
      messageId: 'permission:req-1',
      role: 'assistant',
      kind: 'status',
      messageKind: 'permission_request',
      content: 'git_push',
      timestamp: Date.now(),
      payload: {
        permission_request_id: 'req-1',
        tool: 'git_push',
        risk_level: 'high',
        origin: 'main_loop',
        tool_args: { remote: 'origin' },
      },
    });

    render(<ChatPage />);

    expect(await screen.findByText('permission.card.waiting')).toBeInTheDocument();
    expect(screen.getByText('git_push')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'permission.card.review' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'permission.card.allow_once' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'permission.card.deny_once' })).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'permission.card.allow_once' }));

    await waitFor(() => {
      expect(respondPermission).toHaveBeenCalledWith('req-1', {
        outcome: 'allow',
        scope: 'one_shot',
      });
    });
  });

  it('renders an ask request as an assistant bubble with composer quick replies', async () => {
    useConversationStore.getState().hydrateSessions([
      {
        session_id: 'session-1',
        title: 'New Chat',
        last_message_preview: '',
        last_user_message_preview: '',
        title_overridden: false,
        last_timestamp: 0,
        message_count: 0,
        workspace_path: null,
      },
    ], 'session-1');
    useConversationStore.getState().upsertMessage('session-1', {
      id: 'ask:ask-1',
      messageId: 'ask:ask-1',
      role: 'assistant',
      kind: 'assistant',
      messageKind: 'ask_request',
      content: 'Which branch should I use?',
      timestamp: Date.now(),
      payload: {
        ask_request_id: 'ask-1',
        question: 'Which branch should I use?',
        options: ['main', 'develop'],
        allow_free_text: true,
        expires_at_ms: Date.now() + 300_000,
        background: false,
      },
    });
    vi.mocked(messagesApi.sendMessage).mockResolvedValueOnce({
      success: true,
      message: 'ok',
      data: {
        user_id: 'local_user',
        session_id: 'session-1',
        handled_as: 'ask_response',
        ask_request_id: 'ask-1',
        message_length: 4,
        timestamp: Date.now() / 1000,
      },
    });

    render(<ChatPage />);

    expect(await screen.findByText('Which branch should I use?')).toBeInTheDocument();
    expect(screen.queryByText('ask.card.waiting')).not.toBeInTheDocument();
    expect(screen.getByTestId('ask-composer-quick-replies')).toBeInTheDocument();
    expect(screen.getByText('main')).toBeInTheDocument();

    await userEvent.click(screen.getByTestId('ask-composer-option-main'));
    expect(screen.getByPlaceholderText('chat.inputPlaceholder')).toHaveValue('main');
    await userEvent.click(screen.getByRole('button', { name: 'chat.send' }));

    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledWith(expect.objectContaining({
        user_id: 'local_user',
        session_id: 'session-1',
        message: 'main',
      }));
    });
    await waitFor(() => {
      expect(screen.queryByTestId('ask-composer-quick-replies')).not.toBeInTheDocument();
    });
    expect(screen.getAllByText('Which branch should I use?').length).toBeGreaterThan(0);
    expect(screen.getByText('ask.answered')).toBeInTheDocument();
    expect(screen.queryByText('ask.expires_in')).not.toBeInTheDocument();
    expect(screen.getAllByText('main').length).toBeGreaterThan(0);
    const storedMessages = useConversationStore.getState().messagesBySession['session-1'] || [];
    expect(storedMessages.some((message) => message.messageKind === 'ask_response' && message.content === 'main')).toBe(true);
    expect(storedMessages.some((message) => message.messageKind === 'ask_request' && message.payload?.status === 'answered')).toBe(true);
    expect(respondAsk).not.toHaveBeenCalled();
    expect(messagesApi.sendMessage).not.toHaveBeenCalledWith(expect.objectContaining({
      client_turn_id: expect.any(String),
    }));
  });

  it('restores the ask bubble if it is cleared while the answer is sending', async () => {
    useConversationStore.getState().hydrateSessions([
      {
        session_id: 'session-1',
        title: 'New Chat',
        last_message_preview: '',
        last_user_message_preview: '',
        title_overridden: false,
        last_timestamp: 0,
        message_count: 0,
        workspace_path: null,
      },
    ], 'session-1');
    useConversationStore.getState().upsertMessage('session-1', {
      id: 'ask:ask-cleared',
      messageId: 'ask:ask-cleared',
      role: 'assistant',
      kind: 'assistant',
      messageKind: 'ask_request',
      content: 'Which branch should I use?',
      timestamp: Date.now(),
      payload: {
        ask_request_id: 'ask-cleared',
        question: 'Which branch should I use?',
        options: ['main'],
        allow_free_text: true,
        expires_at_ms: Date.now() + 300_000,
        background: false,
      },
    });
    let resolveSendMessage: ((value: Awaited<ReturnType<typeof messagesApi.sendMessage>>) => void) | null = null;
    vi.mocked(messagesApi.sendMessage).mockReturnValueOnce(new Promise((resolve) => {
      resolveSendMessage = resolve;
    }));

    render(<ChatPage />);

    await userEvent.click(await screen.findByTestId('ask-composer-option-main'));
    await userEvent.click(screen.getByRole('button', { name: 'chat.send' }));
    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalled();
    });

    act(() => {
      useConversationStore.getState().removeMessage('session-1', 'ask:ask-cleared');
      resolveSendMessage?.({
        success: true,
        message: 'ok',
        data: {
          user_id: 'local_user',
          session_id: 'session-1',
          handled_as: 'ask_response',
          ask_request_id: 'ask-cleared',
          message_length: 4,
          timestamp: Date.now() / 1000,
        },
      });
    });

    await waitFor(() => {
      expect(screen.getAllByText('Which branch should I use?').length).toBeGreaterThan(0);
    });
    const storedMessages = useConversationStore.getState().messagesBySession['session-1'] || [];
    expect(storedMessages.some((message) => message.messageKind === 'ask_request' && message.payload?.status === 'answered')).toBe(true);
    expect(storedMessages.some((message) => message.messageKind === 'ask_response' && message.content === 'main')).toBe(true);
  });

  it('renders the active execution card after later in-run transcript messages', async () => {
    useConversationStore.getState().hydrateSessions([
      {
        session_id: 'session-1',
        title: 'New Chat',
        last_message_preview: '',
        last_user_message_preview: '',
        title_overridden: false,
        last_timestamp: 0,
        message_count: 0,
        workspace_path: null,
      },
    ], 'session-1');

    render(<ChatPage />);

    act(() => {
      realtimeListener?.({
        event: 'execution_trace_update',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-tail-placeholder',
          trace_summary: {
            turn_id: 'turn-tail-placeholder',
            mode: 'orchestration',
            status: 'running',
            headline: '正在分析项目',
            active_steps: 1,
            completed_steps: 0,
            failed_steps: 0,
            duration_seconds: 0.8,
            trace_available: true,
          },
        },
      });
    });

    act(() => {
      realtimeListener?.({
        event: 'chat_message_upserted',
        data: {
          session_id: 'session-1',
          message: {
            message_id: 'ask:tail-order',
            message_kind: 'ask_request',
            role: 'assistant',
            kind: 'assistant',
            content: 'Should I continue?',
            timestamp: Date.now() / 1000 + 1,
            payload: {
              ask_request_id: 'tail-order',
              question: 'Should I continue?',
              options: ['yes'],
              allow_free_text: true,
              expires_at_ms: Date.now() + 300_000,
            },
          },
        },
      });
    });

    const askText = await screen.findByText('Should I continue?');
    const executionCard = await screen.findByTestId('chat-trace-status-card-turn-tail-placeholder');
    expect(Boolean(askText.compareDocumentPosition(executionCard) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true);
  });

  it('renders plan and todo state as chat status cards', async () => {
    useConversationStore.getState().hydrateSessions([
      {
        session_id: 'session-1',
        title: 'New Chat',
        last_message_preview: '',
        last_user_message_preview: '',
        title_overridden: false,
        last_timestamp: 0,
        message_count: 0,
        workspace_path: null,
      },
    ], 'session-1');
    useConversationStore.getState().upsertMessage('session-1', {
      id: 'plan:turn-1',
      messageId: 'plan:turn-1',
      role: 'assistant',
      kind: 'status',
      messageKind: 'plan_state',
      content: '1. Inspect\n2. Fix',
      timestamp: Date.now(),
      payload: {
        active: true,
        plan_text: '1. Inspect\n2. Fix',
        entered_at_ms: 1,
        exited_at_ms: null,
      },
    });
    useConversationStore.getState().upsertMessage('session-1', {
      id: 'todo:turn-1',
      messageId: 'todo:turn-1',
      role: 'assistant',
      kind: 'status',
      messageKind: 'todo_state',
      content: 'Inspect runtime drift\nPatch UI',
      timestamp: Date.now(),
      payload: {
        items: [
          { id: 'todo-1', content: 'Inspect runtime drift', status: 'in_progress', created_at_ms: 1, updated_at_ms: 2 },
          { id: 'todo-2', content: 'Patch UI', status: 'completed', created_at_ms: 1, updated_at_ms: 3 },
        ],
      },
    });

    render(<ChatPage />);

    expect(await screen.findByText('control:plan.badge_active')).toBeInTheDocument();
    expect(screen.getAllByText((content) => content.includes('1. Inspect')).length).toBeGreaterThan(0);
    expect(screen.getAllByText('Inspect runtime drift').length).toBeGreaterThan(0);
    expect(screen.getByText('control:todo.status.in_progress')).toBeInTheDocument();
    expect(screen.getByText('control:todo.status.completed')).toBeInTheDocument();
  });

  it('shows a bootstrap loading status card while the first assistant opening is being initialized', async () => {
    let resolveBootstrapInit: (() => void) | null = null;
    vi.mocked(personasApi.getGreeting).mockResolvedValueOnce({
      success: true,
      data: { name: 'AI', greeting: '', needs_bootstrap: true },
    } as any);
    vi.mocked(personasApi.bootstrapInit).mockImplementationOnce(
      () => new Promise((resolve) => {
        resolveBootstrapInit = () => resolve({ success: true, data: { bootstrap_active: true, opening: 'hi' } } as any);
      })
    );
    vi.mocked(messagesApi.getHistory).mockResolvedValueOnce({ messages: [] } as any);

    render(<ChatPage />);

    expect(await screen.findByText('chat.bootstrapInit.preparing')).toBeInTheDocument();

    const bootstrapInitResolver = resolveBootstrapInit as null | (() => void);
    if (bootstrapInitResolver) {
      bootstrapInitResolver();
    }

    await waitFor(() => {
      expect(screen.queryByText('chat.bootstrapInit.preparing')).not.toBeInTheDocument();
    });
    expect(personasApi.bootstrapInit).toHaveBeenCalledWith('session-1', 'local_user');
  });

  it('does not call bootstrap init again once the opening has already been injected', async () => {
    vi.mocked(personasApi.getGreeting).mockResolvedValueOnce({
      success: true,
      data: {
        name: 'AI',
        greeting: '',
        needs_bootstrap: true,
        needs_bootstrap_init: false,
      },
    } as any);

    render(<ChatPage />);

    await waitFor(() => {
      expect(personasApi.getGreeting).toHaveBeenCalled();
    });
    expect(personasApi.bootstrapInit).not.toHaveBeenCalled();
  });

  it('runs bootstrap init again when a later session also needs bootstrap', async () => {
    vi.mocked(messagesApi.getHistory).mockResolvedValue({ messages: [] } as any);
    vi.mocked(personasApi.getGreeting)
      .mockResolvedValueOnce({
        success: true,
        data: { name: 'AI', greeting: '', needs_bootstrap: true },
      } as any)
      .mockResolvedValueOnce({
        success: true,
        data: { name: 'AI', greeting: '', needs_bootstrap: true },
      } as any);
    vi.mocked(personasApi.bootstrapInit).mockResolvedValue({
      success: true,
      data: { bootstrap_active: true, opening: 'hello' },
    } as any);

    useConversationStore.getState().hydrateSessions([
      {
        session_id: 'session-1',
        title: 'Session 1',
        last_message_preview: '',
        last_user_message_preview: '',
        title_overridden: false,
        last_timestamp: 0,
        message_count: 0,
        workspace_path: null,
      },
      {
        session_id: 'session-2',
        title: 'Session 2',
        last_message_preview: '',
        last_user_message_preview: '',
        title_overridden: false,
        last_timestamp: 0,
        message_count: 0,
        workspace_path: null,
      },
    ], 'session-1');

    render(<ChatPage />);

    await waitFor(() => {
      expect(personasApi.bootstrapInit).toHaveBeenCalledWith('session-1', 'local_user');
    });

    act(() => {
      useConversationStore.getState().setCurrentSessionId('session-2');
    });

    await waitFor(() => {
      expect(personasApi.bootstrapInit).toHaveBeenCalledWith('session-2', 'local_user');
      expect(personasApi.bootstrapInit).toHaveBeenCalledTimes(2);
    });
  });

  it('shows draft attachment chips for supported image and file selections', async () => {
    const user = userEvent.setup();
    render(<ChatPage />);

    await waitFor(() => expect(configApi.get).toHaveBeenCalled());

    await user.click(screen.getByRole('button', { name: 'chat.attachments.add' }));

    const imageInput = screen.getByTestId('chat-attachments-image-input') as HTMLInputElement;
    const fileInput = screen.getByTestId('chat-attachments-file-input') as HTMLInputElement;

    await user.upload(imageInput, new File(['image-bytes'], 'diagram.png', { type: 'image/png' }));
    await user.upload(fileInput, new File(['notes'], 'notes.md', { type: 'text/markdown' }));

    expect(screen.getByTestId('chat-composer-attachments')).toBeInTheDocument();
    expect(screen.getByTestId('chat-composer-input')).toContainElement(screen.getByPlaceholderText('chat.inputPlaceholder'));
    expect(screen.getByTestId('chat-composer-toolbar')).toContainElement(screen.getByRole('button', { name: 'chat.attachments.add' }));
    expect(screen.getByText('diagram.png')).toBeInTheDocument();
    expect(screen.getByText('notes.md')).toBeInTheDocument();
  });

  it('renders a theme-aware editor-style composer shell', async () => {
    render(<ChatPage />);

    const composerInput = await screen.findByTestId('chat-composer-input');
    const composerRoot = composerInput.parentElement;
    const toolbar = screen.getByTestId('chat-composer-toolbar');
    const primaryAction = screen.getByTestId('chat-composer-primary-action');
    const sendButton = screen.getByRole('button', { name: 'chat.send' });
    const textarea = screen.getByPlaceholderText('chat.inputPlaceholder') as HTMLTextAreaElement;

    expect(composerRoot).toHaveClass('rounded-xl', 'bg-[hsl(var(--composer-background)/0.94)]');
    expect(composerRoot?.className).toContain('inset_0_0_0_1px_hsl(var(--composer-border)/0.38)');
    expect(composerRoot).not.toHaveClass('rounded-[28px]');
    expect(toolbar).not.toHaveClass('border-t');
    expect(toolbar).toHaveClass('items-end', 'px-3', 'pb-3');
    expect(primaryAction).not.toHaveClass('pb-2');
    expect(sendButton).toHaveClass(
      'h-9',
      'w-9',
      'bg-primary',
      'text-primary-foreground',
    );
    expect(textarea.style.height).toBe('72px');
  });

  it('disables image attachments when the core model does not support vision', async () => {
    const user = userEvent.setup();
    vi.mocked(configApi.get).mockResolvedValue(buildConfigWithVision(false) as any);

    render(<ChatPage />);

    await waitFor(() => expect(configApi.get).toHaveBeenCalled());
    await user.click(screen.getByRole('button', { name: 'chat.attachments.add' }));

    expect(screen.getByRole('button', { name: 'chat.attachments.addImage' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'chat.attachments.addFile' })).toBeEnabled();
  });

  it('adds pasted supported attachments and ignores unsupported files', async () => {
    render(<ChatPage />);

    await waitFor(() => expect(configApi.get).toHaveBeenCalled());

    const textarea = screen.getByPlaceholderText('chat.inputPlaceholder');
    const pastedImage = new File(['image'], 'clipboard.png', { type: 'image/png' });
    const pastedPdf = new File(['pdf'], 'report.pdf', { type: 'application/pdf' });
    const pastedZip = new File(['zip'], 'archive.zip', { type: 'application/zip' });

    fireEvent.paste(textarea, {
      clipboardData: {
        items: [
          { kind: 'file', type: pastedImage.type, getAsFile: () => pastedImage },
          { kind: 'file', type: pastedPdf.type, getAsFile: () => pastedPdf },
          { kind: 'file', type: pastedZip.type, getAsFile: () => pastedZip },
        ],
        getData: () => '',
      },
    });

    expect(screen.getByText('clipboard.png')).toBeInTheDocument();
    expect(screen.getByText('report.pdf')).toBeInTheDocument();
    expect(screen.queryByText('archive.zip')).not.toBeInTheDocument();
    expect(toastWarningMock).toHaveBeenCalledWith('chat.attachments.unsupportedFiles');
  });

  it('warns when unsupported files are selected from the file picker', async () => {
    const user = userEvent.setup();
    render(<ChatPage />);

    await waitFor(() => expect(configApi.get).toHaveBeenCalled());

    await user.click(screen.getByRole('button', { name: 'chat.attachments.add' }));

    const fileInput = screen.getByTestId('chat-attachments-file-input') as HTMLInputElement;
    fireEvent.change(fileInput, {
      target: {
        files: [
          new File(['notes'], 'notes.md', { type: 'text/markdown' }),
          new File(['zip'], 'archive.zip', { type: 'application/zip' }),
        ],
      },
    });

    expect(screen.getByText('notes.md')).toBeInTheDocument();
    expect(screen.queryByText('archive.zip')).not.toBeInTheDocument();
    expect(toastWarningMock).toHaveBeenCalledWith('chat.attachments.unsupportedFiles');
  });

  it('shows the unsupported-file warning only once in strict mode', async () => {
    const user = userEvent.setup();
    render(
      <React.StrictMode>
        <ChatPage />
      </React.StrictMode>
    );

    await waitFor(() => expect(configApi.get).toHaveBeenCalled());

    await user.click(screen.getByRole('button', { name: 'chat.attachments.add' }));

    const fileInput = screen.getByTestId('chat-attachments-file-input') as HTMLInputElement;
    fireEvent.change(fileInput, {
      target: {
        files: [new File(['zip'], 'archive.zip', { type: 'application/zip' })],
      },
    });

    expect(toastWarningMock).toHaveBeenCalledTimes(1);
    expect(toastWarningMock).toHaveBeenCalledWith('chat.attachments.unsupportedFiles');
  });

  it('rejects oversized image attachments before they enter the draft list', async () => {
    const user = userEvent.setup();
    render(<ChatPage />);

    await waitFor(() => expect(configApi.get).toHaveBeenCalled());
    await user.click(screen.getByRole('button', { name: 'chat.attachments.add' }));

    const imageInput = screen.getByTestId('chat-attachments-image-input') as HTMLInputElement;
    const hugeImage = setMockFileSize(new File(['image'], 'huge.png', { type: 'image/png' }), 20 * 1024 * 1024 + 1);

    await user.upload(imageInput, hugeImage);

    expect(screen.queryByText('huge.png')).not.toBeInTheDocument();
    expect(toastWarningMock).toHaveBeenCalledWith('chat.attachments.imageTooLarge');
  });

  it('rejects oversized file attachments before they enter the draft list', async () => {
    const user = userEvent.setup();
    render(<ChatPage />);

    await waitFor(() => expect(configApi.get).toHaveBeenCalled());
    await user.click(screen.getByRole('button', { name: 'chat.attachments.add' }));

    const fileInput = screen.getByTestId('chat-attachments-file-input') as HTMLInputElement;
    const hugeFile = setMockFileSize(new File(['notes'], 'huge.pdf', { type: 'application/pdf' }), 50 * 1024 * 1024 + 1);

    await user.upload(fileInput, hugeFile);

    expect(screen.queryByText('huge.pdf')).not.toBeInTheDocument();
    expect(toastWarningMock).toHaveBeenCalledWith('chat.attachments.fileTooLarge');
  });

  it('uploads draft attachments before sending the websocket turn payload', async () => {
    const user = userEvent.setup();
    vi.mocked(messagesApi.uploadAttachment).mockResolvedValue({
      attachment_id: 'att-1',
      kind: 'text_file',
      original_name: 'notes.md',
      mime_type: 'text/markdown',
      size_bytes: 5,
      storage_path: '/tmp/notes.md',
      sha256: 'abc',
      parse_status: 'parsed',
    } as any);

    useConversationStore.getState().hydrateSessions([
      {
        session_id: 'session-1',
        title: 'New Chat',
        last_message_preview: '',
        last_user_message_preview: '',
        title_overridden: false,
        last_timestamp: 0,
        message_count: 0,
        workspace_path: '/tmp/magi-workspace',
      },
    ], 'session-1');

    render(<ChatPage />);

    await waitFor(() => expect(configApi.get).toHaveBeenCalled());

    await user.click(screen.getByRole('button', { name: 'chat.attachments.add' }));
    const fileInput = screen.getByTestId('chat-attachments-file-input') as HTMLInputElement;
    await user.upload(fileInput, new File(['notes'], 'notes.md', { type: 'text/markdown' }));
    await user.type(screen.getByPlaceholderText('chat.inputPlaceholder'), 'Please inspect this file');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));

    await waitFor(() => expect(messagesApi.uploadAttachment).toHaveBeenCalledTimes(1));
    const uploadedTurnId = vi.mocked(messagesApi.uploadAttachment).mock.calls[0]?.[2];
    expect(messagesApi.uploadAttachment).toHaveBeenCalledWith(
      'local_user',
      'session-1',
      uploadedTurnId,
      expect.any(File),
    );
    expect(messagesApi.sendMessage).toHaveBeenCalledWith({
      user_id: 'local_user',
      session_id: 'session-1',
      message: 'Please inspect this file',
      attachments: [
        expect.objectContaining({
          attachment_id: 'att-1',
          original_name: 'notes.md',
          kind: 'text_file',
        }),
      ],
      workspace_path: '/tmp/magi-workspace',
      client_turn_id: uploadedTurnId,
    });
    await waitFor(() => {
      const pendingTurn = useConversationStore.getState().messagesBySession['session-1']
        ?.find((message) => message.turnId === uploadedTurnId && message.role === 'user');
      expect(pendingTurn?.attachments).toEqual([
        expect.objectContaining({
          attachment_id: 'att-1',
          original_name: 'notes.md',
        }),
      ]);
    });
    expect(screen.queryAllByText('notes.md')).not.toHaveLength(0);
  });

  it('renders image thumbnails for persisted history attachments', async () => {
    useConversationStore.getState().receiveHistory(
      'session-1',
      normalizeHistoryMessages([
        {
          role: 'user',
          content: '看下这张图',
          timestamp: 1000,
          turn_id: 'turn-image-history',
          kind: 'user',
          attachments: [
            {
              attachment_id: 'att-image-history',
              kind: 'image',
              original_name: 'diagram.png',
              storage_path: '/tmp/history-diagram.png',
              size_bytes: 2048,
            },
          ],
        },
      ])
    );

    render(<ChatPage />);

    const preview = await screen.findByRole('img', { name: 'diagram.png' });
    expect(preview).toHaveAttribute(
      'src',
      'http://127.0.0.1:8000/api/messages/session/session-1/attachments/att-image-history/content?user_id=local_user',
    );
    expect(screen.queryByText('diagram.png')).not.toBeInTheDocument();
    expect(screen.queryByText('chat.attachments.addImage')).not.toBeInTheDocument();
    expect(screen.queryByText('2.0 KB')).not.toBeInTheDocument();
    expect(convertFileSrcMock).not.toHaveBeenCalled();
  });

  it('opens a larger preview dialog when a persisted history image thumbnail is clicked', async () => {
    const user = userEvent.setup();

    useConversationStore.getState().receiveHistory(
      'session-1',
      normalizeHistoryMessages([
        {
          role: 'user',
          content: '看下这张图',
          timestamp: 1000,
          turn_id: 'turn-image-preview',
          kind: 'user',
          attachments: [
            {
              attachment_id: 'att-image-preview',
              kind: 'image',
              original_name: 'diagram.png',
              storage_path: '/tmp/history-diagram.png',
              size_bytes: 2048,
            },
          ],
        },
      ])
    );

    render(<ChatPage />);

    const previewButtons = await screen.findAllByRole('button', { name: 'chat.attachments.openPreview' });
    await user.click(previewButtons[0]);

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByRole('img', { name: 'diagram.png' })).toHaveAttribute(
      'src',
      'http://127.0.0.1:8000/api/messages/session/session-1/attachments/att-image-preview/content?user_id=local_user',
    );
    expect(within(dialog).getByText('diagram.png')).toHaveClass('sr-only');
    expect(within(dialog).queryByRole('button', { name: 'Close' })).not.toBeInTheDocument();
  });

  it('enters reply mode, shows quote strips, and sends reply target metadata', async () => {
    const user = userEvent.setup();

    useConversationStore.getState().receiveHistory(
      'session-1',
      normalizeHistoryMessages([
        {
          message_id: 'msg-assistant-root',
          message_kind: 'assistant_final',
          role: 'assistant',
          content: 'Root assistant answer',
          timestamp: 1000,
          turn_id: 'turn-root',
          kind: 'assistant',
        },
        {
          message_id: 'msg-user-reply',
          message_kind: 'user_text',
          role: 'user',
          content: 'Follow-up question',
          timestamp: 1100,
          turn_id: 'turn-reply',
          kind: 'user',
          reply_to: {
            message_id: 'msg-assistant-root',
            role: 'assistant',
            message_kind: 'assistant_final',
            content_excerpt: 'reply-source-excerpt',
          },
        },
      ])
    );

    render(<ChatPage />);

    expect(screen.getByText('reply-source-excerpt')).toBeInTheDocument();

    const assistantBubble = screen.getByText('Root assistant answer').closest('div');
    expect(assistantBubble).not.toBeNull();
    const replyButtons = screen.getAllByRole('button', { name: 'chat.reply.action' });
    await user.click(replyButtons[0]);

    expect(screen.getByTestId('chat-composer-reply-preview')).toHaveTextContent('Root assistant answer');

    await user.type(screen.getByPlaceholderText('chat.inputPlaceholder'), 'Reply from composer');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));

    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledWith(expect.objectContaining({
        message: 'Reply from composer',
        reply_to_message_id: 'msg-assistant-root',
      }));
    });

    const pendingReply = useConversationStore.getState().messagesBySession['session-1']
      ?.find((message) => message.turnId && message.content === 'Reply from composer');

    expect(pendingReply?.replyTo).toEqual({
      messageId: 'msg-assistant-root',
      role: 'assistant',
      messageKind: 'assistant_final',
      contentExcerpt: 'Root assistant answer',
    });
    expect(screen.queryByTestId('chat-composer-reply-preview')).not.toBeInTheDocument();
  });

  it('renders a neutral user bubble surface and keeps the layered reply card', async () => {
    useConversationStore.getState().receiveHistory(
      'session-1',
      normalizeHistoryMessages([
        {
          message_id: 'msg-user-reply-styled',
          message_kind: 'user_text',
          role: 'user',
          content: '你觉得喜欢什么天气',
          timestamp: 1100,
          turn_id: 'turn-user-reply-styled',
          kind: 'user',
          reply_to: {
            message_id: 'msg-assistant-root-style',
            role: 'assistant',
            message_kind: 'assistant_final',
            content_excerpt: '引用条预览',
          },
        },
      ])
    );

    render(<ChatPage />);

    const userBubble = screen.getByText('你觉得喜欢什么天气').parentElement;
    const replyStrip = screen.getByText('引用条预览').parentElement;

    expect(userBubble).toHaveClass(
      'bg-[hsl(var(--chat-user-background)/0.88)]',
      'text-[hsl(var(--chat-user-foreground))]',
      'rounded-tr-md',
    );
    expect(userBubble?.className).toContain('inset_0_0_0_1px_hsl(var(--chat-user-border)/0.22)');
    expect(userBubble?.className).not.toContain('bg-[#f6e7de]');
    expect(replyStrip).toHaveClass('bg-background/80', 'border-border/45', 'text-foreground');
  });

  it('merges a durable user reply event and does not request history again on terminal trace updates', async () => {
    const user = userEvent.setup();

    useConversationStore.getState().receiveHistory(
      'session-1',
      normalizeHistoryMessages([
        {
          message_id: 'msg-assistant-root',
          message_kind: 'assistant_final',
          role: 'assistant',
          content: 'Root assistant answer',
          timestamp: 1000,
          turn_id: 'turn-root',
          kind: 'assistant',
        },
      ])
    );

    render(<ChatPage />);
    await waitFor(() => expect(messagesApi.getHistory).toHaveBeenCalled());
    vi.mocked(messagesApi.getHistory).mockClear();

    await user.click(screen.getByRole('button', { name: 'chat.reply.action' }));
    await user.type(screen.getByPlaceholderText('chat.inputPlaceholder'), 'Reply from composer');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));

    const sendMessageCall = vi.mocked(messagesApi.sendMessage).mock.calls.find(
      ([payload]) => payload?.message === 'Reply from composer'
    );
    const replyTurnId = String(sendMessageCall?.[0]?.client_turn_id || '');
    expect(replyTurnId).not.toBe('');

    vi.mocked(messagesApi.sendMessage).mockClear();

    act(() => {
      realtimeListener?.({
        event: 'chat_message_upserted',
        data: {
          session_id: 'session-1',
          message: {
            message_id: 'msg-user-reply',
            message_kind: 'user_text',
            role: 'user',
            kind: 'user',
            content: 'Reply from composer',
            timestamp: 1500,
            turn_id: replyTurnId,
            reply_to: {
              message_id: 'msg-assistant-root',
              role: 'assistant',
              message_kind: 'assistant_final',
              content_excerpt: 'Root assistant answer',
            },
          },
        },
      });
    });

    await waitFor(() => {
      const mergedReply = useConversationStore.getState().messagesBySession['session-1']
        ?.find((message) => message.turnId === replyTurnId && message.role === 'user');
      expect(mergedReply?.messageId).toBe('msg-user-reply');
      expect(mergedReply?.replyTo?.messageId).toBe('msg-assistant-root');
    });

    act(() => {
      realtimeListener?.({
        event: 'execution_trace_update',
        data: {
          session_id: 'session-1',
          turn_id: replyTurnId,
          trace_summary: {
            turn_id: replyTurnId,
            mode: 'function_calling',
            status: 'completed',
            headline: 'Completed',
            active_steps: 0,
            completed_steps: 1,
            failed_steps: 0,
            duration_seconds: 1,
            trace_available: false,
          },
        },
      });
    });

    expect(messagesApi.getHistory).not.toHaveBeenCalledWith('local_user', 'session-1');
    expect(useConversationStore.getState().messagesBySession['session-1']
      ?.find((message) => message.messageId === 'msg-user-reply')?.replyTo?.contentExcerpt).toBe('Root assistant answer');
  });

  it('opens the label popover and applies an emoji label without adding a new bubble', async () => {
    const user = userEvent.setup();
    vi.mocked(messagesApi.labelMessage).mockResolvedValue({
      success: true,
      data: {
        message_id: 'msg-assistant-plain',
        label: {
          kind: 'emoji',
          text: '👍',
          applied_by: 'user',
          source: 'manual',
          created_at_ms: 1200,
        },
      },
    } as any);

    useConversationStore.getState().receiveHistory(
      'session-1',
      normalizeHistoryMessages([
        {
          message_id: 'msg-assistant-labeled',
          message_kind: 'assistant_final',
          role: 'assistant',
          content: 'Already labeled',
          timestamp: 1000,
          turn_id: 'turn-labeled',
          kind: 'assistant',
          label: {
            kind: 'emoji',
            text: '👌',
            applied_by: 'assistant',
            source: 'manual',
            created_at_ms: 1001,
          },
        } as any,
        {
          message_id: 'msg-assistant-plain',
          message_kind: 'assistant_final',
          role: 'assistant',
          content: 'Needs a label',
          timestamp: 1100,
          turn_id: 'turn-plain',
          kind: 'assistant',
        },
      ])
    );

    render(<ChatPage />);

    expect(screen.getByText('👌')).toBeInTheDocument();

    const beforeCount = useConversationStore.getState().messagesBySession['session-1']?.length;
    const labelButtons = screen.getAllByRole('button', { name: 'chat.label.action' });
    await user.click(labelButtons[1]);
    expect(screen.getByTestId('chat-label-popover')).toBeInTheDocument();
    expect(screen.getByTestId('chat-label-popover')).toHaveClass('fixed');
    expect(screen.getAllByTestId('chat-label-action-wrap')[1]).toHaveClass('flex', 'items-center');

    await user.click(screen.getByRole('button', { name: '👍' }));

    await waitFor(() => {
      expect(messagesApi.labelMessage).toHaveBeenCalledWith('local_user', 'session-1', 'msg-assistant-plain', {
        kind: 'emoji',
        text: '👍',
        applied_by: 'user',
        source: 'manual',
      });
    });

    await waitFor(() => {
      expect(screen.getAllByText('👍').length).toBeGreaterThan(0);
    });

    const afterMessages = useConversationStore.getState().messagesBySession['session-1'] || [];
    const labeledMessage = afterMessages.find((message) => message.messageId === 'msg-assistant-plain');

    expect(afterMessages).toHaveLength(beforeCount || 0);
    expect(labeledMessage?.label).toEqual({
      kind: 'emoji',
      text: '👍',
      appliedBy: 'user',
      source: 'manual',
      createdAtMs: 1200,
    });
  });

  it('applies a custom text label from the popover and closes it afterwards', async () => {
    const user = userEvent.setup();
    vi.mocked(messagesApi.labelMessage).mockResolvedValue({
      success: true,
      data: {
        message_id: 'msg-assistant-custom-label',
        label: {
          kind: 'text',
          text: '记一下',
          applied_by: 'user',
          source: 'manual',
          created_at_ms: 2200,
        },
      },
    } as any);

    useConversationStore.getState().receiveHistory(
      'session-1',
      normalizeHistoryMessages([
        {
          message_id: 'msg-assistant-custom-label',
          message_kind: 'assistant_final',
          role: 'assistant',
          content: 'Custom label target',
          timestamp: 2100,
          turn_id: 'turn-custom',
          kind: 'assistant',
        } as any,
      ])
    );

    render(<ChatPage />);

    await user.click(screen.getByRole('button', { name: 'chat.label.action' }));
    await user.type(screen.getByPlaceholderText('chat.label.customPlaceholder'), '记一下');
    await user.click(screen.getByRole('button', { name: 'chat.label.send' }));

    await waitFor(() => {
      expect(messagesApi.labelMessage).toHaveBeenCalledWith('local_user', 'session-1', 'msg-assistant-custom-label', {
        kind: 'text',
        text: '记一下',
        applied_by: 'user',
        source: 'manual',
      });
    });

    expect(screen.queryByTestId('chat-label-popover')).not.toBeInTheDocument();
    expect(screen.getByText('记一下')).toBeInTheDocument();
  });

  it('does not truncate the custom label while IME composition is still active', async () => {
    const user = userEvent.setup();

    useConversationStore.getState().receiveHistory(
      'session-1',
      normalizeHistoryMessages([
        {
          message_id: 'msg-assistant-ime-label',
          message_kind: 'assistant_final',
          role: 'assistant',
          content: 'IME label target',
          timestamp: 2200,
          turn_id: 'turn-ime',
          kind: 'assistant',
        } as any,
      ])
    );

    render(<ChatPage />);

    await user.click(screen.getByRole('button', { name: 'chat.label.action' }));
    const input = screen.getByPlaceholderText('chat.label.customPlaceholder') as HTMLInputElement;

    fireEvent.compositionStart(input);
    fireEvent.change(input, { target: { value: 'nishabi' } });
    expect(input.value).toBe('nishabi');

    fireEvent.compositionEnd(input, { data: '你好吗朋友' });
    fireEvent.change(input, { target: { value: '你好吗朋友' } });
    expect(input.value).toBe('你好吗朋');
  });

  it('opens a message context menu with reply, copy, and delete actions', async () => {
    const user = userEvent.setup();
    const clipboardWriteText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(window.navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: clipboardWriteText,
      },
    });
    vi.mocked(messagesApi.deleteMessage).mockResolvedValue({
      success: true,
      user_id: 'local_user',
      session_id: 'session-1',
      deleted_message_id: 'msg-assistant-context',
    } as any);

    useConversationStore.getState().receiveHistory(
      'session-1',
      normalizeHistoryMessages([
        {
          message_id: 'msg-user-context',
          message_kind: 'user_text',
          role: 'user',
          content: 'User asks here',
          timestamp: 1000,
          turn_id: 'turn-user-context',
          kind: 'user',
        } as any,
        {
          message_id: 'msg-assistant-context',
          message_kind: 'assistant_final',
          role: 'assistant',
          content: '**Answer** from AI',
          timestamp: 1100,
          turn_id: 'turn-assistant-context',
          kind: 'assistant',
        } as any,
      ])
    );

    render(<ChatPage />);

    fireEvent.contextMenu(screen.getByText('Answer'));

    const menu = screen.getByTestId('chat-message-context-menu');
    expect(within(menu).getByRole('button', { name: 'chat.context.reply' })).toBeInTheDocument();
    expect(within(menu).getByRole('button', { name: 'chat.context.copyMarkdown' })).toBeInTheDocument();
    expect(within(menu).getByRole('button', { name: 'chat.context.copyPlain' })).toBeInTheDocument();
    expect(within(menu).getByRole('button', { name: 'chat.context.delete' })).toBeInTheDocument();

    await user.click(within(menu).getByRole('button', { name: 'chat.context.copyPlain' }));
    expect(clipboardWriteText).toHaveBeenCalledWith('Answer from AI');

    fireEvent.contextMenu(screen.getByText('Answer'));
    await user.click(screen.getByRole('button', { name: 'chat.context.reply' }));
    expect(screen.getByTestId('chat-composer-reply-preview')).toHaveTextContent('**Answer** from AI');

    fireEvent.contextMenu(screen.getByText('Answer'));
    await user.click(screen.getByRole('button', { name: 'chat.context.delete' }));

    await waitFor(() => {
      expect(messagesApi.deleteMessage).toHaveBeenCalledWith('local_user', 'session-1', 'msg-assistant-context');
    });
    expect(screen.queryByText('Answer')).not.toBeInTheDocument();
  });

  it('opens assistant markdown links through the desktop external link handler', async () => {
    const user = userEvent.setup();

    useConversationStore.getState().receiveHistory(
      'session-1',
      normalizeHistoryMessages([
        {
          message_id: 'msg-assistant-link',
          message_kind: 'assistant_final',
          role: 'assistant',
          content: '[点击查看实时K线图](https://example.com/aapl)',
          timestamp: 1200,
          turn_id: 'turn-link',
          kind: 'assistant',
        } as any,
      ])
    );

    render(<ChatPage />);

    await user.click(screen.getByRole('link', { name: '点击查看实时K线图' }));

    expect(openExternalUrlMock).toHaveBeenCalledWith('https://example.com/aapl');
  });

  it('renders trace entry when an agent response arrives through chat subscription', async () => {
    render(<ChatPage />);

    act(() => {
      realtimeListener?.({
        event: 'agent_response',
        data: {
          session_id: 'session-1',
          message_id: 'msg-final-1',
          message_kind: 'assistant_final',
          content: '整理好了',
          timestamp: Date.now() / 1000,
          turn_id: 'turn-1',
          trace_available: true,
          trace_summary: {
            turn_id: 'turn-1',
            mode: 'function_calling',
            status: 'completed',
            headline: '工具链已完成',
            active_steps: 0,
            completed_steps: 2,
            failed_steps: 0,
            duration_seconds: 1.2,
            trace_available: true,
          },
        },
      });
    });

    await waitFor(() => {
      expect(screen.getByText('整理好了')).toBeInTheDocument();
    });
    expect(
      useConversationStore.getState().messagesBySession['session-1']?.find((message) => message.turnId === 'turn-1')?.id
    ).toBe('msg-final-1');
    expect(screen.getByRole('button', { name: 'chat.trace.view' })).toBeInTheDocument();
  });

  it('loads trace when opening a trace entry and refreshes it while the drawer stays open', async () => {
    const user = userEvent.setup();
    vi.mocked(messagesApi.getTrace).mockResolvedValue({
      success: true,
      user_id: 'local_user',
      session_id: 'session-1',
      turn_id: 'turn-trace-open',
      trace: {
        turn_id: 'turn-trace-open',
        user_id: 'local_user',
        session_id: 'session-1',
        status: 'running',
        mode: 'orchestration',
        summary: {
          turn_id: 'turn-trace-open',
          mode: 'orchestration',
          status: 'running',
          headline: '正在分析项目',
          active_steps: 2,
          completed_steps: 1,
          failed_steps: 0,
          duration_seconds: 1.4,
          trace_available: true,
        },
        root: {
          id: 'root-turn-trace-open',
          kind: 'task',
          label: 'Inspect repository',
          status: 'running',
          metadata: {},
          children: [],
        },
      },
    } as any);

    render(<ChatPage />);

    act(() => {
      realtimeListener?.({
        event: 'agent_response',
        data: {
          session_id: 'session-1',
          message_id: 'msg-final-trace-open',
          message_kind: 'assistant_final',
          content: 'Trace refresh target',
          timestamp: Date.now() / 1000,
          turn_id: 'turn-trace-open',
          trace_available: true,
          trace_summary: {
            turn_id: 'turn-trace-open',
            mode: 'orchestration',
            status: 'running',
            headline: '正在分析项目',
            active_steps: 2,
            completed_steps: 1,
            failed_steps: 0,
            duration_seconds: 1.4,
            trace_available: true,
          },
        },
      });
    });

    const messageText = await screen.findByText('Trace refresh target');
    const messageRow = messageText.closest('div.items-start');
    expect(messageRow).not.toBeNull();
    if (!messageRow) {
      throw new Error('Expected the assistant trace row to exist.');
    }

    const scopedRow = messageRow as HTMLElement;
    await user.click(within(scopedRow).getByRole('button', { name: 'chat.trace.view' }));

    await waitFor(() => {
      expect(messagesApi.getTrace).toHaveBeenCalledWith('local_user', 'session-1', 'turn-trace-open');
    });
    await waitFor(() => {
      expect(useChatTraceStore.getState().activeTurnId).toBe('turn-trace-open');
      expect(useChatTraceStore.getState().drawerOpen).toBe(true);
    });

    act(() => {
      realtimeListener?.({
        event: 'execution_trace_update',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-trace-open',
          trace_summary: {
            turn_id: 'turn-trace-open',
            mode: 'orchestration',
            status: 'running',
            headline: '正在分析项目',
            active_steps: 2,
            completed_steps: 1,
            failed_steps: 0,
            duration_seconds: 1.5,
            trace_available: true,
          },
        },
      });
    });

    await waitFor(() => {
      expect(messagesApi.getTrace).toHaveBeenCalledTimes(2);
    });
  });

  it('returns the composer to send mode after an agent response when interjection is disabled', async () => {
    const user = userEvent.setup();
    const config = buildConfigWithVision(true) as any;
    config.data.preferences = {
      ...(config.data.preferences || {}),
      allow_interjection: false,
    };
    vi.mocked(configApi.get).mockResolvedValue(config);

    render(<ChatPage />);

    await waitFor(() => expect(configApi.get).toHaveBeenCalled());

    await user.type(screen.getByPlaceholderText('chat.inputPlaceholder'), 'Please continue');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));

    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledWith(expect.objectContaining({
        message: 'Please continue',
      }));
    });

    const pendingTurnId = String(vi.mocked(messagesApi.sendMessage).mock.calls[0]?.[0]?.client_turn_id || '');
    expect(pendingTurnId).not.toBe('');

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'chat.stop' })).toBeInTheDocument();
    });

    act(() => {
      realtimeListener?.({
        event: 'agent_response',
        data: {
          session_id: 'session-1',
          turn_id: pendingTurnId,
          message_id: 'msg-agent-response-stop-reset',
          message_kind: 'assistant_final',
          content: 'Handled',
          timestamp: Date.now() / 1000,
        },
      });
    });

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'chat.send' })).toBeInTheDocument();
    });
  });

  it('preserves millisecond timestamps from realtime agent responses', async () => {
    render(<ChatPage />);

    act(() => {
      realtimeListener?.({
        event: 'agent_response',
        data: {
          session_id: 'session-1',
          message_id: 'msg-final-ms',
          message_kind: 'assistant_final',
          content: '毫秒时间戳',
          timestamp: 1710000000000,
          turn_id: 'turn-ms',
        },
      });
    });

    await waitFor(() => {
      expect(screen.getByText('毫秒时间戳')).toBeInTheDocument();
    });

    expect(
      useConversationStore.getState().messagesBySession['session-1']?.find((message) => message.turnId === 'turn-ms')?.timestamp
    ).toBe(1710000000000);
  });

  it('shows assistant image attachments immediately from realtime agent responses', async () => {
    render(<ChatPage />);

    act(() => {
      realtimeListener?.({
        event: 'agent_response',
        data: {
          session_id: 'session-1',
          message_id: 'msg-final-image-live',
          message_kind: 'assistant_final',
          content: '图片已生成。',
          timestamp: Date.now() / 1000,
          turn_id: 'turn-image-live',
          attachments: [
            {
              attachment_id: 'att-image-live',
              kind: 'image',
              original_name: 'live.png',
              size_bytes: 2048,
            },
          ],
        },
      });
    });

    expect(await screen.findByRole('img', { name: 'live.png' })).toHaveAttribute(
      'src',
      'http://127.0.0.1:8000/api/messages/session/session-1/attachments/att-image-live/content?user_id=local_user',
    );
  });

  it('hides the trace entry when ux plan disables trace display', async () => {
    const view = render(<ChatPage />);
    const scoped = within(view.container);

    act(() => {
      realtimeListener?.({
        event: 'agent_response',
        data: {
          session_id: 'session-1',
          content: '整理好了',
          timestamp: Date.now() / 1000,
          turn_id: 'turn-hidden',
          ux_plan: {
            assistant_surface_mode: 'final_only',
            trace_display_mode: 'none',
          },
          trace_available: true,
          trace_summary: {
            turn_id: 'turn-hidden',
            mode: 'function_calling',
            status: 'completed',
            headline: '工具链已完成',
            active_steps: 0,
            completed_steps: 2,
            failed_steps: 0,
            duration_seconds: 1.2,
            trace_available: true,
          },
        },
      });
    });

    await waitFor(() => {
      expect(scoped.getAllByText('整理好了').length).toBeGreaterThan(0);
    });
    const hiddenMessage = useConversationStore.getState().messagesBySession['session-1']
      ?.find((message) => message.turnId === 'turn-hidden');
    expect(hiddenMessage?.traceDisplayMode).toBe('none');
    expect(
      shouldShowTraceEntry(hiddenMessage ?? { turnId: '', traceDisplayMode: null, traceAvailable: false, traceSummary: null })
    ).toBe(false);
  });

  it('renders a subtle trace entry for direct replies when ux plan requests collapsible trace display', async () => {
    const view = render(<ChatPage />);
    const scoped = within(view.container);

    act(() => {
      realtimeListener?.({
        event: 'agent_response',
        data: {
          session_id: 'session-1',
          content: '你好，我在。',
          timestamp: Date.now() / 1000,
          turn_id: 'turn-direct-visible',
          ux_plan: {
            assistant_surface_mode: 'final_only',
            trace_display_mode: 'collapsible',
          },
          trace_available: true,
          trace_summary: {
            turn_id: 'turn-direct-visible',
            mode: 'direct_llm',
            status: 'completed',
            headline: '直答已完成',
            active_steps: 0,
            completed_steps: 1,
            failed_steps: 0,
            duration_seconds: 0.8,
            trace_available: true,
          },
        },
      });
    });

    await waitFor(() => {
      expect(scoped.getByText('你好，我在。')).toBeInTheDocument();
    });

    expect(view.container.querySelector('[data-trace-variant="default"]')).toBeInTheDocument();
  });

  it('keeps the default trace entry style when ux plan requests prominent trace display', async () => {
    const view = render(<ChatPage />);
    const scoped = within(view.container);

    act(() => {
      realtimeListener?.({
        event: 'agent_response',
        data: {
          session_id: 'session-1',
          content: '需要你看下执行细节',
          timestamp: Date.now() / 1000,
          turn_id: 'turn-prominent',
          ux_plan: {
            assistant_surface_mode: 'final_only',
            trace_display_mode: 'prominent',
            allow_trace_collapse: true,
          },
          trace_available: true,
          trace_summary: {
            turn_id: 'turn-prominent',
            mode: 'orchestration',
            status: 'completed',
            headline: '任务链路已生成',
            active_steps: 0,
            completed_steps: 3,
            failed_steps: 0,
            duration_seconds: 2.1,
            trace_available: true,
          },
        },
      });
    });

    await waitFor(() => {
      expect(scoped.getByText('需要你看下执行细节')).toBeInTheDocument();
    });

    expect(view.container.querySelector('[data-trace-variant="default"]')).toBeInTheDocument();
    expect(view.container.querySelector('[data-trace-variant="prominent"]')).not.toBeInTheDocument();
  });

  it('renders an interim assistant message when turn ux plan requests interim-then-final', async () => {
    render(<ChatPage />);

    act(() => {
      realtimeListener?.({
        event: 'turn_ux_plan',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-2',
          message_id: 'msg-interim-1',
          message_kind: 'assistant_interim',
          ux_plan: {
            assistant_surface_mode: 'interim_then_final',
            interim_text: '稍等我查一下',
          },
        },
      });
    });

    await waitFor(() => {
      expect(screen.getByText('稍等我查一下')).toBeInTheDocument();
    });
    expect(
      useConversationStore.getState().messagesBySession['session-1']?.find((message) => message.turnId === 'turn-2' && message.kind === 'assistant')?.id
    ).toBe('msg-interim-1');

    act(() => {
      realtimeListener?.({
        event: 'agent_response',
        data: {
          session_id: 'session-1',
          content: '已经查好了',
          timestamp: Date.now() / 1000,
          turn_id: 'turn-2',
          ux_plan: {
            assistant_surface_mode: 'interim_then_final',
          },
        },
      });
    });

    await waitFor(() => {
      expect(screen.getByText('已经查好了')).toBeInTheDocument();
    });
    expect(screen.getByText('稍等我查一下')).toBeInTheDocument();
  });

  it('renders a reaction-only acknowledgement without an assistant bubble', async () => {
    render(<ChatPage />);

    act(() => {
      useConversationStore.getState().appendPendingTurn({
        sessionId: 'session-1',
        input: '嗯',
        turnId: 'turn-3',
        timestamp: Date.now(),
        pendingLabel: 'thinking',
      });
    });

    act(() => {
      realtimeListener?.({
        event: 'turn_ux_plan',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-3',
          ux_plan: {
            assistant_surface_mode: 'reaction_only',
            reaction_style: 'acknowledge',
          },
        },
      });
    });

    await waitFor(() => {
      expect(screen.getAllByText('👌').length).toBeGreaterThan(0);
    });

    act(() => {
      realtimeListener?.({
        event: 'agent_response',
        data: {
          session_id: 'session-1',
          content: '👌',
          timestamp: Date.now() / 1000,
          message_id: 'msg-reaction-only',
          message_kind: 'assistant_reaction',
          turn_id: 'turn-3',
          ux_plan: {
            assistant_surface_mode: 'reaction_only',
            reaction_style: 'acknowledge',
          },
        },
      });
    });

    await waitFor(() => {
      expect(screen.queryByText('msg-reaction-only')).not.toBeInTheDocument();
    });
  });

  it('rehydrates a persisted reaction-only turn without creating an assistant bubble', async () => {
    useConversationStore.getState().receiveHistory(
      'session-1',
      normalizeHistoryMessages([
        {
          message_id: 'msg-user-reaction',
          message_kind: 'user_text',
          role: 'user',
          content: '嗯',
          timestamp: 1000,
          turn_id: 'turn-reaction-history',
          kind: 'user',
          label: {
            kind: 'emoji',
            text: '👌',
            applied_by: 'assistant',
            source: 'reaction_only',
            created_at_ms: 1001,
          },
        },
      ])
    );

    render(<ChatPage />);

    await waitFor(() => {
      expect(screen.getAllByText('嗯').length).toBeGreaterThan(0);
    });

    expect(screen.getAllByText('👌').length).toBeGreaterThan(0);
    expect(screen.queryByText('msg-reaction-only')).not.toBeInTheDocument();
    expect(
      useConversationStore.getState().messagesBySession['session-1']?.filter((message) => message.turnId === 'turn-reaction-history')
    ).toHaveLength(1);
  });

  it('hides trace entry after reload when persisted history says trace display is none', async () => {
    useConversationStore.getState().receiveHistory(
      'session-1',
      normalizeHistoryMessages([
        {
          message_id: 'msg-final-hidden',
          message_kind: 'assistant_final',
          role: 'assistant',
          content: '整理好了',
          timestamp: 1000,
          turn_id: 'turn-hidden-history',
          kind: 'assistant',
          trace_available: true,
          trace_summary: {
            turn_id: 'turn-hidden-history',
            mode: 'function_calling',
            status: 'completed',
            headline: '工具链已完成',
            active_steps: 0,
            completed_steps: 2,
            failed_steps: 0,
            duration_seconds: 1.2,
            trace_available: true,
          },
          trace_display_mode: 'none',
          allow_trace_collapse: false,
        },
      ])
    );

    render(<ChatPage />);

    await waitFor(() => {
      expect(screen.getAllByText('整理好了').length).toBeGreaterThan(0);
    });

    const hiddenMessage = useConversationStore.getState().messagesBySession['session-1']
      ?.find((message) => message.turnId === 'turn-hidden-history');
    expect(hiddenMessage?.traceDisplayMode).toBe('none');
    expect(
      shouldShowTraceEntry(hiddenMessage ?? { turnId: '', traceDisplayMode: null, traceAvailable: false, traceSummary: null })
    ).toBe(false);
  });

  it('renders an interim assistant bubble when ux plan requests visible thinking feedback', async () => {
    render(<ChatPage />);

    act(() => {
      useConversationStore.getState().appendPendingTurn({
        sessionId: 'session-1',
        input: '帮我查一下',
        turnId: 'turn-4',
        timestamp: Date.now(),
        pendingLabel: 'thinking',
      });
    });

    act(() => {
      realtimeListener?.({
        event: 'turn_ux_plan',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-4',
          ux_plan: {
            assistant_surface_mode: 'final_only',
            thinking_indicator: 'visible',
          },
        },
      });
    });

    await waitFor(() => {
      expect(screen.getByText('chat.trace.pending')).toBeInTheDocument();
    });
  });

  it('renders tool-call runtime details inside the assistant bubble', async () => {
    useConversationStore.getState().hydrateSessions([
      {
        session_id: 'session-1',
        title: 'New Chat',
        last_message_preview: '',
        last_user_message_preview: '',
        title_overridden: false,
        last_timestamp: 0,
        message_count: 0,
        workspace_path: null,
      },
    ], 'session-1');
    useConversationStore.getState().upsertMessage('session-1', {
      id: 'msg-tool-runtime',
      role: 'assistant',
      kind: 'assistant',
      content: '',
      timestamp: 1000,
      turnId: 'turn-tool-runtime',
      streaming: true,
      toolCalls: [
        {
          toolCallId: 'call-1',
          toolName: 'web-search',
          status: 'running',
          toolArgsText: '{"query":"magi memory architecture"}',
        },
      ],
    });

    render(<ChatPage />);

    const panels = await screen.findAllByTestId('chat-assistant-runtime-panel');
    const panel = panels.find((candidate) => within(candidate).queryByText('web-search'));
    expect(panel).toBeDefined();
    if (!panel) {
      throw new Error('Expected a runtime panel containing the tool-call details.');
    }
    expect(within(panel).getByText('chat.runtime.label')).toBeInTheDocument();
    expect(within(panel).getByText('chat.toolCalls.label')).toBeInTheDocument();
    expect(within(panel).getByText('web-search')).toBeInTheDocument();
    expect(within(panel).getByText('chat.toolCalls.running')).toBeInTheDocument();
    expect(within(panel).getByText('{"query":"magi memory architecture"}')).toBeInTheDocument();
  });

  it('renders tool-call assistant narration inside runtime activity', async () => {
    useConversationStore.getState().hydrateSessions([
      {
        session_id: 'session-1',
        title: 'New Chat',
        last_message_preview: '',
        last_user_message_preview: '',
        title_overridden: false,
        last_timestamp: 0,
        message_count: 0,
        workspace_path: null,
      },
    ], 'session-1');
    useConversationStore.getState().upsertMessage('session-1', {
      id: 'msg-status-runtime',
      role: 'assistant',
      kind: 'assistant',
      content: '',
      timestamp: 1000,
      turnId: 'turn-status-runtime',
      streaming: true,
      runtimeStatuses: [
        {
          source: 'assistant_tool_call',
          stepLabel: 'tool_call_narration',
          content: '工作区是空的，附件解析也失败了。我先试试提取它们。',
        },
      ],
    });

    render(<ChatPage />);

    const panels = await screen.findAllByTestId('chat-assistant-runtime-panel');
    const panel = panels.find((candidate) => within(candidate).queryByText('工作区是空的，附件解析也失败了。我先试试提取它们。'));
    expect(panel).toBeDefined();
    if (!panel) {
      throw new Error('Expected a runtime panel containing assistant narration.');
    }
    expect(within(panel).getByText('chat.runtime.status')).toBeInTheDocument();
    expect(within(panel).getByText('工作区是空的，附件解析也失败了。我先试试提取它们。')).toBeInTheDocument();
  });

  it('renders streamed reasoning details inside the assistant bubble', async () => {
    useConversationStore.getState().hydrateSessions([
      {
        session_id: 'session-1',
        title: 'New Chat',
        last_message_preview: '',
        last_user_message_preview: '',
        title_overridden: false,
        last_timestamp: 0,
        message_count: 0,
        workspace_path: null,
      },
    ], 'session-1');
    useConversationStore.getState().upsertMessage('session-1', {
      id: 'msg-reasoning-runtime',
      role: 'assistant',
      kind: 'assistant',
      content: '先看一下代码路径。',
      timestamp: 1001,
      turnId: 'turn-reasoning-runtime',
      streaming: true,
      reasoning: [
        {
          source: 'planner',
          stepLabel: 'Plan',
          content: 'Inspecting the execution path',
        },
      ],
    });

    render(<ChatPage />);

    const panels = await screen.findAllByTestId('chat-assistant-runtime-panel');
    const panel = panels.find((candidate) => within(candidate).queryByText('Inspecting the execution path'));
    expect(panel).toBeDefined();
    if (!panel) {
      throw new Error('Expected a runtime panel containing the reasoning details.');
    }
    expect(within(panel).getByText('chat.runtime.label')).toBeInTheDocument();
    expect(within(panel).getByText('chat.thinking.label')).toBeInTheDocument();
    expect(within(panel).getByText('Inspecting the execution path')).toBeInTheDocument();
    expect(screen.getByText('先看一下代码路径。')).toBeInTheDocument();
  });

  it('requests fresh history when a turn completes without an agent response event', () => {
    render(<ChatPage />);

    act(() => {
      realtimeListener?.({
        event: 'execution_trace_update',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-2',
          trace_summary: {
            turn_id: 'turn-2',
            mode: 'function_calling',
            status: 'completed',
            headline: '工具链已完成',
            active_steps: 0,
            completed_steps: 2,
            failed_steps: 0,
            duration_seconds: 1.2,
            trace_available: true,
          },
        },
      });
    });

    expect(messagesApi.getHistory).toHaveBeenCalledWith('local_user', 'session-1');
  });

  it('shows a trace status row on the user turn when a turn is interrupted without assistant output', async () => {
    render(<ChatPage />);

    act(() => {
      useConversationStore.getState().appendPendingTurn({
        sessionId: 'session-1',
        input: '先帮我看登录流程',
        turnId: 'turn-interrupted',
        timestamp: Date.now(),
        pendingLabel: 'thinking',
      });
    });

    act(() => {
      realtimeListener?.({
        event: 'execution_trace_update',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-interrupted',
          trace_summary: {
            turn_id: 'turn-interrupted',
            mode: 'function_calling',
            status: 'interrupted',
            headline: 'Interrupted by a newer turn',
            active_steps: 0,
            completed_steps: 1,
            failed_steps: 0,
            duration_seconds: 0.8,
            trace_available: true,
          },
        },
      });
    });

    await waitFor(() => {
      expect(screen.getByText('Interrupted by a newer turn')).toBeInTheDocument();
    });

    expect(screen.getAllByRole('button', { name: 'chat.trace.view' }).length).toBeGreaterThan(0);
  });

  it('requests run cancellation from the running interim execution bubble', async () => {
    vi.mocked(messagesApi.cancelRun).mockResolvedValue({
      success: true,
      message: 'cancelled',
      data: {
        user_id: 'local_user',
        session_id: 'session-1',
        run_id: 'run-1',
        status: 'cancelling',
      },
    });

    render(<ChatPage />);

    act(() => {
      realtimeListener?.({
        event: 'execution_trace_update',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-running',
          trace_summary: {
            turn_id: 'turn-running',
            mode: 'orchestration',
            status: 'running',
            headline: '正在分析项目',
            active_steps: 2,
            completed_steps: 1,
            failed_steps: 0,
            duration_seconds: 1.4,
            trace_available: true,
          },
        },
      });
    });

    await waitFor(() => {
      expect(screen.getByText('正在分析项目')).toBeInTheDocument();
    });

    const runningPanel = screen.getByTestId('chat-execution-panel-turn-running');
    await userEvent.click(within(runningPanel).getByRole('button', { name: 'chat.trace.cancelRun' }));

    await waitFor(() => {
      expect(messagesApi.cancelRun).toHaveBeenCalledWith('local_user', 'session-1', {
        reason: 'user_cancel',
        turnId: 'turn-running',
      });
    });
  });

  it('requests background handoff from the running interim execution bubble', async () => {
    vi.mocked(messagesApi.detachRun).mockResolvedValue({
      success: true,
      message: 'detaching',
      data: {
        user_id: 'local_user',
        session_id: 'session-1',
        run_id: 'run-1',
        status: 'detaching',
      },
    });

    render(<ChatPage />);

    act(() => {
      realtimeListener?.({
        event: 'execution_trace_update',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-running',
          trace_summary: {
            turn_id: 'turn-running',
            mode: 'orchestration',
            status: 'running',
            headline: '正在分析项目',
            active_steps: 2,
            completed_steps: 1,
            failed_steps: 0,
            duration_seconds: 1.4,
            trace_available: true,
          },
        },
      });
    });

    await waitFor(() => {
      expect(screen.getByText('正在分析项目')).toBeInTheDocument();
    });

    const runningPanel = screen.getByTestId('chat-execution-panel-turn-running');
    await userEvent.click(within(runningPanel).getByRole('button', { name: 'chat.trace.detachRun' }));

    await waitFor(() => {
      expect(messagesApi.detachRun).toHaveBeenCalledWith('local_user', 'session-1', {
        reason: 'user_detach',
        turnId: 'turn-running',
      });
    });
  });

  it('shows execution actions on assistant interim messages and can cancel the run', async () => {
    vi.mocked(messagesApi.cancelRun).mockResolvedValue({
      success: true,
      message: 'cancelled',
      data: {
        user_id: 'local_user',
        session_id: 'session-1',
        run_id: 'run-1',
        status: 'cancelling',
      },
    });

    render(<ChatPage />);

    act(() => {
      realtimeListener?.({
        event: 'turn_ux_plan',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-interim-actions',
          message_id: 'msg-interim-actions',
          message_kind: 'assistant_interim',
          ux_plan: {
            assistant_surface_mode: 'interim_then_final',
            interim_text: '让我仔细想想再回复你。',
            trace_display_mode: 'prominent',
            allow_trace_collapse: true,
          },
        },
      });
    });

    act(() => {
      realtimeListener?.({
        event: 'execution_trace_update',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-interim-actions',
          trace_summary: {
            turn_id: 'turn-interim-actions',
            mode: 'orchestration',
            status: 'running',
            headline: '正在分析项目',
            active_steps: 2,
            completed_steps: 1,
            failed_steps: 0,
            duration_seconds: 1.4,
            trace_available: true,
          },
        },
      });
    });

    await waitFor(() => {
      expect(screen.getByText('让我仔细想想再回复你。')).toBeInTheDocument();
    });

    const runningPanel = screen.getByTestId('chat-execution-panel-turn-interim-actions');
    await userEvent.click(within(runningPanel).getByRole('button', { name: 'chat.trace.cancelRun' }));

    await waitFor(() => {
      expect(messagesApi.cancelRun).toHaveBeenCalledWith('local_user', 'session-1', {
        reason: 'user_cancel',
        turnId: 'turn-interim-actions',
      });
    });
  });

  it('keeps interim execution actions visible after a todo state card appears', async () => {
    render(<ChatPage />);

    act(() => {
      realtimeListener?.({
        event: 'turn_ux_plan',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-interim-todo',
          message_id: 'msg-interim-todo',
          message_kind: 'assistant_interim',
          ux_plan: {
            assistant_surface_mode: 'interim_then_final',
            interim_text: '让我仔细想想再回复你。',
            trace_display_mode: 'prominent',
            allow_trace_collapse: true,
          },
        },
      });
    });

    act(() => {
      realtimeListener?.({
        event: 'execution_trace_update',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-interim-todo',
          trace_summary: {
            turn_id: 'turn-interim-todo',
            mode: 'orchestration',
            status: 'running',
            headline: '正在分析项目',
            active_steps: 1,
            completed_steps: 0,
            failed_steps: 0,
            duration_seconds: 0.8,
            trace_available: true,
          },
        },
      });
    });

    act(() => {
      realtimeListener?.({
        event: 'chat_message_upserted',
        data: {
          session_id: 'session-1',
          message: {
            message_id: 'todo:turn-interim-todo',
            message_kind: 'todo_state',
            role: 'assistant',
            kind: 'status',
            content: 'Search official sources',
            timestamp: Date.now() / 1000,
            turn_id: 'turn-interim-todo',
            payload: {
              items: [
                { id: 'todo-1', content: 'Search official sources', status: 'in_progress' },
              ],
            },
          },
        },
      });
    });

    await waitFor(() => {
      expect(screen.getByText('Search official sources')).toBeInTheDocument();
    });

    const runningPanel = screen.getByTestId('chat-execution-panel-turn-interim-todo');
    expect(within(runningPanel).getByRole('button', { name: 'chat.trace.cancelRun' })).toBeInTheDocument();
    expect(within(runningPanel).getByRole('button', { name: 'chat.trace.detachRun' })).toBeInTheDocument();
  });

  it('updates the running interim execution bubble from execution control websocket events', async () => {
    render(<ChatPage />);

    act(() => {
      realtimeListener?.({
        event: 'execution_trace_update',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-running',
          trace_summary: {
            turn_id: 'turn-running',
            mode: 'orchestration',
            status: 'running',
            headline: '正在分析项目',
            active_steps: 2,
            completed_steps: 1,
            failed_steps: 0,
            duration_seconds: 1.4,
            trace_available: true,
          },
        },
      });
    });

    await waitFor(() => {
      const runningPanel = screen.getByTestId('chat-execution-panel-turn-running');
      expect(within(runningPanel).getByRole('button', { name: 'chat.trace.cancelRun' })).toBeEnabled();
    });

    act(() => {
      realtimeListener?.({
        event: 'turn_execution_control',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-running',
          state: 'cancelling',
          can_cancel: false,
          label: 'Cancelling run',
        },
      });
    });

    await waitFor(() => {
      const runningPanel = screen.getByTestId('chat-execution-panel-turn-running');
      expect(within(runningPanel).getByText('chat.trace.execution.cancellingTitle')).toBeInTheDocument();
      expect(within(runningPanel).getByText('chat.trace.execution.cancellingBody')).toBeInTheDocument();
      expect(within(runningPanel).getByRole('button', { name: 'chat.trace.cancelRun' })).toBeDisabled();
    });

    act(() => {
      realtimeListener?.({
        event: 'turn_execution_control',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-running',
          state: 'cancelled',
          can_cancel: false,
          label: 'Run cancelled',
        },
      });
    });

    await waitFor(() => {
      const runningPanel = screen.getByTestId('chat-execution-panel-turn-running');
      expect(within(runningPanel).getByText('chat.trace.execution.cancelledTitle')).toBeInTheDocument();
      expect(within(runningPanel).getByText('chat.trace.execution.cancelledBody')).toBeInTheDocument();
      expect(within(runningPanel).getByText('chat.trace.execution.footerCancelled')).toBeInTheDocument();
      expect(within(runningPanel).queryByRole('button', { name: 'chat.trace.cancelRun' })).not.toBeInTheDocument();
      expect(messagesApi.getHistory).toHaveBeenCalledWith('local_user', 'session-1');
    });
  });

  it('renders a richer orchestration plan preview on the running interim execution bubble', async () => {
    render(<ChatPage />);

    act(() => {
      realtimeListener?.({
        event: 'execution_trace_update',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-plan-preview',
          trace_summary: {
            turn_id: 'turn-plan-preview',
            mode: 'orchestration',
            status: 'running',
            headline: '正在分析项目',
            active_steps: 2,
            completed_steps: 1,
            failed_steps: 0,
            duration_seconds: 1.4,
            trace_available: true,
            plan_summary: {
              planner: 'task_agent',
              parallel_mode: 'parallel',
              total_steps: 4,
              remaining_steps: 1,
              steps: [
                {
                  subtask_id: 'subtask_1',
                  label: '梳理现有文档和范围',
                  status: 'completed',
                },
                {
                  subtask_id: 'subtask_2',
                  label: '盘点代码结构与运行方式',
                  status: 'running',
                },
                {
                  subtask_id: 'subtask_3',
                  label: '整理 MVP 验收清单',
                  status: 'pending',
                },
              ],
            },
          },
        },
      });
    });

    await waitFor(() => {
      const runningPanel = screen.getByTestId('chat-execution-panel-turn-plan-preview');
      expect(within(runningPanel).getByText('梳理现有文档和范围')).toBeInTheDocument();
    });

    const runningPanel = screen.getByTestId('chat-execution-panel-turn-plan-preview');
    expect(within(runningPanel).getByText('盘点代码结构与运行方式')).toBeInTheDocument();
    expect(within(runningPanel).getByText('整理 MVP 验收清单')).toBeInTheDocument();
    expect(within(runningPanel).getByText('chat.trace.plan.stage.runningParallel')).toBeInTheDocument();
    expect(within(runningPanel).getByText('chat.trace.plan.parallel')).toBeInTheDocument();
    expect(within(runningPanel).getByText('chat.trace.plan.stepStatus.completed')).toBeInTheDocument();
    expect(within(runningPanel).getByText('chat.trace.plan.stepStatus.running')).toBeInTheDocument();
    expect(within(runningPanel).getByText('chat.trace.plan.stepStatus.pending')).toBeInTheDocument();
    expect(within(runningPanel).getByText('chat.trace.plan.moreSteps')).toBeInTheDocument();
  });

  it('does not ask the backend for a current session after subscribe event', () => {
    useConversationStore.getState().setCurrentSessionId(null);
    vi.mocked(messagesApi.sendMessage).mockClear();
    render(<ChatPage />);

    act(() => {
      realtimeListener?.({
        type: 'subscribed',
      });
    });

    expect(messagesApi.sendMessage).not.toHaveBeenCalled();
  });

  it('does not emit act warnings while handling chat updates', async () => {
    const content = 'warning-check-reply';
    render(<ChatPage />);

    act(() => {
      realtimeListener?.({
        event: 'agent_response',
        data: {
          session_id: 'session-1',
          content,
          timestamp: Date.now() / 1000,
          turn_id: 'turn-warning',
        },
      });
    });

    await waitFor(() => {
      expect(screen.getByText(content)).toBeInTheDocument();
    });

    const actWarnings = consoleErrorSpy.mock.calls.filter(([firstArg]) =>
      String(firstArg).includes('not wrapped in act')
    );
    expect(actWarnings).toHaveLength(0);
  });
});
