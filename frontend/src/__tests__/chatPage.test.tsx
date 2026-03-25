import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ChatPage } from '@/pages/Chat';
import { useConversationStore } from '@/stores/conversation-store';
import { useChatTraceStore, useRealtimeStore } from '@/stores';
import { normalizeHistoryMessages, shouldShowTraceEntry } from '@/pages/chat-state';
import { messagesApi } from '@/api';
import { configApi, DEFAULT_SYSTEM_CONFIG } from '@/api/modules/config';

const sendMock = vi.fn();
let realtimeListener: ((message: Record<string, unknown>) => void) | null = null;
const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
const { pickDirectoryMock, convertFileSrcMock, toastWarningMock } = vi.hoisted(() => ({
  pickDirectoryMock: vi.fn(),
  convertFileSrcMock: vi.fn((path: string) => `asset://${path}`),
  toastWarningMock: vi.fn(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'zh-CN' },
  }),
}));

vi.mock('sonner', () => ({
  toast: {
    warning: toastWarningMock,
    error: vi.fn(),
    success: vi.fn(),
  },
}));

vi.mock('@/realtime/provider', () => ({
  useRealtime: () => ({
    send: sendMock,
    subscribe: (listener: (message: Record<string, unknown>) => void) => {
      realtimeListener = listener;
      return () => {
        realtimeListener = null;
      };
    },
  }),
}));

vi.mock('@/runtime/config', () => ({
  getRuntimeConfig: () => ({
    apiBaseUrl: 'http://127.0.0.1:8000/api',
  }),
}));

vi.mock('@/runtime/desktop', () => ({
  pickDirectory: pickDirectoryMock,
}));

vi.mock('@tauri-apps/api/core', () => ({
  convertFileSrc: convertFileSrcMock,
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
    cancelRun: vi.fn(),
    labelMessage: vi.fn(),
    deleteMessage: vi.fn(),
  },
}));

vi.mock('@/components/chat/ToolchainDrawer', () => ({
  default: () => null,
}));

