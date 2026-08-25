import {
  defineChatPageSuite,
  realtimeListener,
  openExternalUrlMock,
  convertFileSrcMock,
  toastErrorMock,
  toastWarningMock,
  setMockFileSize,
  buildConfigWithVision,
  historyWithMessages,
  emptyHistory,
  seedRetryableOperations,
} from '@/test/chatPageHarness';
import React from 'react';
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
import { normalizeHistoryMessages } from '@/domain/chat/state';
import { messagesApi } from '@/api';
import { configApi } from '@/api/modules/config';
import {
  CHAT_RETRYABLE_SEND_STORAGE_KEY,
  INLINE_SKILL_RETRY_STORAGE_KEY,
} from '@/hooks/chatRetryableSendStorage';

defineChatPageSuite('ChatPage message interactions', () => {
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
      reply_to_message_id: undefined,
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

  it('keeps attachment and reply drafts when the send is explicitly rejected', async () => {
    const user = userEvent.setup();
    vi.mocked(messagesApi.uploadAttachment).mockResolvedValue({
      attachment_id: 'att-rejected',
      kind: 'image',
      original_name: 'keep.png',
      mime_type: 'image/png',
      size_bytes: 5,
      storage_path: '/tmp/keep.png',
      sha256: 'abc',
      parse_status: 'not_applicable',
    } as any);
    vi.mocked(messagesApi.sendMessage).mockResolvedValueOnce({
      success: false,
      message: 'blocked',
      data: null,
    } as any);
    vi.mocked(messagesApi.getHistory).mockResolvedValue(historyWithMessages([{
      message_id: 'reply-anchor',
      message_kind: 'assistant_final',
      role: 'assistant',
      kind: 'assistant',
      content: 'Reply anchor',
      timestamp: 1000,
      turn_id: 'reply-anchor-turn',
    }]));
    useConversationStore.getState().receiveHistory(
      'session-1',
      normalizeHistoryMessages([{
        message_id: 'reply-anchor',
        message_kind: 'assistant_final',
        role: 'assistant',
        kind: 'assistant',
        content: 'Reply anchor',
        timestamp: 1000,
        turn_id: 'reply-anchor-turn',
      }]),
    );

    render(<ChatPage />);
    await waitFor(() => expect(configApi.get).toHaveBeenCalled());
    await user.click(screen.getByRole('button', { name: 'chat.reply.action' }));
    await user.click(screen.getByRole('button', { name: 'chat.attachments.add' }));
    const imageInput = screen.getByTestId('chat-attachments-image-input') as HTMLInputElement;
    await user.upload(imageInput, new File(['image'], 'keep.png', { type: 'image/png' }));
    await user.type(screen.getByPlaceholderText('chat.inputPlaceholder'), 'Keep the whole draft');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));

    await waitFor(() => {
      expect(toastErrorMock).toHaveBeenCalledWith('blocked');
      expect(screen.getByRole('button', { name: 'chat.send' })).toBeInTheDocument();
    });
    expect(screen.getByPlaceholderText('chat.inputPlaceholder')).toHaveValue('Keep the whole draft');
    expect(screen.getByTestId('chat-composer-reply-preview')).toHaveTextContent('Reply anchor');
    expect(screen.getByTestId('chat-composer-attachments')).toHaveTextContent('keep.png');
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();
    expect(messagesApi.sendMessage).toHaveBeenCalledWith(expect.objectContaining({
      reply_to_message_id: 'reply-anchor',
      attachments: [expect.objectContaining({ attachment_id: 'att-rejected' })],
    }));
  });

  it('recovers an unconfirmed attachment send after a page remount', async () => {
    const user = userEvent.setup();
    const config = buildConfigWithVision(true) as any;
    config.data.preferences = {
      ...(config.data.preferences || {}),
      allow_interjection: true,
    };
    vi.mocked(configApi.get).mockResolvedValue(config);
    const uploadedAttachment = {
      attachment_id: 'att-refresh',
      kind: 'text_file',
      original_name: 'refresh.txt',
      mime_type: 'text/plain',
      size_bytes: 15,
      storage_path: '/tmp/refresh.txt',
      sha256: 'refresh-sha',
      parse_status: 'parsed',
      session_id: 'session-1',
      turn_id: 'server-bound-turn',
      character_count: 15,
      truncated: false,
      encoding: 'utf-8',
      page_count: 0,
      extraction_succeeded: true,
      parse_error: null,
    };
    vi.mocked(messagesApi.uploadAttachment).mockResolvedValue(
      uploadedAttachment as any,
    );
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
    await user.click(screen.getByRole('button', { name: 'chat.attachments.add' }));
    await user.upload(
      screen.getByTestId('chat-attachments-file-input'),
      new File(['refresh payload'], 'refresh.txt', { type: 'text/plain' }),
    );
    await user.type(
      screen.getByPlaceholderText('chat.inputPlaceholder'),
      'Before refresh',
    );
    await user.click(screen.getByRole('button', { name: 'chat.send' }));
    await waitFor(() => {
      expect(toastWarningMock).toHaveBeenCalledWith('chat.sendUnconfirmed');
      expect(window.sessionStorage.getItem(
        CHAT_RETRYABLE_SEND_STORAGE_KEY,
      )).not.toBeNull();
    });
    const oldRequest = vi.mocked(messagesApi.sendMessage).mock.calls[0]?.[0];
    expect(oldRequest?.attachments).toEqual([uploadedAttachment]);
    const storedEnvelope = JSON.parse(
      window.sessionStorage.getItem(CHAT_RETRYABLE_SEND_STORAGE_KEY) || '{}',
    );
    expect(storedEnvelope.operations?.[0]?.request?.attachments).toEqual([
      uploadedAttachment,
    ]);
    expect(storedEnvelope.operations?.[0]?.request).not.toHaveProperty('file');

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
    vi.mocked(messagesApi.uploadAttachment).mockClear();
    toastWarningMock.mockClear();

    render(<ChatPage />);
    await user.type(
      screen.getByPlaceholderText('chat.inputPlaceholder'),
      'After refresh',
    );
    await user.click(screen.getByRole('button', { name: 'chat.send' }));

    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(1);
      expect(toastWarningMock).toHaveBeenCalledWith(
        'chat.restoredSendResolved',
      );
    });
    const recoveredRequest = vi.mocked(messagesApi.sendMessage).mock.calls[0]?.[0];
    expect(recoveredRequest?.client_turn_id).toBe(oldRequest?.client_turn_id);
    expect(recoveredRequest?.message).toBe('Before refresh');
    expect(recoveredRequest?.attachments).toEqual(oldRequest?.attachments);
    expect(messagesApi.uploadAttachment).not.toHaveBeenCalled();
    expect(screen.getByRole('textbox')).toHaveValue('After refresh');
    expect(window.sessionStorage.getItem(
      CHAT_RETRYABLE_SEND_STORAGE_KEY,
    )).toBeNull();

    await user.click(screen.getByRole('button', { name: 'chat.send' }));
    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(2);
      expect(screen.getByRole('textbox')).toHaveValue('');
    });
    const currentRequest = vi.mocked(messagesApi.sendMessage).mock.calls[1]?.[0];
    expect(currentRequest?.message).toBe('After refresh');
    expect(currentRequest?.client_turn_id).not.toBe(oldRequest?.client_turn_id);
    expect(currentRequest?.attachments).toEqual([]);
  });

  it('keeps an async upload bound to its origin session after navigation', async () => {
    const user = userEvent.setup();
    let resolveUpload: ((value: any) => void) | null = null;
    vi.mocked(messagesApi.uploadAttachment).mockReturnValue(new Promise((resolve) => {
      resolveUpload = resolve;
    }) as ReturnType<typeof messagesApi.uploadAttachment>);
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

    await user.click(screen.getByRole('button', { name: 'chat.attachments.add' }));
    const fileInput = screen.getByTestId('chat-attachments-file-input') as HTMLInputElement;
    await user.upload(fileInput, new File(['notes'], 'origin.md', { type: 'text/markdown' }));
    await user.type(screen.getByPlaceholderText('chat.inputPlaceholder'), 'Send from session one');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));
    await waitFor(() => expect(messagesApi.uploadAttachment).toHaveBeenCalledTimes(1));

    act(() => {
      useConversationStore.getState().setCurrentSessionId('session-2');
    });
    const currentComposer = screen.getByPlaceholderText('chat.inputPlaceholder');
    await user.clear(currentComposer);
    await user.type(currentComposer, 'Keep this session two draft');

    await act(async () => {
      resolveUpload?.({
        attachment_id: 'att-origin',
        kind: 'text_file',
        original_name: 'origin.md',
        mime_type: 'text/markdown',
        size_bytes: 5,
        storage_path: '/tmp/origin.md',
        sha256: 'abc',
        parse_status: 'parsed',
      });
    });

    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledWith(expect.objectContaining({
        session_id: 'session-1',
        message: 'Send from session one',
        attachments: [
          expect.objectContaining({ attachment_id: 'att-origin' }),
        ],
      }));
    });
    expect(useConversationStore.getState().currentSessionId).toBe('session-2');
    expect(screen.getByPlaceholderText('chat.inputPlaceholder')).toHaveValue(
      'Keep this session two draft',
    );
    expect(
      useConversationStore.getState().messagesBySession['session-1']
        ?.some((message) => message.content === 'Send from session one'),
    ).toBe(true);
  });

  it('does not clear a same-text draft recreated after switching sessions', async () => {
    const user = userEvent.setup();
    let resolveSend: ((
      value: Awaited<ReturnType<typeof messagesApi.sendMessage>>,
    ) => void) | null = null;
    const config = buildConfigWithVision(true) as any;
    config.data.preferences = {
      ...(config.data.preferences || {}),
      allow_interjection: true,
    };
    vi.mocked(configApi.get).mockResolvedValue(config);
    vi.mocked(messagesApi.sendMessage).mockReturnValue(new Promise((resolve) => {
      resolveSend = resolve;
    }) as ReturnType<typeof messagesApi.sendMessage>);
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
    await user.type(composer, 'Same visible text');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));
    await waitFor(() => expect(messagesApi.sendMessage).toHaveBeenCalledTimes(1));

    act(() => {
      useConversationStore.getState().setCurrentSessionId('session-2');
    });
    await user.clear(screen.getByPlaceholderText('chat.inputPlaceholder'));
    await user.type(
      screen.getByPlaceholderText('chat.inputPlaceholder'),
      'Temporary different draft',
    );
    await user.clear(screen.getByPlaceholderText('chat.inputPlaceholder'));
    await user.type(
      screen.getByPlaceholderText('chat.inputPlaceholder'),
      'Same visible text',
    );
    act(() => {
      useConversationStore.getState().setCurrentSessionId('session-1');
    });

    await act(async () => {
      resolveSend?.({
        success: true,
        message: 'ok',
        data: {
          user_id: 'local_user',
          session_id: 'session-1',
          message_length: 17,
          timestamp: Date.now() / 1000,
        },
      });
    });

    expect(screen.getByPlaceholderText('chat.inputPlaceholder')).toHaveValue(
      'Same visible text',
    );
  });

  it('sends the visible draft instead of a hidden retry after navigation', async () => {
    const user = userEvent.setup();
    let rejectFirstSend: ((reason?: unknown) => void) | null = null;
    const config = buildConfigWithVision(true) as any;
    config.data.preferences = {
      ...(config.data.preferences || {}),
      allow_interjection: true,
    };
    vi.mocked(configApi.get).mockResolvedValue(config);
    vi.mocked(messagesApi.uploadAttachment).mockResolvedValue({
      attachment_id: 'att-origin-retry',
      kind: 'text_file',
      original_name: 'origin-retry.md',
      mime_type: 'text/markdown',
      size_bytes: 5,
      storage_path: '/tmp/origin-retry.md',
      sha256: 'abc',
      parse_status: 'parsed',
    } as any);
    vi.mocked(messagesApi.sendMessage)
      .mockReturnValueOnce(new Promise((_resolve, reject) => {
        rejectFirstSend = reject;
      }))
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
    vi.mocked(messagesApi.getHistory).mockResolvedValue({
      user_id: 'local_user',
      session_id: 'session-1',
      messages: [],
      count: 0,
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
    await waitFor(() => expect(configApi.get).toHaveBeenCalled());
    await user.click(screen.getByRole('button', { name: 'chat.attachments.add' }));
    const fileInput = screen.getByTestId('chat-attachments-file-input') as HTMLInputElement;
    await user.upload(fileInput, new File(['notes'], 'origin-retry.md', { type: 'text/markdown' }));
    await user.type(screen.getByPlaceholderText('chat.inputPlaceholder'), 'Retry session one');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));
    await waitFor(() => expect(messagesApi.sendMessage).toHaveBeenCalledTimes(1));

    act(() => {
      useConversationStore.getState().setCurrentSessionId('session-2');
    });
    await user.clear(screen.getByPlaceholderText('chat.inputPlaceholder'));
    await user.type(screen.getByPlaceholderText('chat.inputPlaceholder'), 'Keep session two draft');
    await act(async () => {
      rejectFirstSend?.(new Error('response lost'));
    });

    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(2);
      expect(toastWarningMock).toHaveBeenCalledWith('chat.sendUnconfirmed');
    });

    act(() => {
      useConversationStore.getState().setCurrentSessionId('session-1');
    });
    expect(screen.getByPlaceholderText('chat.inputPlaceholder')).toHaveValue('Keep session two draft');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));

    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledTimes(4);
      expect(screen.getByRole('textbox')).toHaveValue('');
    });
    const requests = vi.mocked(messagesApi.sendMessage).mock.calls.map(([request]) => request);
    expect(requests[1]?.client_turn_id).toBe(requests[0]?.client_turn_id);
    expect(requests[2]?.client_turn_id).toBe(requests[0]?.client_turn_id);
    expect(requests[2]?.message).toBe('Retry session one');
    expect(requests[3]?.client_turn_id).not.toBe(requests[0]?.client_turn_id);
    expect(requests[3]).toEqual(expect.objectContaining({
      session_id: 'session-1',
      message: 'Keep session two draft',
      attachments: [],
    }));
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
    vi.mocked(messagesApi.getHistory).mockClear();

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
      cleanup_pending: false,
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

  it('unlocks the composer when the pending user message is deleted', async () => {
    const user = userEvent.setup();
    seedRetryableOperations({
      composerTurnId: 'turn-pending-delete',
      inlineTurnId: 'turn-pending-delete',
    });
    const config = buildConfigWithVision(true) as any;
    config.data.preferences = {
      ...(config.data.preferences || {}),
      allow_interjection: false,
    };
    vi.mocked(configApi.get).mockResolvedValue(config);
    vi.mocked(messagesApi.getHistory).mockResolvedValue({
      user_id: 'local_user',
      session_id: 'session-1',
      history_version: 8,
      messages: [{
        message_id: 'msg-pending-delete',
        message_kind: 'user_text',
        role: 'user',
        kind: 'user',
        content: 'Delete this pending turn',
        timestamp: Date.now() / 1000,
        turn_id: 'turn-pending-delete',
        run_state: { state: 'running' },
      }],
    } as any);
    vi.mocked(messagesApi.deleteMessage).mockResolvedValue({
      success: true,
      user_id: 'local_user',
      session_id: 'session-1',
      deleted_message_id: 'msg-pending-delete',
      cleanup_pending: false,
    } as any);

    render(<ChatPage />);

    const pendingMessage = await screen.findByText('Delete this pending turn');
    expect(await screen.findByRole('button', { name: 'chat.stop' })).toBeInTheDocument();

    fireEvent.contextMenu(pendingMessage);
    await user.click(screen.getByRole('button', { name: 'chat.context.delete' }));

    await waitFor(() => {
      expect(messagesApi.deleteMessage).toHaveBeenCalledWith(
        'local_user',
        'session-1',
        'msg-pending-delete',
      );
      expect(screen.getByRole('button', { name: 'chat.send' })).toBeInTheDocument();
    });
    expect(window.sessionStorage.getItem(
      CHAT_RETRYABLE_SEND_STORAGE_KEY,
    )).toBeNull();
    expect(window.sessionStorage.getItem(
      INLINE_SKILL_RETRY_STORAGE_KEY,
    )).toBeNull();

    vi.mocked(messagesApi.getHistory).mockResolvedValue(emptyHistory());
    await user.type(
      screen.getByPlaceholderText('chat.inputPlaceholder'),
      'Message after exact delete',
    );
    await user.click(screen.getByRole('button', { name: 'chat.send' }));
    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledWith(
        expect.objectContaining({ message: 'Message after exact delete' }),
      );
    });
  });

  it('unlocks the exact pending turn when its assistant message is deleted', async () => {
    const user = userEvent.setup();
    seedRetryableOperations({
      composerTurnId: 'turn-other-retry',
      inlineTurnId: 'turn-other-retry',
    });
    const config = buildConfigWithVision(true) as any;
    config.data.preferences = {
      ...(config.data.preferences || {}),
      allow_interjection: false,
    };
    vi.mocked(configApi.get).mockResolvedValue(config);
    vi.mocked(messagesApi.getHistory).mockResolvedValue({
      user_id: 'local_user',
      session_id: 'session-1',
      history_version: 9,
      messages: [
        {
          message_id: 'msg-user-assistant-delete',
          message_kind: 'user_text',
          role: 'user',
          kind: 'user',
          content: 'Keep the user row',
          timestamp: Date.now() / 1000 - 1,
          turn_id: 'turn-assistant-delete',
        },
        {
          message_id: 'msg-assistant-pending-delete',
          message_kind: 'assistant_interim',
          role: 'assistant',
          kind: 'assistant',
          content: 'Delete this pending assistant row',
          timestamp: Date.now() / 1000,
          turn_id: 'turn-assistant-delete',
          run_state: { state: 'running' },
        },
      ],
    } as any);
    vi.mocked(messagesApi.deleteMessage).mockResolvedValue({
      success: true,
      user_id: 'local_user',
      session_id: 'session-1',
      deleted_message_id: 'msg-assistant-pending-delete',
      cleanup_pending: false,
    } as any);

    render(<ChatPage />);

    const pendingMessage = await screen.findByText(
      'Delete this pending assistant row',
    );
    expect(await screen.findByRole('button', { name: 'chat.stop' })).toBeInTheDocument();

    fireEvent.contextMenu(pendingMessage);
    await user.click(screen.getByRole('button', { name: 'chat.context.delete' }));

    await waitFor(() => {
      expect(messagesApi.deleteMessage).toHaveBeenCalledWith(
        'local_user',
        'session-1',
        'msg-assistant-pending-delete',
      );
      expect(screen.getByRole('button', { name: 'chat.send' })).toBeInTheDocument();
    });
    expect(screen.getByText('Keep the user row')).toBeInTheDocument();
    expect(window.sessionStorage.getItem(
      CHAT_RETRYABLE_SEND_STORAGE_KEY,
    )).not.toBeNull();
    expect(window.sessionStorage.getItem(
      INLINE_SKILL_RETRY_STORAGE_KEY,
    )).not.toBeNull();
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
});
