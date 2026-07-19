import {
  defineChatPageSuite,
  realtimeListener,
  toastErrorMock,
  toastWarningMock,
  buildConfigWithVision,
  historyWithMessages,
  emptyHistory,
} from '@/test/chatPageHarness';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { ChatPage } from '@/pages/Chat';
import { useConversationStore } from '@/stores/conversation-store';
import { normalizeHistoryMessages } from '@/domain/chat/state';
import { messagesApi } from '@/api';
import { configApi } from '@/api/modules/config';
import {
  CHAT_RETRYABLE_SEND_STORAGE_KEY,
} from '@/hooks/chatRetryableSendStorage';
import { PENDING_HISTORY_RECONCILE_DELAY_MS } from '@/hooks/useChatRealtimeEffects';

defineChatPageSuite('ChatPage send recovery', () => {
  it('sends a one-turn recall correction while preserving the ordinary draft', async () => {
    const user = userEvent.setup();
    useConversationStore.getState().receiveHistory(
      'session-1',
      normalizeHistoryMessages([
        {
          message_id: 'user-memory-question',
          message_kind: 'user_text',
          role: 'user',
          content: 'What did I browse?',
          timestamp: 1000,
          turn_id: 'turn-memory',
          kind: 'user',
        },
        {
          message_id: 'assistant-memory-answer',
          message_kind: 'assistant_final',
          role: 'assistant',
          content: 'You browsed a game page.',
          timestamp: 1100,
          turn_id: 'turn-memory',
          kind: 'assistant',
          payload: {
            recalled_memories: [
              {
                kind: 'event',
                source_layer: 'L1',
                statement: 'Visited example.com',
                topic: 'example.com',
                feedback_ref: 'event:event-1',
              },
            ],
          },
        },
      ]),
    );

    render(<ChatPage />);

    const textarea = screen.getByPlaceholderText('chat.inputPlaceholder');
    await user.type(textarea, 'Keep this ordinary draft');
    await user.click(screen.getByRole('button', { name: 'chat.recalledMemories.summary' }));
    await user.click(screen.getByRole('button', { name: 'chat.recallFeedback.itemAction' }));

    expect(screen.getByTestId('recall-feedback-banner')).toBeInTheDocument();
    expect(screen.getByRole('textbox')).toHaveValue('chat.recallFeedback.templates.itemIrrelevant');

    await user.click(screen.getByRole('button', { name: 'chat.recallFeedback.send' }));

    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledWith(expect.objectContaining({
        message: 'chat.recallFeedback.templates.itemIrrelevant',
        reply_to_message_id: 'assistant-memory-answer',
        recall_feedback: {
          kind: 'item_irrelevant',
          target_message_id: 'assistant-memory-answer',
          finding_ref: 'event:event-1',
        },
      }));
    });
    expect(screen.queryByTestId('recall-feedback-banner')).not.toBeInTheDocument();
    expect(screen.getByRole('textbox')).toHaveValue('Keep this ordinary draft');

    const feedbackMessage = useConversationStore.getState().messagesBySession['session-1']
      ?.find((message) => message.payload?.recall_feedback);
    expect(feedbackMessage).toEqual(expect.objectContaining({
      content: 'chat.recallFeedback.templates.itemIrrelevant',
      replyTo: expect.objectContaining({ messageId: 'assistant-memory-answer' }),
      payload: {
        recall_feedback: {
          kind: 'item_irrelevant',
          target_message_id: 'assistant-memory-answer',
          finding_ref: 'event:event-1',
        },
      },
    }));
  });

  it('keeps a recall correction draft when another turn is still running', async () => {
    const user = userEvent.setup();
    useConversationStore.getState().receiveHistory(
      'session-1',
      normalizeHistoryMessages([
        {
          message_id: 'assistant-memory-before-running',
          message_kind: 'assistant_final',
          role: 'assistant',
          content: 'A recalled answer',
          timestamp: 1000,
          turn_id: 'turn-memory-before-running',
          kind: 'assistant',
          payload: {
            recalled_memories: [{
              kind: 'event',
              source_layer: 'L1',
              statement: 'An irrelevant event',
              topic: 'event',
              feedback_ref: 'event:running-block',
            }],
          },
        },
        {
          message_id: 'newer-running-turn',
          message_kind: 'user_text',
          role: 'user',
          content: 'A newer turn is running',
          timestamp: 1100,
          turn_id: 'turn-newer-running',
          kind: 'user',
          run_state: { state: 'running' },
        },
      ]),
    );

    render(<ChatPage />);
    await user.click(screen.getByRole(
      'button',
      { name: 'chat.recalledMemories.summary' },
    ));
    await user.click(screen.getByRole(
      'button',
      { name: 'chat.recallFeedback.itemAction' },
    ));
    await user.click(screen.getByRole(
      'button',
      { name: 'chat.recallFeedback.send' },
    ));

    await waitFor(() => {
      expect(toastWarningMock).toHaveBeenCalledWith(
        'chat.waitForCurrentReply',
      );
    });
    expect(messagesApi.sendMessage).not.toHaveBeenCalled();
    expect(screen.getByTestId('recall-feedback-banner'))
      .toBeInTheDocument();
    expect(screen.getByRole('textbox')).toHaveValue(
      'chat.recallFeedback.templates.itemIrrelevant',
    );
  });

  it('safely retries an interrupted recall correction with the same turn id', async () => {
    const user = userEvent.setup();
    vi.mocked(messagesApi.getHistory).mockResolvedValue(historyWithMessages([{
      message_id: 'assistant-memory-answer',
      message_kind: 'assistant_final',
      role: 'assistant',
      content: 'Previous answer',
      timestamp: 1100,
      turn_id: 'turn-memory',
      kind: 'assistant',
      payload: {
        recalled_memories: [{
          kind: 'event',
          source_layer: 'L1',
          statement: 'Visited example.com',
          topic: 'example.com',
          feedback_ref: 'event:event-1',
        }],
      },
    }]));
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
    useConversationStore.getState().receiveHistory(
      'session-1',
      normalizeHistoryMessages([
        {
          message_id: 'assistant-memory-answer',
          message_kind: 'assistant_final',
          role: 'assistant',
          content: 'Previous answer',
          timestamp: 1100,
          turn_id: 'turn-memory',
          kind: 'assistant',
          payload: {
            recalled_memories: [{
              kind: 'event',
              source_layer: 'L1',
              statement: 'Visited example.com',
              topic: 'example.com',
              feedback_ref: 'event:event-1',
            }],
          },
        },
      ]),
    );

    render(<ChatPage />);
    await user.click(screen.getByRole('button', { name: 'chat.recalledMemories.summary' }));
    await user.click(screen.getByRole('button', { name: 'chat.recallFeedback.itemAction' }));
    await user.click(screen.getByRole('button', { name: 'chat.recallFeedback.send' }));

    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(2);
      expect(screen.queryByTestId('recall-feedback-banner')).not.toBeInTheDocument();
    });
    const firstTurnId = vi.mocked(messagesApi.sendMessage).mock.calls[0]?.[0]?.client_turn_id;
    const secondTurnId = vi.mocked(messagesApi.sendMessage).mock.calls[1]?.[0]?.client_turn_id;
    expect(firstTurnId).toBeTruthy();
    expect(secondTurnId).toBe(firstTurnId);
    expect(
      useConversationStore.getState().messagesBySession['session-1']
        ?.filter((message) => message.turnId === firstTurnId && message.role === 'user'),
    ).toHaveLength(1);
  });

  it('removes an optimistic recall correction when the send is rejected', async () => {
    const user = userEvent.setup();
    const config = buildConfigWithVision(true) as any;
    config.data.preferences = {
      ...(config.data.preferences || {}),
      allow_interjection: false,
    };
    vi.mocked(configApi.get).mockResolvedValue(config);
    vi.mocked(messagesApi.sendMessage).mockResolvedValueOnce({
      success: false,
      message: 'blocked',
      data: { error_code: 'RECALL_FEEDBACK_PENDING_ASK' },
    } as any);
    vi.mocked(messagesApi.getHistory).mockResolvedValue(historyWithMessages([{
      message_id: 'assistant-memory-answer',
      message_kind: 'assistant_final',
      role: 'assistant',
      content: 'Previous answer',
      timestamp: 1100,
      turn_id: 'turn-memory',
      kind: 'assistant',
      payload: {
        recalled_memories: [{
          kind: 'event',
          source_layer: 'L1',
          statement: 'Visited example.com',
          topic: 'example.com',
          feedback_ref: 'event:event-1',
        }],
      },
    }]));
    useConversationStore.getState().receiveHistory(
      'session-1',
      normalizeHistoryMessages([
        {
          message_id: 'assistant-memory-answer',
          message_kind: 'assistant_final',
          role: 'assistant',
          content: 'Previous answer',
          timestamp: 1100,
          turn_id: 'turn-memory',
          kind: 'assistant',
          payload: {
            recalled_memories: [{
              kind: 'event',
              source_layer: 'L1',
              statement: 'Visited example.com',
              topic: 'example.com',
              feedback_ref: 'event:event-1',
            }],
          },
        },
      ]),
    );

    render(<ChatPage />);
    await user.click(screen.getByRole('button', { name: 'chat.recalledMemories.summary' }));
    await user.click(screen.getByRole('button', { name: 'chat.recallFeedback.itemAction' }));
    await user.click(screen.getByRole('button', { name: 'chat.recallFeedback.send' }));

    await waitFor(() => {
      const optimisticFeedback = useConversationStore.getState().messagesBySession['session-1']
        ?.find((message) => message.payload?.recall_feedback && !message.messageId);
      expect(optimisticFeedback).toBeUndefined();
    });
    expect(screen.getByTestId('recall-feedback-banner')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'chat.recallFeedback.convertToNormal' }));
    expect(screen.getByRole('button', { name: 'chat.send' })).toBeInTheDocument();
  });

  it('reports a send failure without calling it an upload failure', async () => {
    const user = userEvent.setup();
    const config = buildConfigWithVision(true) as any;
    config.data.preferences = {
      ...(config.data.preferences || {}),
      allow_interjection: false,
    };
    vi.mocked(configApi.get).mockResolvedValue(config);
    vi.mocked(messagesApi.sendMessage).mockResolvedValueOnce({
      success: false,
      message: 'blocked',
      data: null,
    } as any);
    vi.mocked(messagesApi.getHistory).mockResolvedValue({
      user_id: 'local_user',
      session_id: 'session-1',
      messages: [],
      count: 0,
    } as any);

    render(<ChatPage />);
    await waitFor(() => expect(configApi.get).toHaveBeenCalled());

    await user.type(screen.getByPlaceholderText('chat.inputPlaceholder'), 'Please send this');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));

    await waitFor(() => {
      expect(toastErrorMock).toHaveBeenCalledWith('blocked');
      expect(screen.getByRole('button', { name: 'chat.send' })).toBeInTheDocument();
    });
    expect(
      useConversationStore.getState().messagesBySession['session-1'] || [],
    ).toEqual([]);
    expect(screen.getByPlaceholderText('chat.inputPlaceholder')).toHaveValue(
      'Please send this',
    );
  });

  it('checks history before retrying a send whose response was lost', async () => {
    const user = userEvent.setup();
    vi.mocked(messagesApi.sendMessage).mockRejectedValueOnce(new Error('response lost'));
    vi.mocked(messagesApi.getHistory).mockImplementation(async () => {
      const request = vi.mocked(messagesApi.sendMessage).mock.calls[0]?.[0];
      const turnId = request?.client_turn_id;
      if (!turnId) {
        return {
          user_id: 'local_user',
          session_id: 'session-1',
          messages: [],
          count: 0,
        };
      }
      return {
        user_id: 'local_user',
        session_id: 'session-1',
        history_version: 9,
        count: 1,
        messages: [{
          message_id: 'persisted-after-response-loss',
          message_kind: 'user_text',
          role: 'user',
          kind: 'user',
          content: 'Already received',
          timestamp: Date.now() / 1000,
          turn_id: turnId,
          run_state: { state: 'running' },
        }],
      } as any;
    });

    render(<ChatPage />);
    await user.type(screen.getByPlaceholderText('chat.inputPlaceholder'), 'Already received');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));

    await waitFor(() => {
      expect(screen.getByRole('textbox')).toHaveValue('');
      const turnId = vi.mocked(messagesApi.sendMessage).mock.calls[0]?.[0]?.client_turn_id;
      expect(turnId).toBeTruthy();
      expect(
        useConversationStore.getState().messagesBySession['session-1']
          ?.some((message) => (
            message.role === 'user'
            && message.turnId === turnId
            && message.content === 'Already received'
          )),
      ).toBe(true);
    });
    expect(messagesApi.sendMessage).toHaveBeenCalledTimes(1);
  });

  it('keeps a turn when a later delivery stage reports failure after persistence', async () => {
    const user = userEvent.setup();
    vi.mocked(messagesApi.sendMessage).mockImplementationOnce(async (request) => ({
      success: false,
      message: 'queue checkpoint failed',
      data: {
        user_id: 'local_user',
        session_id: 'session-1',
        turn_id: request.client_turn_id,
        message_id: 'persisted-before-stage-failure',
        message_length: request.message.length,
        timestamp: Date.now() / 1000,
      },
    } as any));
    vi.mocked(messagesApi.getHistory).mockImplementation(async () => {
      const request = vi.mocked(messagesApi.sendMessage).mock.calls[0]?.[0];
      const turnId = request?.client_turn_id;
      return {
        user_id: 'local_user',
        session_id: 'session-1',
        history_version: 10,
        count: turnId ? 1 : 0,
        messages: turnId ? [{
          message_id: 'persisted-before-stage-failure',
          message_kind: 'user_text',
          role: 'user',
          kind: 'user',
          content: 'Keep the persisted turn',
          timestamp: Date.now() / 1000,
          turn_id: turnId,
          run_state: { state: 'queued' },
        }] : [],
      } as any;
    });

    render(<ChatPage />);
    await user.type(screen.getByPlaceholderText('chat.inputPlaceholder'), 'Keep the persisted turn');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));

    await waitFor(() => {
      expect(screen.getByRole('textbox')).toHaveValue('');
      expect(
        useConversationStore.getState().messagesBySession['session-1']
          ?.some((message) => message.content === 'Keep the persisted turn'),
      ).toBe(true);
    });
    expect(messagesApi.sendMessage).toHaveBeenCalledTimes(1);
    expect(toastErrorMock).not.toHaveBeenCalledWith('queue checkpoint failed');
  });

  it('keeps an unconfirmed draft and reuses its turn id on manual retry', async () => {
    const user = userEvent.setup();
    const config = buildConfigWithVision(true) as any;
    config.data.preferences = {
      ...(config.data.preferences || {}),
      allow_interjection: false,
    };
    vi.mocked(configApi.get).mockResolvedValue(config);
    vi.mocked(messagesApi.getHistory).mockResolvedValue(emptyHistory());
    vi.mocked(messagesApi.sendMessage)
      .mockRejectedValueOnce(new Error('offline'))
      .mockRejectedValueOnce(new Error('offline'))
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
    await waitFor(() => expect(configApi.get).toHaveBeenCalled());
    await user.type(screen.getByPlaceholderText('chat.inputPlaceholder'), 'Keep this safe');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));

    await waitFor(() => {
      expect(toastWarningMock).toHaveBeenCalledWith('chat.sendUnconfirmed');
      expect(screen.getByRole('button', { name: 'chat.send' })).toBeInTheDocument();
    });
    expect(screen.getByPlaceholderText('chat.inputPlaceholder')).toHaveValue('Keep this safe');
    expect(window.sessionStorage.getItem(
      CHAT_RETRYABLE_SEND_STORAGE_KEY,
    )).not.toBeNull();
    expect(
      useConversationStore.getState().messagesBySession['session-1'] || [],
    ).toEqual([]);

    await user.click(screen.getByRole('button', { name: 'chat.send' }));

    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(3);
      expect(screen.getByRole('textbox')).toHaveValue('');
    });
    const turnIds = vi.mocked(messagesApi.sendMessage).mock.calls
      .map(([request]) => request.client_turn_id);
    expect(new Set(turnIds).size).toBe(1);
    expect(turnIds[0]).toBeTruthy();
    expect(
      useConversationStore.getState().messagesBySession['session-1']
        ?.filter((message) => message.turnId === turnIds[0] && message.role === 'user'),
    ).toHaveLength(1);
    expect(window.sessionStorage.getItem(
      CHAT_RETRYABLE_SEND_STORAGE_KEY,
    )).toBeNull();
  });

  it('sends edited visible text instead of retrying a hidden draft', async () => {
    const user = userEvent.setup();
    let resolveConvergence: ((value: any) => void) | null = null;
    const config = buildConfigWithVision(true) as any;
    config.data.preferences = {
      ...(config.data.preferences || {}),
      allow_interjection: true,
    };
    vi.mocked(configApi.get).mockResolvedValue(config);
    vi.mocked(messagesApi.getHistory).mockResolvedValue(emptyHistory());
    vi.mocked(messagesApi.sendMessage)
      .mockRejectedValueOnce(new Error('offline'))
      .mockRejectedValueOnce(new Error('offline'))
      .mockReturnValueOnce(new Promise((resolve) => {
        resolveConvergence = resolve;
      }) as ReturnType<typeof messagesApi.sendMessage>)
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
    const composer = screen.getByPlaceholderText('chat.inputPlaceholder');
    await user.type(composer, 'Old hidden text');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));

    await waitFor(() => {
      expect(toastWarningMock).toHaveBeenCalledWith('chat.sendUnconfirmed');
    });
    await user.clear(composer);
    await user.type(composer, 'New visible text');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));

    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(3);
    });
    const requestsBeforeResolution = vi.mocked(messagesApi.sendMessage).mock.calls
      .map(([request]) => request);
    expect(requestsBeforeResolution[2]?.message).toBe('Old hidden text');
    expect(requestsBeforeResolution[2]?.client_turn_id).toBe(
      requestsBeforeResolution[0]?.client_turn_id,
    );
    expect(screen.getByRole('textbox')).toHaveValue('New visible text');

    await act(async () => {
      resolveConvergence?.({
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
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(4);
      expect(screen.getByRole('textbox')).toHaveValue('');
    });
    const requests = vi.mocked(messagesApi.sendMessage).mock.calls.map(([request]) => request);
    expect(requests[0]?.message).toBe('Old hidden text');
    expect(requests[1]?.message).toBe('Old hidden text');
    expect(requests[1]?.client_turn_id).toBe(requests[0]?.client_turn_id);
    expect(requests[2]?.message).toBe('Old hidden text');
    expect(requests[2]?.client_turn_id).toBe(requests[0]?.client_turn_id);
    expect(requests[3]?.message).toBe('New visible text');
    expect(requests[3]?.client_turn_id).not.toBe(requests[0]?.client_turn_id);
  });

  it('restores the old turn lock before a changed draft can upload', async () => {
    const user = userEvent.setup();
    const config = buildConfigWithVision(true) as any;
    config.data.preferences = {
      ...(config.data.preferences || {}),
      allow_interjection: false,
    };
    vi.mocked(configApi.get).mockResolvedValue(config);
    vi.mocked(messagesApi.getHistory).mockResolvedValue({
      user_id: 'local_user',
      session_id: 'session-1',
      messages: [],
      count: 0,
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
          message_length: 0,
          timestamp: Date.now() / 1000,
        },
      });
    vi.mocked(messagesApi.uploadAttachment).mockRejectedValue(
      new Error('upload should not start'),
    );

    render(<ChatPage />);
    const composer = screen.getByPlaceholderText('chat.inputPlaceholder');
    await user.type(composer, 'Old uncertain turn');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));
    await waitFor(() => {
      expect(toastWarningMock).toHaveBeenCalledWith('chat.sendUnconfirmed');
    });

    await user.clear(composer);
    await user.type(composer, 'Changed draft with attachment');
    await user.click(screen.getByRole('button', { name: 'chat.attachments.add' }));
    await user.upload(
      screen.getByTestId('chat-attachments-file-input'),
      new File(['draft'], 'changed.md', { type: 'text/markdown' }),
    );
    await user.click(screen.getByRole('button', { name: 'chat.send' }));

    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(3);
      expect(screen.getByRole('button', { name: 'chat.stop' })).toBeInTheDocument();
    });
    expect(messagesApi.uploadAttachment).not.toHaveBeenCalled();
    expect(screen.getByRole('textbox')).toHaveValue('Changed draft with attachment');
    expect(screen.getByTestId('chat-composer-attachments')).toHaveTextContent('changed.md');
  });

  it('does not treat a retry-time 4xx as proof the old turn was rejected', async () => {
    const user = userEvent.setup();
    const config = buildConfigWithVision(true) as any;
    config.data.preferences = {
      ...(config.data.preferences || {}),
      allow_interjection: true,
    };
    vi.mocked(configApi.get).mockResolvedValue(config);
    vi.mocked(messagesApi.getHistory).mockResolvedValue({
      user_id: 'local_user',
      session_id: 'session-1',
      messages: [],
      count: 0,
    } as any);
    vi.mocked(messagesApi.sendMessage)
      .mockRejectedValueOnce(new Error('offline'))
      .mockRejectedValueOnce(new Error('offline'))
      .mockRejectedValueOnce({
        kind: 'http',
        status: 409,
        message: 'conflict',
      });

    render(<ChatPage />);
    const composer = screen.getByPlaceholderText('chat.inputPlaceholder');
    await user.type(composer, 'Old uncertain text');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));
    await waitFor(() => {
      expect(toastWarningMock).toHaveBeenCalledWith('chat.sendUnconfirmed');
    });

    await user.clear(composer);
    await user.type(composer, 'Current visible text');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));

    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(3);
      expect(toastWarningMock).toHaveBeenCalledWith(
        'chat.previousSendUnconfirmed',
      );
    });
    const requests = vi.mocked(messagesApi.sendMessage).mock.calls
      .map(([request]) => request);
    expect(requests.every(
      (request) => request.message === 'Old uncertain text',
    )).toBe(true);
    expect(new Set(
      requests.map((request) => request.client_turn_id),
    )).toHaveLength(1);
    expect(screen.getByRole('textbox')).toHaveValue('Current visible text');
  });

  it('keeps a changed draft when its upload fails after the old turn is terminal', async () => {
    const user = userEvent.setup();
    const config = buildConfigWithVision(true) as any;
    config.data.preferences = {
      ...(config.data.preferences || {}),
      allow_interjection: false,
    };
    vi.mocked(configApi.get).mockResolvedValue(config);
    vi.mocked(messagesApi.sendMessage)
      .mockRejectedValueOnce(new Error('offline'))
      .mockRejectedValueOnce(new Error('offline'))
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
    vi.mocked(messagesApi.getHistory).mockImplementation(async () => {
      const oldTurnId = vi.mocked(messagesApi.sendMessage).mock.calls[0]?.[0]?.client_turn_id;
      if (
        vi.mocked(messagesApi.sendMessage).mock.calls.length < 3
        || !oldTurnId
      ) {
        return {
          user_id: 'local_user',
          session_id: 'session-1',
          messages: [],
          count: 0,
        } as any;
      }
      return {
        user_id: 'local_user',
        session_id: 'session-1',
        messages: [{
          message_id: 'old-terminal-turn',
          message_kind: 'user_text',
          role: 'user',
          kind: 'user',
          content: 'Old uncertain turn',
          timestamp: Date.now() / 1000,
          turn_id: oldTurnId,
          run_state: { state: 'completed' },
        }],
        count: 1,
      } as any;
    });
    vi.mocked(messagesApi.uploadAttachment).mockRejectedValue(
      new Error('disk unavailable'),
    );

    render(<ChatPage />);
    const composer = screen.getByPlaceholderText('chat.inputPlaceholder');
    await user.type(composer, 'Old uncertain turn');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));
    await waitFor(() => {
      expect(toastWarningMock).toHaveBeenCalledWith('chat.sendUnconfirmed');
    });

    await user.clear(composer);
    await user.type(composer, 'Changed terminal draft');
    await user.click(screen.getByRole('button', { name: 'chat.attachments.add' }));
    await user.upload(
      screen.getByTestId('chat-attachments-file-input'),
      new File(['draft'], 'terminal.md', { type: 'text/markdown' }),
    );
    await user.click(screen.getByRole('button', { name: 'chat.send' }));

    await waitFor(() => {
      expect(messagesApi.uploadAttachment).toHaveBeenCalledTimes(1);
      expect(toastErrorMock).toHaveBeenCalledWith('chat.attachments.uploadFailed');
      expect(screen.getByRole('button', { name: 'chat.send' })).toBeInTheDocument();
    });
    expect(messagesApi.sendMessage).toHaveBeenCalledTimes(3);
    expect(screen.getByRole('textbox')).toHaveValue('Changed terminal draft');
    expect(screen.getByTestId('chat-composer-attachments')).toHaveTextContent('terminal.md');
  });

  it('clears a matching retry after leaving and returning to its session', async () => {
    const user = userEvent.setup();
    vi.mocked(messagesApi.getHistory).mockResolvedValue(emptyHistory());
    vi.mocked(messagesApi.sendMessage)
      .mockRejectedValueOnce(new Error('offline'))
      .mockRejectedValueOnce(new Error('offline'))
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
    await user.type(
      screen.getByPlaceholderText('chat.inputPlaceholder'),
      'Retry after navigation',
    );
    await user.click(screen.getByRole('button', { name: 'chat.send' }));
    await waitFor(() => {
      expect(toastWarningMock).toHaveBeenCalledWith('chat.sendUnconfirmed');
    });

    act(() => {
      useConversationStore.getState().setCurrentSessionId('session-2');
    });
    act(() => {
      useConversationStore.getState().setCurrentSessionId('session-1');
    });
    expect(screen.getByRole('textbox')).toHaveValue('Retry after navigation');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));

    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(3);
      expect(screen.getByRole('textbox')).toHaveValue('');
    });
    const turnIds = vi.mocked(messagesApi.sendMessage).mock.calls
      .map(([request]) => request.client_turn_id);
    expect(new Set(turnIds)).toHaveLength(1);
  });

  it('restores the exact non-terminal turn lock from history', async () => {
    const config = buildConfigWithVision(true) as any;
    config.data.preferences = {
      ...(config.data.preferences || {}),
      allow_interjection: false,
    };
    vi.mocked(configApi.get).mockResolvedValue(config);
    vi.mocked(messagesApi.getHistory).mockResolvedValue({
      user_id: 'local_user',
      session_id: 'session-1',
      history_version: 7,
      messages: [{
        message_id: 'msg-restored-running',
        message_kind: 'user_text',
        role: 'user',
        kind: 'user',
        content: 'Keep processing this turn',
        timestamp: Date.now() / 1000,
        turn_id: 'turn-restored-running',
        run_state: { state: 'running' },
      }],
    } as any);

    render(<ChatPage />);

    expect(await screen.findByText('Keep processing this turn')).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'chat.stop' })).toBeInTheDocument();
  });

  it('returns to send mode when stop finds no active run', async () => {
    const user = userEvent.setup();
    const config = buildConfigWithVision(true) as any;
    config.data.preferences = {
      ...(config.data.preferences || {}),
      allow_interjection: false,
    };
    vi.mocked(configApi.get).mockResolvedValue(config);
    vi.mocked(messagesApi.cancelRun).mockResolvedValue({
      success: false,
      message: 'no active run',
      data: {
        user_id: 'local_user',
        session_id: 'session-1',
      },
    });

    render(<ChatPage />);
    await waitFor(() => expect(configApi.get).toHaveBeenCalled());

    await user.type(screen.getByPlaceholderText('chat.inputPlaceholder'), 'Stop this stale turn');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));
    await user.click(await screen.findByRole('button', { name: 'chat.stop' }));

    await waitFor(() => {
      expect(messagesApi.cancelRun).toHaveBeenCalledTimes(1);
      expect(screen.getByRole('button', { name: 'chat.send' })).toBeInTheDocument();
    });
  });

  it('releases a pending stop after terminal history reconciliation', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({
      advanceTimers: vi.advanceTimersByTime,
    });
    const config = buildConfigWithVision(true) as any;
    config.data.preferences = {
      ...(config.data.preferences || {}),
      allow_interjection: false,
    };
    vi.mocked(configApi.get).mockResolvedValue(config);
    let terminal = false;
    const historyForCurrentState = () => ({
      user_id: 'local_user',
      session_id: 'session-1',
      history_version: terminal ? 12 : 11,
      messages: [{
        message_id: 'msg-stop-reconcile',
        message_kind: 'user_text',
        role: 'user',
        kind: 'user',
        content: 'Reconcile this stop',
        timestamp: Date.now() / 1000,
        turn_id: 'turn-stop-reconcile',
        run_state: {
          state: terminal ? 'cancelled' : 'running',
        },
      }],
    });
    vi.mocked(messagesApi.getHistory).mockImplementation(async () => (
      historyForCurrentState() as any
    ));
    vi.mocked(messagesApi.cancelRun).mockResolvedValue({
      success: true,
      message: 'cancelling',
      data: {
        user_id: 'local_user',
        session_id: 'session-1',
        run_id: 'run-stop-reconcile',
        status: 'cancelling',
      },
    });

    render(<ChatPage />);
    expect(await screen.findByText('Reconcile this stop')).toBeInTheDocument();
    await user.click(
      await screen.findByRole('button', { name: 'chat.stop' }),
    );
    await waitFor(() => {
      expect(messagesApi.cancelRun).toHaveBeenCalledTimes(1);
    });

    terminal = true;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(
        PENDING_HISTORY_RECONCILE_DELAY_MS,
      );
    });
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'chat.send' })).toBeInTheDocument();
    });

    terminal = false;
    act(() => {
      useConversationStore.getState().receiveHistory(
        'session-1',
        normalizeHistoryMessages(historyForCurrentState().messages as any),
        13,
      );
      realtimeListener?.({
        event: 'turn_execution_control',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-stop-reconcile',
          state: 'running',
        },
      });
    });
    await user.click(
      await screen.findByRole('button', { name: 'chat.stop' }),
    );

    await waitFor(() => {
      expect(messagesApi.cancelRun).toHaveBeenCalledTimes(2);
      expect(messagesApi.cancelRun).toHaveBeenLastCalledWith(
        'local_user',
        'session-1',
        {
          reason: 'user_cancel',
          turnId: 'turn-stop-reconcile',
        },
      );
    });
  });

  it('can turn a recall correction into an ordinary message', async () => {
    const user = userEvent.setup();
    useConversationStore.getState().receiveHistory(
      'session-1',
      normalizeHistoryMessages([
        {
          message_id: 'assistant-memory-answer',
          message_kind: 'assistant_final',
          role: 'assistant',
          content: 'Previous answer',
          timestamp: 1100,
          turn_id: 'turn-memory',
          kind: 'assistant',
          payload: {
            recalled_memories: [{
              kind: 'event',
              source_layer: 'L1',
              statement: 'Visited example.com',
              topic: 'example.com',
              feedback_ref: 'event:event-1',
            }],
          },
        },
      ]),
    );

    render(<ChatPage />);
    await user.click(screen.getByRole('button', { name: 'chat.recalledMemories.summary' }));
    await user.click(screen.getByRole('button', { name: 'chat.recallFeedback.answerAction' }));
    await user.click(screen.getByRole('button', { name: 'chat.recallFeedback.convertToNormal' }));

    expect(screen.queryByTestId('recall-feedback-banner')).not.toBeInTheDocument();
    expect(screen.getByRole('textbox')).toHaveValue('chat.recallFeedback.templates.answerEvidenceMismatch');

    await user.click(screen.getByRole('button', { name: 'chat.send' }));
    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledWith(expect.not.objectContaining({
        recall_feedback: expect.anything(),
      }));
    });
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
});
