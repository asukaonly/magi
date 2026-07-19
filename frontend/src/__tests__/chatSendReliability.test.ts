import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { UserMessageRequest } from '@/api';
import type { AskStateDTO } from '@/api/modules/control';
import { sendChatMessageReliably } from '@/hooks/chatSendReliability';

const {
  getAskStateMock,
  getHistoryMock,
  sendMessageMock,
} = vi.hoisted(() => ({
  getAskStateMock: vi.fn(),
  getHistoryMock: vi.fn(),
  sendMessageMock: vi.fn(),
}));

vi.mock('@/api', () => ({
  messagesApi: {
    getHistory: getHistoryMock,
    sendMessage: sendMessageMock,
  },
}));

vi.mock('@/api/modules/control', () => ({
  getAskState: getAskStateMock,
}));

const SESSION_ID = 'session-1';
const REQUEST_ID = 'ask-old';
const ANSWER = 'Old answer';
const request: UserMessageRequest = {
  user_id: 'local_user',
  session_id: SESSION_ID,
  message: ANSWER,
  client_turn_id: 'turn-old-answer',
  metadata: {
    ask_request_id: REQUEST_ID,
  },
};
const confirmation = {
  kind: 'ask_response' as const,
  sessionId: SESSION_ID,
  requestId: REQUEST_ID,
  answer: ANSWER,
};

const askState = (
  overrides: Partial<AskStateDTO> = {},
): AskStateDTO => ({
  request_id: REQUEST_ID,
  question: 'Choose',
  options: [],
  allow_free_text: true,
  status: 'pending',
  answer: null,
  created_at_ms: Date.now(),
  timeout_seconds: 60,
  expires_at_ms: Date.now() + 60_000,
  ...overrides,
});

describe('chat send reliability', () => {
  beforeEach(() => {
    getHistoryMock.mockReset().mockResolvedValue({
      user_id: 'local_user',
      session_id: SESSION_ID,
      messages: [],
      count: 0,
    });
    getAskStateMock.mockReset().mockResolvedValue(askState());
    sendMessageMock.mockReset().mockResolvedValue({
      success: true,
      message: 'ok',
      data: { session_id: SESSION_ID },
    });
  });

  it('retries the same stable ask request while the ask is still pending', async () => {
    await expect(sendChatMessageReliably({
      request,
      confirmation,
      fallbackMessage: 'failed',
      preflight: true,
    })).resolves.toEqual({
      kind: 'accepted',
      responseSessionId: SESSION_ID,
    });

    expect(sendMessageMock).toHaveBeenCalledTimes(1);
    expect(sendMessageMock).toHaveBeenCalledWith(request);
  });

  it('accepts an already answered ask only when the answer matches', async () => {
    getAskStateMock.mockResolvedValue(askState({
      status: 'answered',
      answer: ANSWER,
    }));

    await expect(sendChatMessageReliably({
      request,
      confirmation,
      fallbackMessage: 'failed',
      preflight: true,
    })).resolves.toEqual({
      kind: 'accepted',
      responseSessionId: SESSION_ID,
    });
    expect(sendMessageMock).not.toHaveBeenCalled();
  });

  it.each([
    ['missing', null],
    ['replaced', askState({ request_id: 'ask-new' })],
    ['timed out', askState({ status: 'timeout' })],
    ['cancelled', askState({ status: 'cancelled' })],
    ['answered differently', askState({
      status: 'answered',
      answer: 'Different answer',
    })],
  ])('concludes an old ask when it is %s', async (_label, state) => {
    getAskStateMock.mockResolvedValue(state);

    await expect(sendChatMessageReliably({
      request,
      confirmation,
      fallbackMessage: 'failed',
      preflight: true,
    })).resolves.toEqual({ kind: 'concluded' });
    expect(sendMessageMock).not.toHaveBeenCalled();
  });

  it('keeps the old ask blocked when its state endpoint is unavailable', async () => {
    getAskStateMock.mockRejectedValue(new Error('offline'));

    await expect(sendChatMessageReliably({
      request,
      confirmation,
      fallbackMessage: 'failed',
      preflight: true,
    })).resolves.toEqual({ kind: 'unconfirmed' });
    expect(sendMessageMock).not.toHaveBeenCalled();
  });
});
