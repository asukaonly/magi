import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  CHAT_RETRYABLE_SEND_STORAGE_KEY,
  loadRetryableChatSends,
  saveRetryableChatSends,
  type RetryableChatSendOperation,
} from '@/hooks/chatRetryableSendStorage';
import { useChatSendMessage } from '@/hooks/useChatSendMessage';
import { useConversationStore } from '@/stores/conversation-store';

const {
  getAskStateMock,
  getHistoryMock,
  sendMessageMock,
  toastWarningMock,
} = vi.hoisted(() => ({
  getAskStateMock: vi.fn(),
  getHistoryMock: vi.fn(),
  sendMessageMock: vi.fn(),
  toastWarningMock: vi.fn(),
}));

vi.mock('@/api', () => ({
  messagesApi: {
    getHistory: getHistoryMock,
    sendMessage: sendMessageMock,
    uploadAttachment: vi.fn(),
  },
}));

vi.mock('@/api/modules/control', () => ({
  getAskState: getAskStateMock,
}));

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
    warning: toastWarningMock,
  },
}));

const SESSION_ID = 'session-1';
const OLD_REQUEST_ID = 'ask-old';
const OLD_TURN_ID = 'turn-old';

const oldAskOperation = (): RetryableChatSendOperation => ({
  sessionId: SESSION_ID,
  turnId: OLD_TURN_ID,
  createdAtMs: Date.now(),
  draftIdentity: 'old-identity',
  draftSignature: 'old-signature',
  draftKind: 'pending_ask',
  request: {
    user_id: 'local_user',
    session_id: SESSION_ID,
    message: 'Old answer',
    workspace_path: null,
    client_turn_id: OLD_TURN_ID,
    metadata: {
      ask_request_id: OLD_REQUEST_ID,
    },
  },
  confirmation: {
    kind: 'ask_response',
    sessionId: SESSION_ID,
    requestId: OLD_REQUEST_ID,
    answer: 'Old answer',
  },
  askAnswer: {
    requestId: OLD_REQUEST_ID,
    sessionId: SESSION_ID,
    messageId: 'ask-message-old',
    question: 'Old question',
    options: [],
    allowFreeText: true,
    expiresAtMs: Date.now() + 60_000,
    answer: 'Old answer',
    timestamp: Date.now(),
  },
});

const oldNormalOperation = (): RetryableChatSendOperation => ({
  sessionId: SESSION_ID,
  turnId: OLD_TURN_ID,
  createdAtMs: Date.now(),
  draftIdentity: 'old-normal-identity',
  draftSignature: 'old-normal-signature',
  draftKind: 'normal',
  request: {
    user_id: 'local_user',
    session_id: SESSION_ID,
    message: 'Message sent before refresh',
    workspace_path: null,
    client_turn_id: OLD_TURN_ID,
    attachments: [],
  },
  confirmation: {
    kind: 'turn',
    sessionId: SESSION_ID,
    turnId: OLD_TURN_ID,
  },
  pendingTurn: {
    sessionId: SESSION_ID,
    input: 'Message sent before refresh',
    turnId: OLD_TURN_ID,
    timestamp: Date.now(),
    pendingLabel: 'pending',
    attachments: [],
    replyTo: null,
  },
});

const pendingAskState = (requestId = OLD_REQUEST_ID) => ({
  request_id: requestId,
  question: 'Question',
  options: [],
  allow_free_text: true,
  status: 'pending' as const,
  answer: null,
  created_at_ms: Date.now(),
  timeout_seconds: 60,
  expires_at_ms: Date.now() + 60_000,
});

const createDeferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
};

const renderSendHook = ({
  inputValue,
  pendingAsk = null,
}: {
  inputValue: string;
  pendingAsk?: {
    requestId: string;
    sessionId: string;
    messageId: string | null;
    question: string;
    options: string[];
    allowFreeText: boolean;
    expiresAtMs: number | null;
  } | null;
}) => {
  const appendPendingTurn = vi.fn();
  const clearComposerDraftIfUnchanged = vi.fn();
  const onAskAnswered = vi.fn();
  const onPendingResponseFailure = vi.fn();
  const onPendingResponseTurn = vi.fn();
  const removePendingMessage = vi.fn();
  const result = renderHook(() => useChatSendMessage({
    currentSessionId: SESSION_ID,
    currentWorkspacePath: null,
    inputValue,
    draftAttachments: [],
    replyTarget: null,
    allowInterjection: true,
    pendingAsk,
    recallFeedbackDraft: null,
    reasoningPreference: 'auto',
    appendPendingTurn,
    removePendingMessage,
    setCurrentSessionId: vi.fn(),
    getCurrentSessionId: () => SESSION_ID,
    composerDraftIdentity: 'current-identity',
    composerDraftSignature: 'current-signature',
    clearComposerDraftIfUnchanged,
    onPendingResponseTurn,
    onPendingResponseFailure,
    onAskAnswered,
    reconcileExternalTurnBeforeSend: async () => ({ kind: 'ready' }),
    runWithTurnAdmission: async (_sessionId, _kind, operation) => ({
      entered: true,
      value: await operation(),
    }),
    translate: (key) => key,
  }));
  return {
    ...result,
    appendPendingTurn,
    clearComposerDraftIfUnchanged,
    onAskAnswered,
    onPendingResponseFailure,
    onPendingResponseTurn,
    removePendingMessage,
  };
};

