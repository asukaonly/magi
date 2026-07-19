import {
  defineChatPageSuite,
  realtimeListener,
  toastWarningMock,
} from '@/test/chatPageHarness';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { ChatPage } from '@/pages/Chat';
import { useConversationStore } from '@/stores/conversation-store';
import { messagesApi } from '@/api';
import {
  getAskState,
  respondAsk,
  respondPermission,
  updateSessionSettings,
} from '@/api/modules/control';
import { personasApi } from '@/api/modules/personas';

defineChatPageSuite('ChatPage control cards', () => {
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
    expect(messagesApi.sendMessage).toHaveBeenCalledWith(expect.objectContaining({
      client_turn_id: expect.stringMatching(/^turn_/),
      metadata: {
        ask_request_id: 'ask-1',
      },
    }));
  });

  it('confirms a pending ask after its send response is lost without sending twice', async () => {
    useConversationStore.getState().upsertMessage('session-1', {
      id: 'ask:ask-lost-response',
      messageId: 'ask:ask-lost-response',
      role: 'assistant',
      kind: 'assistant',
      messageKind: 'ask_request',
      content: 'Which branch should I use?',
      timestamp: Date.now(),
      payload: {
        ask_request_id: 'ask-lost-response',
        session_id: 'session-1',
        status: 'pending',
        question: 'Which branch should I use?',
        options: ['main'],
        allow_free_text: true,
      },
    });
    vi.mocked(messagesApi.sendMessage).mockRejectedValueOnce(new Error('response lost'));
    vi.mocked(messagesApi.getHistory).mockResolvedValue({
      user_id: 'local_user',
      session_id: 'session-1',
      messages: [],
      count: 0,
    } as any);
    vi.mocked(getAskState).mockResolvedValue({
      request_id: 'ask-lost-response',
      question: 'Which branch should I use?',
      options: ['main'],
      allow_free_text: true,
      status: 'answered',
      answer: 'main',
      created_at_ms: Date.now(),
      timeout_seconds: null,
      expires_at_ms: null,
    } as any);

    render(<ChatPage />);
    await userEvent.click(await screen.findByTestId('ask-composer-option-main'));
    await userEvent.click(screen.getByRole('button', { name: 'chat.send' }));

    await waitFor(() => {
      expect(screen.queryByTestId('ask-composer-quick-replies')).not.toBeInTheDocument();
      expect(screen.getByText('ask.answered')).toBeInTheDocument();
    });
    expect(messagesApi.sendMessage).toHaveBeenCalledTimes(1);
    expect(messagesApi.sendMessage).toHaveBeenCalledWith(expect.objectContaining({
      client_turn_id: expect.stringMatching(/^turn_/),
    }));
    expect(
      useConversationStore.getState().messagesBySession['session-1']
        ?.some((message) => (
          message.messageKind === 'ask_response'
          && message.content === 'main'
        )),
    ).toBe(true);
  });

  it('does not resend an ask when its confirmation endpoints are unavailable', async () => {
    useConversationStore.getState().upsertMessage('session-1', {
      id: 'ask:ask-confirmation-offline',
      messageId: 'ask:ask-confirmation-offline',
      role: 'assistant',
      kind: 'assistant',
      messageKind: 'ask_request',
      content: 'Which branch should I use?',
      timestamp: Date.now(),
      payload: {
        ask_request_id: 'ask-confirmation-offline',
        session_id: 'session-1',
        status: 'pending',
        question: 'Which branch should I use?',
        options: ['main'],
        allow_free_text: true,
      },
    });
    vi.mocked(messagesApi.sendMessage).mockRejectedValueOnce(new Error('response lost'));
    vi.mocked(messagesApi.getHistory).mockRejectedValue(new Error('offline'));
    vi.mocked(getAskState).mockRejectedValue(new Error('offline'));

    render(<ChatPage />);
    await userEvent.click(await screen.findByTestId('ask-composer-option-main'));
    await userEvent.click(screen.getByRole('button', { name: 'chat.send' }));

    await waitFor(() => {
      expect(toastWarningMock).toHaveBeenCalledWith('chat.sendUnconfirmed');
      expect(screen.getByRole('textbox')).toHaveValue('main');
    });
    expect(messagesApi.sendMessage).toHaveBeenCalledTimes(1);
  });

  it('does not submit an edited ask answer after the previous answer is accepted', async () => {
    useConversationStore.getState().upsertMessage('session-1', {
      id: 'ask:ask-edited-after-unknown',
      messageId: 'ask:ask-edited-after-unknown',
      role: 'assistant',
      kind: 'assistant',
      messageKind: 'ask_request',
      content: 'Which branch should I use?',
      timestamp: Date.now(),
      payload: {
        ask_request_id: 'ask-edited-after-unknown',
        session_id: 'session-1',
        status: 'pending',
        question: 'Which branch should I use?',
        options: ['main'],
        allow_free_text: true,
      },
    });
    vi.mocked(messagesApi.getHistory).mockResolvedValue({
      user_id: 'local_user',
      session_id: 'session-1',
      messages: [],
      count: 0,
    } as any);
    vi.mocked(getAskState).mockResolvedValue({
      request_id: 'ask-edited-after-unknown',
      question: 'Which branch should I use?',
      options: ['main'],
      allow_free_text: true,
      status: 'pending',
      answer: null,
      created_at_ms: Date.now(),
      timeout_seconds: null,
      expires_at_ms: null,
    } as any);
    vi.mocked(messagesApi.sendMessage)
      .mockRejectedValueOnce(new Error('offline'))
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({
        success: true,
        message: 'ok',
        data: {
          user_id: 'local_user',
          session_id: 'session-1',
          handled_as: 'ask_response',
          ask_request_id: 'ask-edited-after-unknown',
          message_length: 4,
          timestamp: Date.now() / 1000,
        },
      });

    render(<ChatPage />);
    await userEvent.click(
      await screen.findByTestId('ask-composer-option-main'),
    );
    await userEvent.click(screen.getByRole('button', { name: 'chat.send' }));
    await waitFor(() => {
      expect(toastWarningMock).toHaveBeenCalledWith('chat.sendUnconfirmed');
    });

    const composer = screen.getByRole('textbox');
    await userEvent.clear(composer);
    await userEvent.type(composer, 'develop');
    await userEvent.click(screen.getByRole('button', { name: 'chat.send' }));

    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(3);
      expect(screen.getByText('ask.answered')).toBeInTheDocument();
    });
    const requests = vi.mocked(messagesApi.sendMessage).mock.calls
      .map(([request]) => request);
    expect(requests.every((request) => request.message === 'main')).toBe(true);
    expect(new Set(
      requests.map((request) => request.client_turn_id),
    )).toHaveLength(1);
    expect(screen.getByRole('textbox')).toHaveValue('develop');
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
});
