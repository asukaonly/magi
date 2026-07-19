import {
  defineChatPageSuite,
  toastErrorMock,
  toastWarningMock,
  buildConfigWithVision,
  historyWithMessages,
  emptyHistory,
  seedRetryableOperations,
} from '@/test/chatPageHarness';
import {
  act,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { ChatPage } from '@/pages/Chat';
import { useConversationStore } from '@/stores/conversation-store';
import { normalizeHistoryMessages } from '@/domain/chat/state';
import { commandsApi, messagesApi } from '@/api';
import { configApi } from '@/api/modules/config';
import { personasApi } from '@/api/modules/personas';
import {
  CHAT_RETRYABLE_SEND_STORAGE_KEY,
  INLINE_SKILL_RETRY_STORAGE_KEY,
} from '@/hooks/chatRetryableSendStorage';

defineChatPageSuite('ChatPage inline skills and clearing', () => {
  it('keeps an empty session stable while its history initializes', async () => {
    render(<ChatPage />);

    expect(
      await screen.findByPlaceholderText('chat.inputPlaceholder'),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(messagesApi.getHistory).toHaveBeenCalledTimes(1);
    });
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

  it('confirms that clearing a chat also removes related memories', async () => {
    const user = userEvent.setup();
    vi.mocked(messagesApi.clearHistory).mockResolvedValueOnce({
      success: true,
      message: 'ok',
      user_id: 'local_user',
      session_id: 'session-1',
      cleared_message_ids: ['message-before-clear', 'reply-before-clear'],
      cleared_turn_ids: ['turn-before-clear'],
      cleanup_pending: true,
    });
    seedRetryableOperations();
    useConversationStore.getState().receiveHistory(
      'session-1',
      normalizeHistoryMessages([
        {
          message_id: 'message-before-clear',
          message_kind: 'user_text',
          role: 'user',
          content: 'Remember this old message',
          timestamp: 1000,
          turn_id: 'turn-before-clear',
          kind: 'user',
        },
        {
          message_id: 'reply-before-clear',
          message_kind: 'assistant_final',
          role: 'assistant',
          content: 'Reply target before clear',
          timestamp: 1100,
          turn_id: 'turn-before-clear',
          kind: 'assistant',
        },
      ]),
      4,
    );

    render(<ChatPage />);

    const composer = screen.getByPlaceholderText('chat.inputPlaceholder');
    const replyActions = screen.getAllByRole('button', {
      name: 'chat.reply.action',
    });
    await user.click(replyActions[replyActions.length - 1]);
    expect(screen.getByTestId('chat-composer-reply-preview')).toHaveTextContent(
      'Reply target before clear',
    );
    await user.type(composer, '/cl');
    const clearCommand = await screen.findByRole('option', { name: /\/clear/ });
    await user.click(clearCommand);

    const dialog = await screen.findByRole('dialog', { name: 'chat.clearHistoryDialog.title' });
    expect(within(dialog).getByText('chat.clearHistoryDialog.description')).toBeInTheDocument();
    expect(within(dialog).getByText('chat.clearHistoryDialog.warning')).toBeInTheDocument();
    expect(messagesApi.clearHistory).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole('button', { name: 'chat.clearHistoryDialog.confirm' }));

    await waitFor(() => {
      expect(messagesApi.clearHistory).toHaveBeenCalledWith('local_user', 'session-1');
      expect(screen.queryByRole('dialog', { name: 'chat.clearHistoryDialog.title' })).not.toBeInTheDocument();
    });
    const state = useConversationStore.getState();
    expect(state.currentSessionId).toBe('session-1');
    expect(state.messagesBySession['session-1']).toEqual([]);
    expect(window.sessionStorage.getItem(
      CHAT_RETRYABLE_SEND_STORAGE_KEY,
    )).toBeNull();
    expect(window.sessionStorage.getItem(
      INLINE_SKILL_RETRY_STORAGE_KEY,
    )).toBeNull();
    expect(screen.queryByTestId('chat-composer-reply-preview')).not.toBeInTheDocument();
    expect(toastWarningMock).toHaveBeenCalledWith(
      'chat.clearHistoryDialog.cleanupPending',
    );

    await user.type(composer, 'Message after clear');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));
    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledWith(
        expect.objectContaining({ message: 'Message after clear' }),
      );
    });
  });

  it('waits for an active send before clearing the chat', async () => {
    const user = userEvent.setup();
    const config = buildConfigWithVision(true) as any;
    config.data.preferences = {
      ...(config.data.preferences || {}),
      allow_interjection: true,
    };
    vi.mocked(configApi.get).mockResolvedValue(config);
    let resolveSend!: (
      value: Awaited<ReturnType<typeof messagesApi.sendMessage>>,
    ) => void;
    let resolveClear!: (
      value: Awaited<ReturnType<typeof messagesApi.clearHistory>>,
    ) => void;
    vi.mocked(messagesApi.sendMessage).mockReturnValueOnce(
      new Promise((resolve) => {
        resolveSend = resolve;
      }),
    );
    vi.mocked(messagesApi.clearHistory).mockReturnValueOnce(
      new Promise((resolve) => {
        resolveClear = resolve;
      }),
    );

    render(<ChatPage />);
    await waitFor(() => expect(configApi.get).toHaveBeenCalled());

    const composer = screen.getByPlaceholderText('chat.inputPlaceholder');
    await user.type(composer, 'Message already sending');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));
    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(1);
    });

    await user.clear(composer);
    await user.type(composer, '/cl');
    await user.click(await screen.findByRole('option', { name: /\/clear/ }));
    const dialog = await screen.findByRole('dialog', {
      name: 'chat.clearHistoryDialog.title',
    });
    await user.click(within(dialog).getByRole('button', {
      name: 'chat.clearHistoryDialog.confirm',
    }));

    await act(async () => {
      await Promise.resolve();
    });
    expect(messagesApi.clearHistory).not.toHaveBeenCalled();

    act(() => {
      resolveSend({
        success: true,
        message: 'ok',
        data: {
          user_id: 'local_user',
          session_id: 'session-1',
          message_length: 23,
          timestamp: Date.now() / 1000,
        },
      });
    });
    await waitFor(() => {
      expect(messagesApi.clearHistory).toHaveBeenCalledTimes(1);
    });
    expect(messagesApi.sendMessage).toHaveBeenCalledTimes(1);

    act(() => {
      resolveClear({
        success: true,
        message: 'ok',
        user_id: 'local_user',
        session_id: 'session-1',
        cleared_message_ids: [],
        cleared_turn_ids: [],
        cleanup_pending: false,
      });
    });
    await waitFor(() => {
      expect(screen.queryByRole('dialog', {
        name: 'chat.clearHistoryDialog.title',
      })).not.toBeInTheDocument();
    });
  });

  it('keeps chat clearing retryable when completion is not confirmed', async () => {
    const user = userEvent.setup();
    seedRetryableOperations();
    vi.mocked(messagesApi.clearHistory)
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValue({
        success: true,
        message: 'ok',
        user_id: 'local_user',
        session_id: 'session-1',
        cleared_message_ids: [],
        cleared_turn_ids: [],
        cleanup_pending: false,
      });
    useConversationStore.getState().receiveHistory(
      'session-1',
      normalizeHistoryMessages([{
        message_id: 'message-before-retry',
        message_kind: 'user_text',
        role: 'user',
        content: 'Keep this until clearing finishes',
        timestamp: 1000,
        turn_id: 'turn-before-retry',
        kind: 'user',
      }]),
      5,
    );

    render(<ChatPage />);

    await user.type(screen.getByPlaceholderText('chat.inputPlaceholder'), '/cl');
    await user.click(await screen.findByRole('option', { name: /\/clear/ }));
    const dialog = await screen.findByRole('dialog', { name: 'chat.clearHistoryDialog.title' });
    await user.click(within(dialog).getByRole('button', { name: 'chat.clearHistoryDialog.confirm' }));

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('chat.clearHistoryDialog.error');
    expect(messagesApi.clearHistory).toHaveBeenCalledTimes(1);
    expect(useConversationStore.getState().messagesBySession['session-1']).toHaveLength(1);
    expect(window.sessionStorage.getItem(
      CHAT_RETRYABLE_SEND_STORAGE_KEY,
    )).not.toBeNull();
    expect(window.sessionStorage.getItem(
      INLINE_SKILL_RETRY_STORAGE_KEY,
    )).not.toBeNull();

    await user.click(within(dialog).getByRole('button', { name: 'chat.clearHistoryDialog.retry' }));

    await waitFor(() => {
      expect(messagesApi.clearHistory).toHaveBeenCalledTimes(2);
      expect(screen.queryByRole('dialog', { name: 'chat.clearHistoryDialog.title' })).not.toBeInTheDocument();
    });
    expect(useConversationStore.getState().messagesBySession['session-1']).toEqual([]);
    expect(window.sessionStorage.getItem(
      CHAT_RETRYABLE_SEND_STORAGE_KEY,
    )).toBeNull();
    expect(window.sessionStorage.getItem(
      INLINE_SKILL_RETRY_STORAGE_KEY,
    )).toBeNull();
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

  it('retries an inline skill send with one stable turn id', async () => {
    const user = userEvent.setup();
    vi.mocked(commandsApi.listSkills).mockResolvedValue([{
      name: 'reliable-skill',
      description: 'Reliable inline skill',
      argument_hint: null,
      tags: [],
      context_mode: 'inline',
    }]);
    vi.mocked(commandsApi.expandSkill).mockResolvedValue({
      name: 'reliable-skill',
      description: 'Reliable inline skill',
      invocation_text: '/reliable-skill',
      rendered_prompt: 'Expanded prompt',
      context_mode: 'inline',
    } as any);
    vi.mocked(messagesApi.getHistory).mockResolvedValue(emptyHistory());
    vi.mocked(messagesApi.sendMessage)
      .mockRejectedValueOnce(new Error('response lost'))
      .mockResolvedValueOnce({
        success: true,
        message: 'ok',
        data: {
          user_id: 'local_user',
          session_id: 'session-1',
          message_length: 0,
          timestamp: Date.now() / 1000,
        },
      });

    render(<ChatPage />);
    await user.type(screen.getByPlaceholderText('chat.inputPlaceholder'), '/reliable-skill');
    await user.click(await screen.findByRole('option', { name: /\/reliable-skill/ }));

    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(2);
    });
    const requests = vi.mocked(messagesApi.sendMessage).mock.calls.map(([request]) => request);
    expect(requests[0]?.client_turn_id).toMatch(/^turn_/);
    expect(requests[1]?.client_turn_id).toBe(requests[0]?.client_turn_id);
    expect(requests[0]?.message).toBe('/reliable-skill\n\nExpanded prompt');
  });

  it('recovers an inline skill retry across a page remount', async () => {
    const user = userEvent.setup();
    vi.mocked(commandsApi.listSkills).mockResolvedValue([{
      name: 'refresh-skill',
      description: 'Refresh-safe inline skill',
      argument_hint: null,
      tags: [],
      context_mode: 'inline',
    }]);
    vi.mocked(commandsApi.expandSkill)
      .mockResolvedValueOnce({
        name: 'refresh-skill',
        description: 'Refresh-safe inline skill',
        invocation_text: '/refresh-skill',
        rendered_prompt: 'Original expanded prompt',
        context_mode: 'inline',
      } as any)
      .mockResolvedValueOnce({
        name: 'refresh-skill',
        description: 'Refresh-safe inline skill',
        invocation_text: '/refresh-skill',
        rendered_prompt: 'Changed expanded prompt',
        context_mode: 'inline',
      } as any);
    vi.mocked(messagesApi.getHistory).mockResolvedValue({
      user_id: 'local_user',
      session_id: 'session-1',
      messages: [],
      count: 0,
    } as any);
    vi.mocked(messagesApi.sendMessage)
      .mockRejectedValueOnce(new Error('offline'))
      .mockRejectedValueOnce(new Error('offline'));

    const firstPage = render(<ChatPage />);
    await user.type(
      screen.getByPlaceholderText('chat.inputPlaceholder'),
      '/refresh-skill',
    );
    await user.click(
      await screen.findByRole('option', { name: /\/refresh-skill/ }),
    );
    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(2);
      expect(window.sessionStorage.getItem(
        INLINE_SKILL_RETRY_STORAGE_KEY,
      )).not.toBeNull();
    });
    const originalRequest = vi.mocked(messagesApi.sendMessage).mock.calls[0]?.[0];

    firstPage.unmount();
    vi.mocked(messagesApi.sendMessage).mockReset().mockResolvedValue({
      success: true,
      message: 'ok',
      data: {
        user_id: 'local_user',
        session_id: 'session-1',
        message_length: 0,
        timestamp: Date.now() / 1000,
      },
    });

    render(<ChatPage />);
    await user.type(
      screen.getByPlaceholderText('chat.inputPlaceholder'),
      '/refresh-skill',
    );
    await user.click(
      await screen.findByRole('option', { name: /\/refresh-skill/ }),
    );

    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(1);
      expect(window.sessionStorage.getItem(
        INLINE_SKILL_RETRY_STORAGE_KEY,
      )).toBeNull();
    });
    const recoveredRequest = vi.mocked(messagesApi.sendMessage).mock.calls[0]?.[0];
    expect(recoveredRequest?.client_turn_id).toBe(
      originalRequest?.client_turn_id,
    );
    expect(recoveredRequest?.message).toBe(
      '/refresh-skill\n\nOriginal expanded prompt',
    );
    expect(commandsApi.expandSkill).toHaveBeenCalledTimes(1);
  });

  it('shows an accepted inline skill turn and locks ordinary sends until it finishes', async () => {
    const user = userEvent.setup();
    const config = buildConfigWithVision(true) as any;
    config.data.preferences = {
      ...(config.data.preferences || {}),
      allow_interjection: false,
    };
    vi.mocked(configApi.get).mockResolvedValue(config);
    vi.mocked(commandsApi.listSkills).mockResolvedValue([{
      name: 'blocking-skill',
      description: 'Blocking inline skill',
      argument_hint: null,
      tags: [],
      context_mode: 'inline',
    }]);
    vi.mocked(commandsApi.expandSkill).mockResolvedValue({
      name: 'blocking-skill',
      description: 'Blocking inline skill',
      invocation_text: '/blocking-skill',
      rendered_prompt: 'Expanded blocking prompt',
      context_mode: 'inline',
    } as any);

    render(<ChatPage />);
    await waitFor(() => expect(configApi.get).toHaveBeenCalled());
    await user.type(
      screen.getByPlaceholderText('chat.inputPlaceholder'),
      '/blocking-skill',
    );
    await user.click(
      await screen.findByRole('option', { name: /\/blocking-skill/ }),
    );

    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(1);
      expect(screen.getByRole('button', { name: 'chat.stop' })).toBeInTheDocument();
    });
    const request = vi.mocked(messagesApi.sendMessage).mock.calls[0]?.[0];
    const turnId = String(request?.client_turn_id || '');
    const visibleTurn = (
      useConversationStore.getState().messagesBySession['session-1'] || []
    ).find((message) => (
      message.role === 'user'
      && message.turnId === turnId
    ));
    expect(visibleTurn?.content).toBe(
      '/blocking-skill\n\nExpanded blocking prompt',
    );
    expect(screen.getByPlaceholderText('chat.waitingForReply')).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'chat.send' })).not.toBeInTheDocument();
  });

  it('uses the latest session for no-argument inline skills', async () => {
    const user = userEvent.setup();
    const config = buildConfigWithVision(true) as any;
    config.data.preferences = {
      ...(config.data.preferences || {}),
      allow_interjection: true,
    };
    vi.mocked(configApi.get).mockResolvedValue(config);
    vi.mocked(commandsApi.listSkills).mockResolvedValue([{
      name: 'live-session-skill',
      description: 'Uses the active session',
      argument_hint: null,
      tags: [],
      context_mode: 'inline',
    }]);
    vi.mocked(commandsApi.expandSkill).mockImplementation(async (request) => ({
      name: 'live-session-skill',
      description: 'Uses the active session',
      invocation_text: '/live-session-skill',
      rendered_prompt: `Expanded for ${request.session_id}`,
      context_mode: 'inline',
    } as any));
    useConversationStore.getState().setCurrentSessionId(null);

    render(<ChatPage />);
    act(() => {
      useConversationStore.getState().setCurrentSessionId('session-loaded');
    });

    await user.type(
      await screen.findByPlaceholderText('chat.inputPlaceholder'),
      '/live-session-skill',
    );
    await user.click(
      await screen.findByRole('option', { name: /\/live-session-skill/ }),
    );
    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(1);
      expect(messagesApi.sendMessage).toHaveBeenLastCalledWith(
        expect.objectContaining({ session_id: 'session-loaded' }),
      );
    });

    act(() => {
      useConversationStore.getState().setCurrentSessionId('session-next');
    });
    await user.type(
      await screen.findByPlaceholderText('chat.inputPlaceholder'),
      '/live-session-skill',
    );
    await user.click(
      await screen.findByRole('option', { name: /\/live-session-skill/ }),
    );

    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(2);
      expect(messagesApi.sendMessage).toHaveBeenLastCalledWith(
        expect.objectContaining({ session_id: 'session-next' }),
      );
    });
  });

  it('does not let an ordinary message bypass an unconfirmed inline skill', async () => {
    const user = userEvent.setup();
    vi.mocked(commandsApi.listSkills).mockResolvedValue([{
      name: 'uncertain-skill',
      description: 'Uncertain inline skill',
      argument_hint: null,
      tags: [],
      context_mode: 'inline',
    }]);
    vi.mocked(commandsApi.expandSkill).mockResolvedValue({
      name: 'uncertain-skill',
      description: 'Uncertain inline skill',
      invocation_text: '/uncertain-skill',
      rendered_prompt: 'Uncertain expanded prompt',
      context_mode: 'inline',
    } as any);
    vi.mocked(messagesApi.getHistory).mockResolvedValue({
      user_id: 'local_user',
      session_id: 'session-1',
      messages: [],
      count: 0,
    } as any);
    vi.mocked(messagesApi.sendMessage).mockRejectedValue(
      new Error('response lost'),
    );

    render(<ChatPage />);
    await user.type(
      screen.getByPlaceholderText('chat.inputPlaceholder'),
      '/uncertain-skill',
    );
    await user.click(
      await screen.findByRole('option', { name: /\/uncertain-skill/ }),
    );
    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(2);
    });
    expect(toastWarningMock).toHaveBeenCalledWith(
      'chat.skills.sendUnconfirmed',
    );
    expect(toastErrorMock).not.toHaveBeenCalled();

    await user.type(
      screen.getByPlaceholderText('chat.inputPlaceholder'),
      'Do not send this yet',
    );
    await user.click(screen.getByRole('button', { name: 'chat.send' }));

    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(4);
      expect(toastWarningMock).toHaveBeenCalledWith(
        'chat.previousSendUnconfirmed',
      );
    });
    expect(vi.mocked(messagesApi.sendMessage).mock.calls.every(
      ([request]) => request.message
        === '/uncertain-skill\n\nUncertain expanded prompt',
    )).toBe(true);
    expect(screen.getByRole('textbox')).toHaveValue('Do not send this yet');
  });

  it('restores the inline turn lock when the old skill is accepted but still running', async () => {
    const user = userEvent.setup();
    const config = buildConfigWithVision(true) as any;
    config.data.preferences = {
      ...(config.data.preferences || {}),
      allow_interjection: false,
    };
    vi.mocked(configApi.get).mockResolvedValue(config);
    vi.mocked(commandsApi.listSkills).mockResolvedValue([{
      name: 'running-skill',
      description: 'Running inline skill',
      argument_hint: null,
      tags: [],
      context_mode: 'inline',
    }]);
    vi.mocked(commandsApi.expandSkill).mockResolvedValue({
      name: 'running-skill',
      description: 'Running inline skill',
      invocation_text: '/running-skill',
      rendered_prompt: 'Running expanded prompt',
      context_mode: 'inline',
    } as any);
    let oldTurnIsVisible = false;
    vi.mocked(messagesApi.getHistory).mockImplementation(async () => {
      const turnId = vi.mocked(messagesApi.sendMessage).mock.calls[0]?.[0]
        ?.client_turn_id;
      return {
        user_id: 'local_user',
        session_id: 'session-1',
        messages: oldTurnIsVisible && turnId ? [{
          message_id: 'running-inline-user',
          message_kind: 'user_text',
          role: 'user',
          kind: 'user',
          content: '/running-skill\n\nRunning expanded prompt',
          timestamp: Date.now() / 1000,
          turn_id: turnId,
          run_state: { state: 'running' },
        }] : [],
        count: oldTurnIsVisible && turnId ? 1 : 0,
      } as any;
    });
    vi.mocked(messagesApi.sendMessage).mockRejectedValue(
      new Error('response lost'),
    );

    render(<ChatPage />);
    await waitFor(() => expect(configApi.get).toHaveBeenCalled());
    await user.type(
      screen.getByPlaceholderText('chat.inputPlaceholder'),
      '/running-skill',
    );
    await user.click(
      await screen.findByRole('option', { name: /\/running-skill/ }),
    );
    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(2);
    });

    oldTurnIsVisible = true;
    await user.type(
      screen.getByPlaceholderText('chat.inputPlaceholder'),
      'Wait behind the running skill',
    );
    await user.click(screen.getByRole('button', { name: 'chat.send' }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'chat.stop' })).toBeInTheDocument();
    });
    expect(messagesApi.sendMessage).toHaveBeenCalledTimes(2);
    expect(screen.getByRole('textbox')).toHaveValue(
      'Wait behind the running skill',
    );
  });

  it('lets an ask answer resume an unconfirmed inline skill that is still running', async () => {
    const user = userEvent.setup();
    const config = buildConfigWithVision(true) as any;
    config.data.preferences = {
      ...(config.data.preferences || {}),
      allow_interjection: false,
    };
    vi.mocked(configApi.get).mockResolvedValue(config);
    vi.mocked(commandsApi.listSkills).mockResolvedValue([{
      name: 'asking-skill',
      description: 'Asking inline skill',
      argument_hint: null,
      tags: [],
      context_mode: 'inline',
    }]);
    vi.mocked(commandsApi.expandSkill).mockResolvedValue({
      name: 'asking-skill',
      description: 'Asking inline skill',
      invocation_text: '/asking-skill',
      rendered_prompt: 'Ask the user before continuing',
      context_mode: 'inline',
    } as any);
    let oldTurnIsVisible = false;
    vi.mocked(messagesApi.getHistory).mockImplementation(async () => {
      const turnId = vi.mocked(messagesApi.sendMessage).mock.calls[0]?.[0]
        ?.client_turn_id;
      return historyWithMessages(
        oldTurnIsVisible && turnId
          ? [{
            message_id: 'asking-inline-user',
            message_kind: 'user_text',
            role: 'user',
            kind: 'user',
            content: '/asking-skill\n\nAsk the user before continuing',
            timestamp: Date.now() / 1000,
            turn_id: turnId,
            run_state: { state: 'running' },
          }]
          : [],
      );
    });
    vi.mocked(messagesApi.sendMessage).mockRejectedValue(
      new Error('response lost'),
    );

    render(<ChatPage />);
    await user.type(
      screen.getByPlaceholderText('chat.inputPlaceholder'),
      '/asking-skill',
    );
    await user.click(
      await screen.findByRole('option', { name: /\/asking-skill/ }),
    );
    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(2);
    });

    const previousTurnId = String(
      vi.mocked(messagesApi.sendMessage).mock.calls[0]?.[0]
        ?.client_turn_id || '',
    );
    oldTurnIsVisible = true;
    vi.mocked(messagesApi.sendMessage).mockResolvedValue({
      success: true,
      message: 'ok',
      data: {
        user_id: 'local_user',
        session_id: 'session-1',
        handled_as: 'ask_response',
        ask_request_id: 'ask-from-inline-skill',
        message_length: 3,
        timestamp: Date.now() / 1000,
      },
    });
    act(() => {
      useConversationStore.getState().upsertMessage('session-1', {
        id: 'ask:ask-from-inline-skill',
        messageId: 'ask:ask-from-inline-skill',
        role: 'assistant',
        kind: 'assistant',
        messageKind: 'ask_request',
        content: 'Continue the inline skill?',
        timestamp: Date.now(),
        turnId: previousTurnId,
        payload: {
          ask_request_id: 'ask-from-inline-skill',
          session_id: 'session-1',
          status: 'pending',
          question: 'Continue the inline skill?',
          allow_free_text: true,
        },
      });
    });

    await user.type(
      screen.getByPlaceholderText('chat.inputPlaceholder'),
      'Yes',
    );
    await user.click(screen.getByRole('button', { name: 'chat.send' }));

    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(3);
    });
    expect(messagesApi.sendMessage).toHaveBeenLastCalledWith(
      expect.objectContaining({
        message: 'Yes',
        metadata: {
          ask_request_id: 'ask-from-inline-skill',
        },
      }),
    );
    expect(window.sessionStorage.getItem(
      INLINE_SKILL_RETRY_STORAGE_KEY,
    )).toBeNull();
  });

  it('continues an ordinary send after a same-page inline retry is terminal', async () => {
    const user = userEvent.setup();
    vi.mocked(commandsApi.listSkills).mockResolvedValue([{
      name: 'terminal-skill',
      description: 'Terminal inline skill',
      argument_hint: null,
      tags: [],
      context_mode: 'inline',
    }]);
    vi.mocked(commandsApi.expandSkill).mockResolvedValue({
      name: 'terminal-skill',
      description: 'Terminal inline skill',
      invocation_text: '/terminal-skill',
      rendered_prompt: 'Terminal expanded prompt',
      context_mode: 'inline',
    } as any);
    let oldTurnIsTerminal = false;
    vi.mocked(messagesApi.getHistory).mockImplementation(async () => {
      const turnId = vi.mocked(messagesApi.sendMessage).mock.calls[0]?.[0]
        ?.client_turn_id;
      return {
        user_id: 'local_user',
        session_id: 'session-1',
        messages: oldTurnIsTerminal && turnId ? [{
          message_id: 'terminal-inline-user',
          message_kind: 'user_text',
          role: 'user',
          kind: 'user',
          content: '/terminal-skill\n\nTerminal expanded prompt',
          timestamp: Date.now() / 1000,
          turn_id: turnId,
          run_state: { state: 'completed' },
        }] : [],
        count: oldTurnIsTerminal && turnId ? 1 : 0,
      } as any;
    });
    vi.mocked(messagesApi.sendMessage)
      .mockRejectedValueOnce(new Error('response lost'))
      .mockRejectedValueOnce(new Error('response lost'))
      .mockResolvedValueOnce({
        success: true,
        message: 'ok',
        data: {
          user_id: 'local_user',
          session_id: 'session-1',
          message_length: 0,
          timestamp: Date.now() / 1000,
        },
      });

    render(<ChatPage />);
    await user.type(
      screen.getByPlaceholderText('chat.inputPlaceholder'),
      '/terminal-skill',
    );
    await user.click(
      await screen.findByRole('option', { name: /\/terminal-skill/ }),
    );
    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(2);
    });

    oldTurnIsTerminal = true;
    await user.type(
      screen.getByPlaceholderText('chat.inputPlaceholder'),
      'Send after terminal',
    );
    await user.click(screen.getByRole('button', { name: 'chat.send' }));

    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(3);
      expect(messagesApi.sendMessage).toHaveBeenLastCalledWith(
        expect.objectContaining({ message: 'Send after terminal' }),
      );
    });
  });

  it('does not let a different inline skill bypass an older unknown skill', async () => {
    const user = userEvent.setup();
    vi.mocked(commandsApi.listSkills).mockResolvedValue([
      {
        name: 'first-unknown-skill',
        description: 'First unknown skill',
        argument_hint: null,
        tags: [],
        context_mode: 'inline',
      },
      {
        name: 'second-new-skill',
        description: 'Second new skill',
        argument_hint: null,
        tags: [],
        context_mode: 'inline',
      },
    ]);
    vi.mocked(commandsApi.expandSkill).mockImplementation(async (request) => ({
      name: request.skill_name,
      description: request.skill_name,
      invocation_text: `/${request.skill_name}`,
      rendered_prompt: `Expanded ${request.skill_name}`,
      context_mode: 'inline',
    } as any));
    vi.mocked(messagesApi.getHistory).mockResolvedValue({
      user_id: 'local_user',
      session_id: 'session-1',
      messages: [],
      count: 0,
    } as any);
    vi.mocked(messagesApi.sendMessage).mockRejectedValue(
      new Error('response lost'),
    );

    render(<ChatPage />);
    await user.type(
      screen.getByPlaceholderText('chat.inputPlaceholder'),
      '/first-unknown-skill',
    );
    await user.click(
      await screen.findByRole('option', { name: /\/first-unknown-skill/ }),
    );
    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(2);
    });

    await user.type(
      screen.getByPlaceholderText('chat.inputPlaceholder'),
      '/second-new-skill',
    );
    await user.click(
      await screen.findByRole('option', { name: /\/second-new-skill/ }),
    );

    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(4);
      expect(toastWarningMock).toHaveBeenCalledWith(
        'chat.previousSendUnconfirmed',
      );
    });
    expect(commandsApi.expandSkill).toHaveBeenCalledTimes(1);
    expect(vi.mocked(messagesApi.sendMessage).mock.calls.every(
      ([request]) => request.message
        === '/first-unknown-skill\n\nExpanded first-unknown-skill',
    )).toBe(true);
  });

  it('does not let an inline skill bypass an unconfirmed composer turn', async () => {
    const user = userEvent.setup();
    vi.mocked(commandsApi.listSkills).mockResolvedValue([{
      name: 'blocked-by-composer',
      description: 'Blocked by composer retry',
      argument_hint: null,
      tags: [],
      context_mode: 'inline',
    }]);
    vi.mocked(commandsApi.expandSkill).mockResolvedValue({
      name: 'blocked-by-composer',
      description: 'Blocked by composer retry',
      invocation_text: '/blocked-by-composer',
      rendered_prompt: 'Should not expand yet',
      context_mode: 'inline',
    } as any);
    vi.mocked(messagesApi.getHistory).mockResolvedValue({
      user_id: 'local_user',
      session_id: 'session-1',
      messages: [],
      count: 0,
    } as any);
    vi.mocked(messagesApi.sendMessage).mockRejectedValue(
      new Error('response lost'),
    );

    render(<ChatPage />);
    await user.type(
      screen.getByPlaceholderText('chat.inputPlaceholder'),
      'Unknown composer turn',
    );
    await user.click(screen.getByRole('button', { name: 'chat.send' }));
    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(2);
    });

    await user.clear(screen.getByRole('textbox'));
    await user.type(
      screen.getByPlaceholderText('chat.inputPlaceholder'),
      '/blocked-by-composer',
    );
    await user.click(
      await screen.findByRole('option', { name: /\/blocked-by-composer/ }),
    );

    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(4);
      expect(toastWarningMock).toHaveBeenCalledWith(
        'chat.previousSendUnconfirmed',
      );
    });
    expect(commandsApi.expandSkill).not.toHaveBeenCalled();
    expect(vi.mocked(messagesApi.sendMessage).mock.calls.every(
      ([request]) => request.message === 'Unknown composer turn',
    )).toBe(true);
  });

  it('continues an ordinary send after an old inline request is explicitly rejected', async () => {
    const user = userEvent.setup();
    vi.mocked(commandsApi.listSkills).mockResolvedValue([{
      name: 'rejected-old-skill',
      description: 'Rejected old inline skill',
      argument_hint: null,
      tags: [],
      context_mode: 'inline',
    }]);
    vi.mocked(commandsApi.expandSkill).mockResolvedValue({
      name: 'rejected-old-skill',
      description: 'Rejected old inline skill',
      invocation_text: '/rejected-old-skill',
      rendered_prompt: 'Rejected old prompt',
      context_mode: 'inline',
    } as any);
    vi.mocked(messagesApi.getHistory).mockResolvedValue({
      user_id: 'local_user',
      session_id: 'session-1',
      messages: [],
      count: 0,
    } as any);
    vi.mocked(messagesApi.sendMessage).mockRejectedValue(
      new Error('response lost'),
    );

    render(<ChatPage />);
    await user.type(
      screen.getByPlaceholderText('chat.inputPlaceholder'),
      '/rejected-old-skill',
    );
    await user.click(
      await screen.findByRole('option', { name: /\/rejected-old-skill/ }),
    );
    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(2);
    });

    vi.mocked(messagesApi.sendMessage)
      .mockReset()
      .mockResolvedValueOnce({
        success: false,
        message: 'rejected',
        data: {
          user_id: 'local_user',
          session_id: 'session-1',
          message_length: 0,
          timestamp: Date.now() / 1000,
        },
      })
      .mockResolvedValueOnce({
        success: true,
        message: 'ok',
        data: {
          user_id: 'local_user',
          session_id: 'session-1',
          message_length: 0,
          timestamp: Date.now() / 1000,
        },
      });
    await user.type(
      screen.getByPlaceholderText('chat.inputPlaceholder'),
      'Send after rejection',
    );
    await user.click(screen.getByRole('button', { name: 'chat.send' }));

    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(2);
    });
    expect(vi.mocked(messagesApi.sendMessage).mock.calls[0]?.[0].message)
      .toBe('/rejected-old-skill\n\nRejected old prompt');
    expect(vi.mocked(messagesApi.sendMessage).mock.calls[1]?.[0].message)
      .toBe('Send after rejection');
  });

  it('uses the first post-refresh click only to settle an old inline turn', async () => {
    const user = userEvent.setup();
    const config = buildConfigWithVision(true) as any;
    config.data.preferences = {
      ...(config.data.preferences || {}),
      allow_interjection: false,
    };
    vi.mocked(configApi.get).mockResolvedValue(config);
    vi.mocked(commandsApi.listSkills).mockResolvedValue([{
      name: 'restored-old-skill',
      description: 'Restored old inline skill',
      argument_hint: null,
      tags: [],
      context_mode: 'inline',
    }]);
    vi.mocked(commandsApi.expandSkill).mockResolvedValue({
      name: 'restored-old-skill',
      description: 'Restored old inline skill',
      invocation_text: '/restored-old-skill',
      rendered_prompt: 'Restored old prompt',
      context_mode: 'inline',
    } as any);
    vi.mocked(messagesApi.getHistory).mockResolvedValue({
      user_id: 'local_user',
      session_id: 'session-1',
      messages: [],
      count: 0,
    } as any);
    vi.mocked(messagesApi.sendMessage).mockRejectedValue(
      new Error('response lost'),
    );

    const firstPage = render(<ChatPage />);
    await waitFor(() => expect(configApi.get).toHaveBeenCalled());
    await user.type(
      screen.getByPlaceholderText('chat.inputPlaceholder'),
      '/restored-old-skill',
    );
    await user.click(
      await screen.findByRole('option', { name: /\/restored-old-skill/ }),
    );
    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(2);
    });
    const oldTurnId = vi.mocked(messagesApi.sendMessage).mock.calls[0]?.[0]
      .client_turn_id;

    firstPage.unmount();
    vi.mocked(messagesApi.sendMessage).mockReset().mockResolvedValue({
      success: true,
      message: 'ok',
      data: {
        user_id: 'local_user',
        session_id: 'session-1',
        message_length: 0,
        timestamp: Date.now() / 1000,
      },
    });
    vi.mocked(messagesApi.getHistory).mockResolvedValue({
      user_id: 'local_user',
      session_id: 'session-1',
      messages: [{
        message_id: 'restored-terminal-inline',
        message_kind: 'user_text',
        role: 'user',
        kind: 'user',
        content: '/restored-old-skill\n\nRestored old prompt',
        timestamp: Date.now() / 1000,
        turn_id: oldTurnId,
        run_state: { state: 'completed' },
      }],
      count: 1,
    } as any);

    render(<ChatPage />);
    await user.type(
      await screen.findByPlaceholderText('chat.inputPlaceholder'),
      'Keep this restored draft',
    );
    await user.click(screen.getByRole('button', { name: 'chat.send' }));

    await waitFor(() => {
      expect(toastWarningMock).toHaveBeenCalledWith(
        'chat.restoredSendResolved',
      );
    });
    expect(messagesApi.sendMessage).not.toHaveBeenCalled();
    expect(screen.getByRole('textbox')).toHaveValue(
      'Keep this restored draft',
    );

    await user.click(screen.getByRole('button', { name: 'chat.send' }));
    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(1);
      expect(messagesApi.sendMessage).toHaveBeenLastCalledWith(
        expect.objectContaining({ message: 'Keep this restored draft' }),
      );
    });
  });

  it('does not relock the composer when a retried inline skill is already terminal', async () => {
    const user = userEvent.setup();
    const config = buildConfigWithVision(true) as any;
    config.data.preferences = {
      ...(config.data.preferences || {}),
      allow_interjection: false,
    };
    vi.mocked(configApi.get).mockResolvedValue(config);
    vi.mocked(commandsApi.listSkills).mockResolvedValue([{
      name: 'completed-retry-skill',
      description: 'Completed inline retry',
      argument_hint: null,
      tags: [],
      context_mode: 'inline',
    }]);
    vi.mocked(commandsApi.expandSkill).mockResolvedValue({
      name: 'completed-retry-skill',
      description: 'Completed inline retry',
      invocation_text: '/completed-retry-skill',
      rendered_prompt: 'Completed retry prompt',
      context_mode: 'inline',
    } as any);
    let oldTurnIsTerminal = false;
    vi.mocked(messagesApi.getHistory).mockImplementation(async () => {
      const turnId = vi.mocked(messagesApi.sendMessage).mock.calls[0]?.[0]
        .client_turn_id;
      return {
        user_id: 'local_user',
        session_id: 'session-1',
        messages: oldTurnIsTerminal && turnId ? [{
          message_id: 'completed-retry-inline',
          message_kind: 'user_text',
          role: 'user',
          kind: 'user',
          content: '/completed-retry-skill\n\nCompleted retry prompt',
          timestamp: Date.now() / 1000,
          turn_id: turnId,
          run_state: { state: 'completed' },
        }] : [],
        count: oldTurnIsTerminal && turnId ? 1 : 0,
      } as any;
    });
    vi.mocked(messagesApi.sendMessage).mockRejectedValue(
      new Error('response lost'),
    );

    render(<ChatPage />);
    await waitFor(() => expect(configApi.get).toHaveBeenCalled());
    await user.type(
      screen.getByPlaceholderText('chat.inputPlaceholder'),
      '/completed-retry-skill',
    );
    await user.click(
      await screen.findByRole('option', { name: /\/completed-retry-skill/ }),
    );
    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(2);
    });

    oldTurnIsTerminal = true;
    await user.type(
      screen.getByPlaceholderText('chat.inputPlaceholder'),
      '/completed-retry-skill',
    );
    await user.click(
      await screen.findByRole('option', { name: /\/completed-retry-skill/ }),
    );

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'chat.send' })).toBeInTheDocument();
    });
    expect(screen.queryByRole('button', { name: 'chat.stop' }))
      .not.toBeInTheDocument();
    expect(messagesApi.sendMessage).toHaveBeenCalledTimes(2);
  });
});