describe('useChatSendMessage', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    useConversationStore.getState().reset();
    useConversationStore.getState().setCurrentSessionId(SESSION_ID);
    getHistoryMock.mockReset().mockResolvedValue({
      user_id: 'local_user',
      session_id: SESSION_ID,
      messages: [],
      count: 0,
    });
    getAskStateMock.mockReset().mockResolvedValue(null);
    sendMessageMock.mockReset().mockResolvedValue({
      success: true,
      message: 'ok',
      data: { session_id: SESSION_ID },
    });
    toastWarningMock.mockReset();
  });

  it('concludes a replaced old ask and sends the current ordinary draft', async () => {
    const oldOperation = oldAskOperation();
    saveRetryableChatSends(new Map([[SESSION_ID, oldOperation]]));
    getAskStateMock.mockResolvedValue(pendingAskState('ask-new'));
    const hook = renderSendHook({ inputValue: 'Current message' });

    await act(async () => {
      await hook.result.current.handleSendMessage();
    });

    expect(sendMessageMock).toHaveBeenCalledTimes(1);
    expect(sendMessageMock).toHaveBeenCalledWith(expect.objectContaining({
      message: 'Current message',
      session_id: SESSION_ID,
    }));
    expect(sendMessageMock).not.toHaveBeenCalledWith(expect.objectContaining({
      client_turn_id: OLD_TURN_ID,
    }));
    expect(hook.clearComposerDraftIfUnchanged).toHaveBeenCalledWith(
      'current-identity',
      'normal',
    );
    expect(window.sessionStorage.getItem(
      CHAT_RETRYABLE_SEND_STORAGE_KEY,
    )).toBeNull();
  });

  it('concludes a cancelled old ask and sends the current new ask answer', async () => {
    const oldOperation = oldAskOperation();
    saveRetryableChatSends(new Map([[SESSION_ID, oldOperation]]));
    getAskStateMock.mockResolvedValue({
      ...pendingAskState(),
      status: 'cancelled',
    });
    const hook = renderSendHook({
      inputValue: 'New answer',
      pendingAsk: {
        requestId: 'ask-new',
        sessionId: SESSION_ID,
        messageId: 'ask-message-new',
        question: 'New question',
        options: [],
        allowFreeText: true,
        expiresAtMs: Date.now() + 60_000,
      },
    });

    await act(async () => {
      await hook.result.current.handleSendMessage();
    });

    expect(sendMessageMock).toHaveBeenCalledTimes(1);
    expect(sendMessageMock).toHaveBeenCalledWith(expect.objectContaining({
      message: 'New answer',
      metadata: { ask_request_id: 'ask-new' },
    }));
    expect(hook.onAskAnswered).toHaveBeenCalledWith(expect.objectContaining({
      requestId: 'ask-new',
      answer: 'New answer',
    }));
    expect(window.sessionStorage.getItem(
      CHAT_RETRYABLE_SEND_STORAGE_KEY,
    )).toBeNull();
  });

  it('keeps the current draft blocked when the old ask endpoint is unavailable', async () => {
    const oldOperation = oldAskOperation();
    saveRetryableChatSends(new Map([[SESSION_ID, oldOperation]]));
    getAskStateMock.mockRejectedValue(new Error('offline'));
    const hook = renderSendHook({ inputValue: 'Do not send yet' });

    await act(async () => {
      await hook.result.current.handleSendMessage();
    });

    expect(sendMessageMock).not.toHaveBeenCalled();
    expect(hook.clearComposerDraftIfUnchanged).not.toHaveBeenCalled();
    expect(toastWarningMock).toHaveBeenCalledWith(
      'chat.previousSendUnconfirmed',
    );
    expect(window.sessionStorage.getItem(
      CHAT_RETRYABLE_SEND_STORAGE_KEY,
    )).not.toBeNull();
  });

  it('retries the old stable ask while it is still pending and preserves the new draft', async () => {
    const oldOperation = oldAskOperation();
    saveRetryableChatSends(new Map([[SESSION_ID, oldOperation]]));
    getAskStateMock.mockResolvedValue(pendingAskState());
    const hook = renderSendHook({ inputValue: 'Keep this new draft' });

    await act(async () => {
      await hook.result.current.handleSendMessage();
    });

    expect(sendMessageMock).toHaveBeenCalledTimes(1);
    expect(sendMessageMock).toHaveBeenCalledWith(oldOperation.request);
    expect(hook.clearComposerDraftIfUnchanged).not.toHaveBeenCalled();
    expect(hook.onAskAnswered).toHaveBeenCalledWith(oldOperation.askAnswer);
  });

  it('reconciles a restored ordinary send before rejecting an empty draft', async () => {
    const oldOperation = oldNormalOperation();
    saveRetryableChatSends(new Map([[SESSION_ID, oldOperation]]));
    getHistoryMock.mockResolvedValue({
      user_id: 'local_user',
      session_id: SESSION_ID,
      messages: [{
        message_id: 'old-user-message',
        message_kind: 'user_text',
        role: 'user',
        content: oldOperation.request.message,
        timestamp: Date.now() / 1000,
        turn_id: OLD_TURN_ID,
        kind: 'user',
      }],
      count: 1,
    });
    const hook = renderSendHook({ inputValue: '' });

    await act(async () => {
      await hook.result.current.handleSendMessage();
    });

    expect(getHistoryMock).toHaveBeenCalledWith(
      'local_user',
      SESSION_ID,
    );
    expect(sendMessageMock).not.toHaveBeenCalled();
    expect(window.sessionStorage.getItem(
      CHAT_RETRYABLE_SEND_STORAGE_KEY,
    )).toBeNull();
    expect(toastWarningMock).toHaveBeenCalledWith(
      'chat.restoredSendResolved',
    );
    expect(toastWarningMock).not.toHaveBeenCalledWith('chat.emptyInput');
  });

  it('clears only a matching exact retry turn', () => {
    const oldOperation = oldAskOperation();
    saveRetryableChatSends(new Map([[SESSION_ID, oldOperation]]));
    const hook = renderSendHook({ inputValue: 'Draft' });

    act(() => {
      hook.result.current.clearRetryableSendForTurn(
        SESSION_ID,
        'different-turn',
      );
    });
    expect(window.sessionStorage.getItem(
      CHAT_RETRYABLE_SEND_STORAGE_KEY,
    )).not.toBeNull();

    act(() => {
      hook.result.current.clearRetryableSendForTurn(
        SESSION_ID,
        OLD_TURN_ID,
      );
    });
    expect(window.sessionStorage.getItem(
      CHAT_RETRYABLE_SEND_STORAGE_KEY,
    )).toBeNull();
  });

  it.each([
    {
      name: 'an exact message deletion',
      clear: (hook: ReturnType<typeof renderSendHook>, turnId: string) => {
        hook.result.current.clearRetryableSendForTurn(SESSION_ID, turnId);
      },
    },
    {
      name: 'a session or history deletion',
      clear: (hook: ReturnType<typeof renderSendHook>) => {
        hook.result.current.clearRetryableSendsForSession(SESSION_ID);
      },
    },
    {
      name: 'a full memory clear',
      clear: (hook: ReturnType<typeof renderSendHook>) => {
        hook.result.current.clearAllRetryableSends();
      },
    },
  ])('does not restore a retry after $name while its request is still in flight', async ({ clear }) => {
    const firstAttempt = createDeferred<never>();
    sendMessageMock
      .mockImplementationOnce(() => firstAttempt.promise)
      .mockRejectedValue(new Error('offline'));
    const hook = renderSendHook({ inputValue: 'Delete while sending' });
    let sendPromise!: Promise<void>;

    act(() => {
      sendPromise = hook.result.current.handleSendMessage();
    });

    await waitFor(() => {
      expect(window.sessionStorage.getItem(
        CHAT_RETRYABLE_SEND_STORAGE_KEY,
      )).not.toBeNull();
    });
    const operation = loadRetryableChatSends().get(SESSION_ID);
    expect(operation).toBeDefined();

    act(() => {
      clear(hook, operation!.turnId);
    });
    expect(window.sessionStorage.getItem(
      CHAT_RETRYABLE_SEND_STORAGE_KEY,
    )).toBeNull();

    await act(async () => {
      firstAttempt.reject(new Error('late network failure'));
      await sendPromise;
    });

    expect(window.sessionStorage.getItem(
      CHAT_RETRYABLE_SEND_STORAGE_KEY,
    )).toBeNull();
    expect(toastWarningMock).not.toHaveBeenCalledWith(
      'chat.sendUnconfirmed',
    );
  });
});
