import {
  defineChatPageSuite,
  realtimeListener,
  toastWarningMock,
  buildConfigWithVision,
  historyWithMessages,
  emptyHistory,
} from '@/test/chatPageHarness';
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { ChatPage } from '@/pages/Chat';
import { useConversationStore } from '@/stores/conversation-store';
import { commandsApi, messagesApi } from '@/api';
import { configApi } from '@/api/modules/config';
import {
  CHAT_RETRYABLE_SEND_STORAGE_KEY,
  INLINE_SKILL_RETRY_STORAGE_KEY,
} from '@/hooks/chatRetryableSendStorage';

defineChatPageSuite('ChatPage turn admission', () => {
  it('admits only one ordinary turn while the first request is in flight', async () => {
    const user = userEvent.setup();
    let resolveSend: ((
      value: Awaited<ReturnType<typeof messagesApi.sendMessage>>,
    ) => void) | null = null;
    vi.mocked(messagesApi.sendMessage).mockReturnValue(
      new Promise((resolve) => {
        resolveSend = resolve;
      }),
    );

    render(<ChatPage />);
    await user.type(
      screen.getByPlaceholderText('chat.inputPlaceholder'),
      'One in-flight turn',
    );
    const sendButton = screen.getByRole('button', { name: 'chat.send' });
    act(() => {
      sendButton.click();
      sendButton.click();
    });

    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(1);
    });
    expect(window.sessionStorage.getItem(
      CHAT_RETRYABLE_SEND_STORAGE_KEY,
    )).not.toBeNull();

    await act(async () => {
      resolveSend?.({
        success: true,
        message: 'ok',
        data: {
          user_id: 'local_user',
          session_id: 'session-1',
          message_length: 0,
          timestamp: Date.now() / 1000,
        },
      });
    });
    await waitFor(() => {
      expect(window.sessionStorage.getItem(
        CHAT_RETRYABLE_SEND_STORAGE_KEY,
      )).toBeNull();
    });
  });

  it('admits only one inline skill turn while the first request is in flight', async () => {
    const user = userEvent.setup();
    vi.mocked(commandsApi.listSkills).mockResolvedValue([{
      name: 'single-flight-skill',
      description: 'Single-flight inline skill',
      argument_hint: null,
      tags: [],
      context_mode: 'inline',
    }]);
    vi.mocked(commandsApi.expandSkill).mockResolvedValue({
      name: 'single-flight-skill',
      description: 'Single-flight inline skill',
      invocation_text: '/single-flight-skill',
      rendered_prompt: 'Single-flight prompt',
      context_mode: 'inline',
    } as any);
    let resolveSend: ((
      value: Awaited<ReturnType<typeof messagesApi.sendMessage>>,
    ) => void) | null = null;
    vi.mocked(messagesApi.sendMessage).mockReturnValue(
      new Promise((resolve) => {
        resolveSend = resolve;
      }),
    );

    render(<ChatPage />);
    await user.type(
      screen.getByPlaceholderText('chat.inputPlaceholder'),
      '/single-flight-skill',
    );
    const option = await screen.findByRole(
      'option',
      { name: /\/single-flight-skill/ },
    );
    act(() => {
      fireEvent.mouseDown(option);
      fireEvent.mouseDown(option);
    });

    await waitFor(() => {
      expect(commandsApi.expandSkill).toHaveBeenCalledTimes(1);
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(1);
    });
    expect(window.sessionStorage.getItem(
      INLINE_SKILL_RETRY_STORAGE_KEY,
    )).not.toBeNull();

    await act(async () => {
      resolveSend?.({
        success: true,
        message: 'ok',
        data: {
          user_id: 'local_user',
          session_id: 'session-1',
          message_length: 0,
          timestamp: Date.now() / 1000,
        },
      });
    });
    await waitFor(() => {
      expect(window.sessionStorage.getItem(
        INLINE_SKILL_RETRY_STORAGE_KEY,
      )).toBeNull();
    });
  });

  it('keeps a realtime message that arrives while initial history is loading', async () => {
    let resolveHistory: ((
      value: Awaited<ReturnType<typeof messagesApi.getHistory>>,
    ) => void) | null = null;
    vi.mocked(messagesApi.getHistory).mockReturnValue(
      new Promise((resolve) => {
        resolveHistory = resolve;
      }),
    );

    render(<ChatPage />);
    await waitFor(() => {
      expect(messagesApi.getHistory).toHaveBeenCalled();
      expect(realtimeListener).not.toBeNull();
    });
    act(() => {
      realtimeListener?.({
        event: 'agent_response',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-during-history',
          message_id: 'message-during-history',
          message_kind: 'assistant_final',
          content: 'Arrived while history was loading',
          timestamp: Date.now() / 1000,
        },
      });
    });
    expect(await screen.findByText(
      'Arrived while history was loading',
    )).toBeInTheDocument();

    await act(async () => {
      resolveHistory?.(emptyHistory());
    });

    await waitFor(() => {
      expect(screen.getAllByText(
        'Arrived while history was loading',
      )).toHaveLength(1);
    });
  });

  it('does not let Enter submit a second turn while the session is still running', async () => {
    const user = userEvent.setup();
    vi.mocked(configApi.get).mockReturnValue(new Promise(() => {}));

    render(<ChatPage />);
    await waitFor(() => expect(configApi.get).toHaveBeenCalled());
    const composer = screen.getByPlaceholderText('chat.inputPlaceholder');
    await user.type(composer, 'Must remain unsent');
    act(() => {
      useConversationStore.getState().upsertMessage('session-1', {
        id: 'existing-running-user',
        messageId: 'existing-running-user',
        role: 'user',
        kind: 'user',
        messageKind: 'user_text',
        content: 'Existing running turn',
        timestamp: Date.now(),
        turnId: 'turn-existing-running',
        runState: { state: 'running' },
      });
    });
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'chat.stop' }))
        .toBeInTheDocument();
      expect(composer).toBeDisabled();
    });

    await act(async () => {
      fireEvent.keyDown(composer, { key: 'Enter', code: 'Enter' });
      await Promise.resolve();
    });

    expect(messagesApi.sendMessage).not.toHaveBeenCalled();
    expect(composer).toHaveValue('Must remain unsent');
  });

  it('allows the first turn in an empty session while interjection settings load', async () => {
    const user = userEvent.setup();
    vi.mocked(configApi.get).mockReturnValue(new Promise(() => {}));

    render(<ChatPage />);
    await waitFor(() => expect(configApi.get).toHaveBeenCalled());
    const composer = screen.getByPlaceholderText('chat.inputPlaceholder');
    await user.type(composer, 'First turn needs no interjection setting');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));

    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(1);
    });
  });

  it('waits for initial history and blocks Enter when it reveals a running turn', async () => {
    const user = userEvent.setup();
    let resolveHistory: ((value: any) => void) | null = null;
    vi.mocked(messagesApi.getHistory).mockReturnValue(new Promise((resolve) => {
      resolveHistory = resolve;
    }) as ReturnType<typeof messagesApi.getHistory>);

    render(<ChatPage />);
    const composer = screen.getByPlaceholderText('chat.inputPlaceholder');
    await user.type(composer, 'Do not race the initial history');
    await act(async () => {
      fireEvent.keyDown(composer, { key: 'Enter', code: 'Enter' });
      await Promise.resolve();
    });
    expect(messagesApi.sendMessage).not.toHaveBeenCalled();

    await act(async () => {
      resolveHistory?.({
        user_id: 'local_user',
        session_id: 'session-1',
        history_version: 1,
        messages: [{
          message_id: 'history-running-user',
          message_kind: 'user_text',
          role: 'user',
          kind: 'user',
          content: 'Already running on the backend',
          timestamp: Date.now() / 1000,
          turn_id: 'turn-history-running',
          run_state: { state: 'running' },
        }],
        count: 1,
      });
    });

    await waitFor(() => {
      expect(toastWarningMock).toHaveBeenCalledWith(
        'chat.waitForCurrentReply',
      );
      expect(screen.getByRole('button', { name: 'chat.stop' }))
        .toBeInTheDocument();
    });
    expect(messagesApi.sendMessage).not.toHaveBeenCalled();
    expect(composer).toHaveValue('Do not race the initial history');
  });

  it('waits for initial history before expanding an inline skill', async () => {
    const user = userEvent.setup();
    let resolveHistory: ((value: any) => void) | null = null;
    vi.mocked(messagesApi.getHistory).mockReturnValue(new Promise((resolve) => {
      resolveHistory = resolve;
    }) as ReturnType<typeof messagesApi.getHistory>);
    vi.mocked(commandsApi.listSkills).mockResolvedValue([{
      name: 'history-gated-skill',
      description: 'History-gated skill',
      argument_hint: '<topic>',
      tags: [],
      context_mode: 'inline',
    }]);

    render(<ChatPage />);
    const composer = screen.getByPlaceholderText('chat.inputPlaceholder');
    await user.type(composer, '/history-gated-skill');
    await user.click(
      await screen.findByRole(
        'option',
        { name: /\/history-gated-skill/ },
      ),
    );
    const dialog = await screen.findByRole('dialog');
    await user.type(
      within(dialog).getByPlaceholderText('<topic>'),
      'topic',
    );
    await user.click(
      within(dialog).getByRole('button', { name: 'chat.skills.send' }),
    );
    expect(commandsApi.expandSkill).not.toHaveBeenCalled();

    await act(async () => {
      resolveHistory?.({
        user_id: 'local_user',
        session_id: 'session-1',
        history_version: 1,
        messages: [{
          message_id: 'history-running-before-skill',
          message_kind: 'user_text',
          role: 'user',
          kind: 'user',
          content: 'Backend turn still running',
          timestamp: Date.now() / 1000,
          turn_id: 'turn-running-before-skill',
          run_state: { state: 'running' },
        }],
        count: 1,
      });
    });

    await waitFor(() => {
      expect(within(dialog).getByText('chat.waitForCurrentReply'))
        .toBeInTheDocument();
    });
    expect(commandsApi.expandSkill).not.toHaveBeenCalled();
    expect(messagesApi.sendMessage).not.toHaveBeenCalled();
  });

  it('keeps an ask answer available while initial history is still loading', async () => {
    const user = userEvent.setup();
    vi.mocked(messagesApi.getHistory).mockReturnValue(new Promise(() => {}));
    useConversationStore.getState().upsertMessage('session-1', {
      id: 'ask-before-history-ready',
      messageId: 'ask-before-history-ready',
      role: 'assistant',
      kind: 'assistant',
      messageKind: 'ask_request',
      content: 'Answer without waiting for history',
      timestamp: Date.now(),
      turnId: 'turn-ask-before-history',
      payload: {
        ask_request_id: 'ask-request-before-history',
        session_id: 'session-1',
        status: 'pending',
        question: 'Answer without waiting for history',
        allow_free_text: true,
      },
    });

    render(<ChatPage />);
    const composer = screen.getByPlaceholderText('chat.inputPlaceholder');
    await user.type(composer, 'Ask control answer');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));

    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledWith(
        expect.objectContaining({
          message: 'Ask control answer',
          metadata: {
            ask_request_id: 'ask-request-before-history',
          },
        }),
      );
    });
  });

  it('lets an ask answer resume a previously unconfirmed running turn', async () => {
    const user = userEvent.setup();
    const config = buildConfigWithVision(true) as any;
    config.data.preferences = {
      ...(config.data.preferences || {}),
      allow_interjection: false,
    };
    let confirmPreviousTurn = false;
    vi.mocked(configApi.get).mockResolvedValue(config);
    vi.mocked(messagesApi.getHistory).mockImplementation(async () => {
      const previousTurnId = vi.mocked(messagesApi.sendMessage)
        .mock.calls[0]?.[0]?.client_turn_id;
      return historyWithMessages(
        confirmPreviousTurn && previousTurnId
          ? [{
            message_id: 'previous-running-turn',
            message_kind: 'user_text',
            role: 'user',
            kind: 'user',
            content: 'Start a task that asks a question',
            timestamp: Date.now() / 1000,
            turn_id: previousTurnId,
            run_state: { state: 'running' },
          }]
          : [],
      );
    });
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
          ask_request_id: 'ask-after-unconfirmed-turn',
          message_length: 3,
          timestamp: Date.now() / 1000,
        },
      });

    render(<ChatPage />);
    const composer = screen.getByPlaceholderText('chat.inputPlaceholder');
    await user.type(composer, 'Start a task that asks a question');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));
    await waitFor(() => {
      expect(toastWarningMock).toHaveBeenCalledWith('chat.sendUnconfirmed');
    });

    confirmPreviousTurn = true;
    act(() => {
      useConversationStore.getState().upsertMessage('session-1', {
        id: 'ask:ask-after-unconfirmed-turn',
        messageId: 'ask:ask-after-unconfirmed-turn',
        role: 'assistant',
        kind: 'assistant',
        messageKind: 'ask_request',
        content: 'Continue this task?',
        timestamp: Date.now(),
        turnId: String(
          vi.mocked(messagesApi.sendMessage)
            .mock.calls[0]?.[0]?.client_turn_id || '',
        ),
        payload: {
          ask_request_id: 'ask-after-unconfirmed-turn',
          session_id: 'session-1',
          status: 'pending',
          question: 'Continue this task?',
          allow_free_text: true,
        },
      });
    });

    await user.clear(composer);
    await user.type(composer, 'Yes');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));

    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(3);
    });
    expect(messagesApi.sendMessage).toHaveBeenLastCalledWith(
      expect.objectContaining({
        message: 'Yes',
        metadata: {
          ask_request_id: 'ask-after-unconfirmed-turn',
        },
      }),
    );
    expect(window.sessionStorage.getItem(
      CHAT_RETRYABLE_SEND_STORAGE_KEY,
    )).toBeNull();
  });

  it('keeps the draft when initial history cannot be verified', async () => {
    const user = userEvent.setup();
    vi.mocked(messagesApi.getHistory).mockRejectedValue(
      new Error('history unavailable'),
    );

    render(<ChatPage />);
    const composer = screen.getByPlaceholderText('chat.inputPlaceholder');
    await user.type(composer, 'Keep this until history recovers');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));

    await waitFor(() => {
      expect(toastWarningMock).toHaveBeenCalledWith(
        'chat.historyNotReady',
      );
    });
    expect(messagesApi.sendMessage).not.toHaveBeenCalled();
    expect(composer).toHaveValue('Keep this until history recovers');
  });

  it('blocks an inline skill until an explicit interjection setting allows it', async () => {
    const user = userEvent.setup();
    const config = buildConfigWithVision(true) as any;
    config.data.preferences = {
      ...(config.data.preferences || {}),
      allow_interjection: true,
    };
    let resolveConfig: ((value: typeof config) => void) | null = null;
    vi.mocked(configApi.get).mockReturnValue(new Promise((resolve) => {
      resolveConfig = resolve;
    }));
    vi.mocked(commandsApi.listSkills).mockResolvedValue([{
      name: 'blocked-while-running',
      description: 'Blocked while running',
      argument_hint: '<topic>',
      tags: [],
      context_mode: 'inline',
    }]);
    vi.mocked(commandsApi.expandSkill).mockResolvedValue({
      name: 'blocked-while-running',
      description: 'Blocked while running',
      invocation_text: '/blocked-while-running',
      rendered_prompt: 'This must not be submitted yet',
      context_mode: 'inline',
    } as any);

    render(<ChatPage />);
    await waitFor(() => expect(configApi.get).toHaveBeenCalled());
    const composer = screen.getByPlaceholderText('chat.inputPlaceholder');
    await user.type(composer, '/blocked-while-running');
    await user.click(
      await screen.findByRole(
        'option',
        { name: /\/blocked-while-running/ },
      ),
    );
    const dialog = await screen.findByRole('dialog');
    await user.type(
      within(dialog).getByPlaceholderText('<topic>'),
      'topic',
    );

    act(() => {
      useConversationStore.getState().upsertMessage('session-1', {
        id: 'running-before-inline',
        messageId: 'running-before-inline',
        role: 'user',
        kind: 'user',
        messageKind: 'user_text',
        content: 'Existing running turn',
        timestamp: Date.now(),
        turnId: 'turn-running-before-inline',
        runState: { state: 'running' },
      });
    });
    await waitFor(() => {
      expect(screen.getByRole(
        'button',
        { name: 'chat.stop', hidden: true },
      ))
        .toBeInTheDocument();
    });

    await user.click(
      within(dialog).getByRole('button', { name: 'chat.skills.send' }),
    );
    await waitFor(() => {
      expect(within(dialog).getByText('chat.waitForCurrentReply'))
        .toBeInTheDocument();
    });

    expect(commandsApi.expandSkill).not.toHaveBeenCalled();
    expect(messagesApi.sendMessage).not.toHaveBeenCalled();

    await act(async () => {
      resolveConfig?.(config);
    });
    await waitFor(() => {
      expect(screen.getByRole(
        'button',
        { name: 'chat.send', hidden: true },
      )).toBeInTheDocument();
    });
    await user.click(
      within(dialog).getByRole('button', { name: 'chat.skills.send' }),
    );
    await waitFor(() => {
      expect(commandsApi.expandSkill).toHaveBeenCalledTimes(1);
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(1);
    });
  });

  it('keeps pending-turn admission isolated by session', async () => {
    const user = userEvent.setup();
    const config = buildConfigWithVision(true) as any;
    config.data.preferences = {
      ...(config.data.preferences || {}),
      allow_interjection: false,
    };
    vi.mocked(configApi.get).mockResolvedValue(config);
    vi.mocked(messagesApi.sendMessage).mockImplementation(async (request) => ({
      success: true,
      message: 'ok',
      data: {
        user_id: 'local_user',
        session_id: request.session_id,
        message_length: request.message.length,
        timestamp: Date.now() / 1000,
      },
    }));
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
    await waitFor(() => expect(configApi.get).toHaveBeenCalled());
    const composer = screen.getByPlaceholderText('chat.inputPlaceholder');
    await user.type(composer, 'Session one keeps running');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));
    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(1);
      expect(screen.getByRole('button', { name: 'chat.stop' }))
        .toBeInTheDocument();
    });

    act(() => {
      useConversationStore.getState().setCurrentSessionId('session-2');
    });
    await user.type(composer, 'Session two can send');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));

    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(2);
    });
    expect(vi.mocked(messagesApi.sendMessage).mock.calls[1]?.[0])
      .toEqual(expect.objectContaining({
        session_id: 'session-2',
        message: 'Session two can send',
      }));
  });

  it('keeps sending state and draft clearing isolated by session', async () => {
    const user = userEvent.setup();
    let resolveSessionOne: ((value: any) => void) | null = null;
    vi.mocked(messagesApi.sendMessage).mockImplementation((request) => {
      if (request.session_id === 'session-1') {
        return new Promise((resolve) => {
          resolveSessionOne = resolve;
        });
      }
      return Promise.resolve({
        success: true,
        message: 'ok',
        data: {
          user_id: 'local_user',
          session_id: request.session_id,
          message_length: request.message.length,
          timestamp: Date.now() / 1000,
        },
      });
    });
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
    const composer = screen.getByPlaceholderText('chat.inputPlaceholder');
    await user.type(composer, 'Session one in flight');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));
    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(1);
    });

    act(() => {
      useConversationStore.getState().setCurrentSessionId('session-2');
    });
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'chat.send' }))
        .toBeEnabled();
    });
    await user.clear(composer);
    await user.type(composer, 'Session two draft');

    await act(async () => {
      resolveSessionOne?.({
        success: true,
        message: 'ok',
        data: {
          user_id: 'local_user',
          session_id: 'session-1',
          message_length: 21,
          timestamp: Date.now() / 1000,
        },
      });
    });
    expect(composer).toHaveValue('Session two draft');

    await user.click(screen.getByRole('button', { name: 'chat.send' }));
    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(2);
    });
    expect(vi.mocked(messagesApi.sendMessage).mock.calls[1]?.[0])
      .toEqual(expect.objectContaining({
        session_id: 'session-2',
        message: 'Session two draft',
      }));
  });

  it('still allows explicit interjection while another turn is running', async () => {
    const user = userEvent.setup();
    const config = buildConfigWithVision(true) as any;
    config.data.preferences = {
      ...(config.data.preferences || {}),
      allow_interjection: true,
    };
    vi.mocked(configApi.get).mockResolvedValue(config);

    render(<ChatPage />);
    await waitFor(() => expect(configApi.get).toHaveBeenCalled());
    const composer = screen.getByPlaceholderText('chat.inputPlaceholder');
    await user.type(composer, 'First interjectable turn');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));
    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(1);
      expect(composer).toHaveValue('');
    });

    await user.type(composer, 'Second interjection');
    await act(async () => {
      fireEvent.keyDown(composer, { key: 'Enter', code: 'Enter' });
    });

    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(2);
    });
  });

  it('allows an ask answer through the running-turn gate', async () => {
    const user = userEvent.setup();
    const config = buildConfigWithVision(true) as any;
    config.data.preferences = {
      ...(config.data.preferences || {}),
      allow_interjection: false,
    };
    vi.mocked(configApi.get).mockResolvedValue(config);

    render(<ChatPage />);
    await waitFor(() => expect(configApi.get).toHaveBeenCalled());
    const composer = screen.getByPlaceholderText('chat.inputPlaceholder');
    await user.type(composer, 'Turn that will ask');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));
    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(1);
      expect(screen.getByRole('button', { name: 'chat.stop' }))
        .toBeInTheDocument();
    });

    act(() => {
      useConversationStore.getState().upsertMessage('session-1', {
        id: 'ask-running-turn',
        messageId: 'ask-running-turn',
        role: 'assistant',
        kind: 'assistant',
        messageKind: 'ask_request',
        content: 'Please answer before I continue',
        timestamp: Date.now(),
        turnId: 'turn-running-ask',
        payload: {
          ask_request_id: 'ask-running-request',
          session_id: 'session-1',
          status: 'pending',
          question: 'Please answer before I continue',
          allow_free_text: true,
        },
      });
    });
    await user.type(composer, 'Continue with this answer');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));

    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(2);
    });
    expect(vi.mocked(messagesApi.sendMessage).mock.calls[1]?.[0])
      .toEqual(expect.objectContaining({
        session_id: 'session-1',
        message: 'Continue with this answer',
        metadata: {
          ask_request_id: 'ask-running-request',
        },
      }));
    expect(screen.getByRole('button', { name: 'chat.stop' }))
      .toBeInTheDocument();
  });
});
