import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { UserMessageRequest } from '@/api';
import { sendChatMessageReliably } from '@/hooks/chatSendReliability';

const {
  confirmSendMock,
  getTurnSnapshotMock,
  sendMessageMock,
} = vi.hoisted(() => ({
  confirmSendMock: vi.fn(),
  getTurnSnapshotMock: vi.fn(),
  sendMessageMock: vi.fn(),
}));

vi.mock('@/api', () => ({
  messagesApi: {
    getTurnSnapshot: getTurnSnapshotMock,
    confirmSend: confirmSendMock,
    sendMessage: sendMessageMock,
  },
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

describe('chat send reliability', () => {
  beforeEach(() => {
    getTurnSnapshotMock.mockReset();
    confirmSendMock.mockReset().mockResolvedValue({ status: 'absent', safe_to_retry: true });
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
    confirmSendMock.mockResolvedValue({ status: 'confirmed', safe_to_retry: false });

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

  it('concludes a request that the server retired or answered differently', async () => {
    confirmSendMock.mockResolvedValue({ status: 'concluded', safe_to_retry: false });

    await expect(sendChatMessageReliably({
      request,
      confirmation,
      fallbackMessage: 'failed',
      preflight: true,
    })).resolves.toEqual({ kind: 'concluded' });
    expect(sendMessageMock).not.toHaveBeenCalled();
  });

  it('keeps the old ask blocked when its state endpoint is unavailable', async () => {
    confirmSendMock.mockRejectedValue(new Error('offline'));

    await expect(sendChatMessageReliably({
      request,
      confirmation,
      fallbackMessage: 'failed',
      preflight: true,
    })).resolves.toEqual({ kind: 'unconfirmed' });
    expect(sendMessageMock).not.toHaveBeenCalled();
  });
});