describe('ChatPage', () => {
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
    sendMock.mockReset();
    useConversationStore.getState().reset();
    useChatTraceStore.getState().reset();
    useRealtimeStore.getState().reset();
    cleanup();
    document.body.innerHTML = '';
  });

  beforeEach(() => {
    sendMock.mockReset();
    realtimeListener = null;
    consoleErrorSpy.mockClear();
    pickDirectoryMock.mockReset();
    pickDirectoryMock.mockResolvedValue(undefined);
    toastWarningMock.mockReset();
    vi.mocked(messagesApi.labelMessage).mockReset();
    vi.mocked(messagesApi.deleteMessage).mockReset();
    vi.mocked(configApi.get).mockResolvedValue(buildConfigWithVision(true) as any);
    Element.prototype.scrollIntoView = vi.fn();
    URL.createObjectURL = vi.fn(() => 'blob:chat-attachment');
    URL.revokeObjectURL = vi.fn();
    useConversationStore.getState().reset();
    useChatTraceStore.getState().reset();
    useRealtimeStore.getState().setConnected(true);
    useConversationStore.getState().setCurrentSessionId('session-1');
  });

  it('shows a lightweight workspace status bar with count and path', async () => {
    useConversationStore.getState().hydrateSessions([
      {
        session_id: 'session-1',
        title: 'New Chat',
        last_message_preview: '',
        last_user_message_preview: '',
        title_overridden: false,
        last_timestamp: 0,
        message_count: 0,
        workspace_path: '/Users/asuka/code/magi',
      },
    ], 'session-1');
    useConversationStore.getState().receiveHistory(
      'session-1',
      normalizeHistoryMessages([
        { role: 'user', content: 'hello', timestamp: 1000, turn_id: 't-1', kind: 'user' },
        { role: 'assistant', content: 'world', timestamp: 2000, turn_id: 't-1', kind: 'assistant' },
      ])
    );

    render(<ChatPage />);

    expect(screen.queryByText('chat.workspace.label')).not.toBeInTheDocument();
    expect(screen.getByTestId('chat-workspace-path')).toHaveTextContent('/Users/asuka/code/magi');
    expect(screen.getByTestId('chat-workspace-message-count')).toHaveTextContent('2');
    expect(screen.getByText('hello').parentElement).toHaveClass('rounded-xl', 'rounded-tr-sm');
    expect(screen.getByText('world').parentElement?.parentElement).toHaveClass('rounded-xl', 'rounded-tl-sm');
  });

  it('updates and clears the current session workspace from the status bar', async () => {
    const user = userEvent.setup();
    pickDirectoryMock.mockResolvedValue('/tmp/next-workspace');
    vi.mocked(messagesApi.updateSessionWorkspace)
      .mockResolvedValueOnce({
        success: true,
        user_id: 'local_user',
        session: {
          session_id: 'session-1',
          title: 'New Chat',
          last_message_preview: '',
          last_user_message_preview: '',
          title_overridden: false,
          last_timestamp: 0,
          message_count: 0,
          workspace_path: '/tmp/next-workspace',
        },
      } as any)
      .mockResolvedValueOnce({
        success: true,
        user_id: 'local_user',
        session: {
          session_id: 'session-1',
          title: 'New Chat',
          last_message_preview: '',
          last_user_message_preview: '',
          title_overridden: false,
          last_timestamp: 0,
          message_count: 0,
          workspace_path: null,
        },
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
        workspace_path: '/Users/asuka/code/magi',
      },
    ], 'session-1');

    render(<ChatPage />);

    await user.click(screen.getByRole('button', { name: 'chat.workspace.change' }));

    await waitFor(() => expect(pickDirectoryMock).toHaveBeenCalledWith('/Users/asuka/code/magi'));
    await waitFor(() => expect(messagesApi.updateSessionWorkspace).toHaveBeenCalledWith('local_user', 'session-1', '/tmp/next-workspace'));
    expect(screen.getByTestId('chat-workspace-path')).toHaveTextContent('/tmp/next-workspace');

    await user.click(screen.getByRole('button', { name: 'chat.workspace.clear' }));

    await waitFor(() => expect(messagesApi.updateSessionWorkspace).toHaveBeenLastCalledWith('local_user', 'session-1', null));
    expect(screen.getByTestId('chat-workspace-path')).toHaveTextContent('~/.magi/chat-workspace');
  });

  it('shows the fallback Magi workspace path when no session directory is selected', async () => {
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

    expect(await screen.findByTestId('chat-workspace-path')).toHaveTextContent('~/.magi/chat-workspace');
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

  it('renders a quieter editor-style composer shell', async () => {
    render(<ChatPage />);

    const composerInput = await screen.findByTestId('chat-composer-input');
    const composerRoot = composerInput.parentElement;
    const toolbar = screen.getByTestId('chat-composer-toolbar');
    const sendButton = screen.getByRole('button', { name: 'chat.send' });
    const textarea = screen.getByPlaceholderText('chat.inputPlaceholder') as HTMLTextAreaElement;

    expect(composerRoot).toHaveClass('rounded-2xl');
    expect(composerRoot).not.toHaveClass('rounded-[28px]');
    expect(toolbar).not.toHaveClass('border-t');
    expect(sendButton).toHaveClass('h-10', 'w-10');
    expect(textarea.style.height).toBe('88px');
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
        workspace_path: '/Users/asuka/code/magi',
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
    expect(sendMock).toHaveBeenCalledWith({
      type: 'send_message',
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
      workspace_path: '/Users/asuka/code/magi',
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
    expect(preview).toHaveAttribute('src', 'asset:///tmp/history-diagram.png');
    expect(convertFileSrcMock).toHaveBeenCalledWith('/tmp/history-diagram.png');
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
      'asset:///tmp/history-diagram.png',
    );
    expect(within(dialog).getAllByText('diagram.png').length).toBeGreaterThan(0);
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
      expect(sendMock).toHaveBeenCalledWith(expect.objectContaining({
        type: 'send_message',
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

    await user.click(screen.getByRole('button', { name: 'chat.reply.action' }));
    await user.type(screen.getByPlaceholderText('chat.inputPlaceholder'), 'Reply from composer');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));

    const sendMessageCall = sendMock.mock.calls.find(
      ([payload]) => payload?.type === 'send_message' && payload?.message === 'Reply from composer'
    );
    const replyTurnId = String(sendMessageCall?.[0]?.client_turn_id || '');
    expect(replyTurnId).not.toBe('');

    sendMock.mockClear();

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

    expect(sendMock).not.toHaveBeenCalledWith(expect.objectContaining({
      type: 'get_history',
      session_id: 'session-1',
    }));
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

  it('renders a more prominent trace entry when ux plan requests prominent trace display', async () => {
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

    expect(view.container.querySelector('[data-trace-variant="prominent"]')).toBeInTheDocument();
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

  it('renders a thinking status card when ux plan requests visible thinking feedback', async () => {
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

    expect(sendMock).toHaveBeenCalledWith({
      type: 'get_history',
      session_id: 'session-1',
    });
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

  it('requests run cancellation from the running trace status card', async () => {
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

    const runningCard = screen.getByTestId('chat-trace-status-card-turn-running');
    await userEvent.click(within(runningCard).getByRole('button', { name: 'chat.trace.cancelRun' }));

    await waitFor(() => {
      expect(messagesApi.cancelRun).toHaveBeenCalledWith('local_user', 'session-1', {
        reason: 'user_cancel',
        turnId: 'turn-running',
      });
    });
  });

  it('updates the running trace status card from execution control websocket events', async () => {
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
      const runningCard = screen.getByTestId('chat-trace-status-card-turn-running');
      expect(within(runningCard).getByRole('button', { name: 'chat.trace.cancelRun' })).toBeEnabled();
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
      const runningCard = screen.getByTestId('chat-trace-status-card-turn-running');
      expect(within(runningCard).getByText('Cancelling run')).toBeInTheDocument();
      expect(within(runningCard).getByText('chat.trace.execution.cancellingBody')).toBeInTheDocument();
      expect(within(runningCard).getByRole('button', { name: 'chat.trace.cancelRun' })).toBeDisabled();
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
      const runningCard = screen.getByTestId('chat-trace-status-card-turn-running');
      expect(within(runningCard).getByText('Run cancelled')).toBeInTheDocument();
      expect(within(runningCard).getByText('chat.trace.execution.cancelledBody')).toBeInTheDocument();
      expect(within(runningCard).getByText('chat.trace.execution.footerCancelled')).toBeInTheDocument();
      expect(within(runningCard).queryByRole('button', { name: 'chat.trace.cancelRun' })).not.toBeInTheDocument();
      expect(sendMock).toHaveBeenCalledWith({
        type: 'get_history',
        session_id: 'session-1',
      });
    });
  });

  it('renders a richer orchestration plan preview on the running trace status card', async () => {
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
      expect(screen.getByText('梳理现有文档和范围')).toBeInTheDocument();
    });

    expect(screen.getByText('盘点代码结构与运行方式')).toBeInTheDocument();
    expect(screen.getByText('整理 MVP 验收清单')).toBeInTheDocument();
    expect(screen.getByText('chat.trace.plan.stage.runningParallel')).toBeInTheDocument();
    expect(screen.getByText('chat.trace.plan.parallel')).toBeInTheDocument();
    expect(screen.getByText('chat.trace.plan.stepStatus.completed')).toBeInTheDocument();
    expect(screen.getByText('chat.trace.plan.stepStatus.running')).toBeInTheDocument();
    expect(screen.getByText('chat.trace.plan.stepStatus.pending')).toBeInTheDocument();
    expect(screen.getByText('chat.trace.plan.moreSteps')).toBeInTheDocument();
  });

  it('does not ask the backend for a current session after websocket subscribe', () => {
    useConversationStore.getState().setCurrentSessionId(null);
    sendMock.mockClear();
    render(<ChatPage />);

    act(() => {
      realtimeListener?.({
        type: 'subscribed',
      });
    });

    expect(sendMock).not.toHaveBeenCalledWith({ type: 'get_current_session' });
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
