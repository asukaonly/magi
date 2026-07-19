import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useChatMessageMutations } from '@/hooks/useChatMessageMutations';

const { deleteMessageMock, toastErrorMock, toastWarningMock } = vi.hoisted(() => ({
  deleteMessageMock: vi.fn(),
  toastErrorMock: vi.fn(),
  toastWarningMock: vi.fn(),
}));

vi.mock('@/api', () => ({
  messagesApi: {
    deleteMessage: deleteMessageMock,
    labelMessage: vi.fn(),
  },
}));

vi.mock('sonner', () => ({
  toast: {
    error: toastErrorMock,
    warning: toastWarningMock,
  },
}));

const message = {
  id: 'message-1',
  messageId: 'message-1',
  role: 'user' as const,
  kind: 'user' as const,
  content: 'Pending message',
  timestamp: 1,
  turnId: 'turn-1',
};

const renderMutations = () => {
  const clearPendingResponseTurn = vi.fn();
  const clearRetryableTurn = vi.fn();
  const clearComposerReferenceToMessage = vi.fn();
  const closeLabelPopover = vi.fn();
  const closeMessageContextMenu = vi.fn();
  const removeMessage = vi.fn();
  const result = renderHook(() => useChatMessageMutations({
    currentSessionId: 'session-1',
    activeLabelMessageId: null,
    applyMessageLabel: vi.fn(),
    removeMessage,
    clearRetryableTurn,
    clearPendingResponseTurn,
    clearComposerReferenceToMessage,
    closeLabelPopover,
    closeMessageContextMenu,
    normalizeCopyText: (value) => value,
    translate: (key) => key,
  }));
  return {
    ...result,
    clearPendingResponseTurn,
    clearRetryableTurn,
    clearComposerReferenceToMessage,
    closeMessageContextMenu,
    removeMessage,
  };
};

describe('useChatMessageMutations', () => {
  beforeEach(() => {
    deleteMessageMock.mockReset().mockResolvedValue({
      success: true,
      user_id: 'local_user',
      session_id: 'session-1',
      deleted_message_id: 'message-1',
      cleanup_pending: false,
    });
    toastErrorMock.mockReset();
    toastWarningMock.mockReset();
  });

  it('clears the exact retry only after deletion is confirmed', async () => {
    const hook = renderMutations();

    await act(async () => {
      await hook.result.current.handleDeleteMessage(message);
    });

    expect(deleteMessageMock).toHaveBeenCalledWith(
      'local_user',
      'session-1',
      'message-1',
    );
    expect(hook.removeMessage).toHaveBeenCalledWith(
      'session-1',
      'message-1',
    );
    expect(hook.clearRetryableTurn).toHaveBeenCalledWith(
      'session-1',
      'turn-1',
    );
    expect(hook.clearPendingResponseTurn).toHaveBeenCalledWith({
      sessionId: 'session-1',
      turnId: 'turn-1',
    });
    expect(hook.clearComposerReferenceToMessage).toHaveBeenCalledWith(
      'message-1',
    );
  });

  it('keeps retry state when deletion fails', async () => {
    deleteMessageMock.mockRejectedValue(new Error('offline'));
    const hook = renderMutations();

    await act(async () => {
      await hook.result.current.handleDeleteMessage(message);
    });

    expect(hook.removeMessage).not.toHaveBeenCalled();
    expect(hook.clearRetryableTurn).not.toHaveBeenCalled();
    expect(hook.clearPendingResponseTurn).not.toHaveBeenCalled();
    expect(toastErrorMock).toHaveBeenCalledWith(
      'chat.context.deleteFailed',
    );
  });

  it('keeps retry state when deletion is reported as incomplete', async () => {
    deleteMessageMock.mockResolvedValue({
      success: false,
      user_id: 'local_user',
      session_id: 'session-1',
      deleted_message_id: 'message-1',
      cleanup_pending: false,
    });
    const hook = renderMutations();

    await act(async () => {
      await hook.result.current.handleDeleteMessage(message);
    });

    expect(hook.removeMessage).not.toHaveBeenCalled();
    expect(hook.clearRetryableTurn).not.toHaveBeenCalled();
    expect(hook.clearPendingResponseTurn).not.toHaveBeenCalled();
    expect(toastErrorMock).toHaveBeenCalledWith(
      'chat.context.deleteFailed',
    );
  });

  it('removes the message and warns when private cleanup will retry', async () => {
    deleteMessageMock.mockResolvedValue({
      success: true,
      user_id: 'local_user',
      session_id: 'session-1',
      deleted_message_id: 'message-1',
      cleanup_pending: true,
    });
    const hook = renderMutations();

    await act(async () => {
      await hook.result.current.handleDeleteMessage(message);
    });

    expect(hook.removeMessage).toHaveBeenCalledWith('session-1', 'message-1');
    expect(toastWarningMock).toHaveBeenCalledWith(
      'chat.context.deleteCleanupPending',
    );
    expect(toastErrorMock).not.toHaveBeenCalled();
  });
});
