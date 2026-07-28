import {
  afterAll,
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from 'vitest';

import type { ClearMemoryResponse } from '@/api/modules/memory';
import { CHAT_SESSION_KEY, DEFAULT_USER_ID } from '@/constants';
import { APP_EVENTS } from '@/constants/events';
import { clearAllMemory } from '@/hooks/clearAllMemory';
import {
  completeChatSessionDeletion,
} from '@/hooks/chatRetryLifecycle';
import {
  CHAT_RETRYABLE_SEND_STORAGE_KEY,
  INLINE_SKILL_RETRY_STORAGE_KEY,
  loadRetryableChatSends,
  loadRetryableInlineSkillOperations,
  saveRetryableChatSends,
  saveRetryableInlineSkillOperations,
  type RetryableChatSendOperation,
  type RetryableInlineSkillOperation,
} from '@/hooks/chatRetryableSendStorage';
import { useConversationStore } from '@/stores/conversation-store';

const { clearAllMock, listNotificationsMock } = vi.hoisted(() => ({
  clearAllMock: vi.fn(),
  listNotificationsMock: vi.fn(),
}));
const xhrOpenSpy = vi.spyOn(XMLHttpRequest.prototype, 'open');

vi.mock('@/api/modules/memory', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/modules/memory')>();
  return {
    ...actual,
    memoryApi: {
      ...actual.memoryApi,
      clearAll: clearAllMock,
    },
    default: {
      ...actual.default,
      clearAll: clearAllMock,
    },
  };
});

vi.mock('@/api/modules/notifications', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/modules/notifications')>();
  return {
    ...actual,
    listNotifications: listNotificationsMock,
  };
});

const buildComposerOperation = (
  sessionId: string,
  turnId: string,
): RetryableChatSendOperation => ({
  sessionId,
  turnId,
  createdAtMs: Date.now(),
  draftIdentity: `identity:${turnId}`,
  draftSignature: `signature:${turnId}`,
  draftKind: 'normal',
  request: {
    user_id: DEFAULT_USER_ID,
    session_id: sessionId,
    message: `message:${turnId}`,
    client_turn_id: turnId,
  },
  confirmation: {
    kind: 'turn',
    sessionId,
    turnId,
  },
  pendingTurn: {
    sessionId,
    input: `message:${turnId}`,
    turnId,
    timestamp: Date.now(),
    pendingLabel: 'Pending',
  },
});

const buildInlineOperation = (
  sessionId: string,
  turnId: string,
): RetryableInlineSkillOperation => ({
  retryKey: JSON.stringify([sessionId, null, 'summarize', [turnId]]),
  createdAtMs: Date.now(),
  request: {
    user_id: DEFAULT_USER_ID,
    session_id: sessionId,
    message: `/summarize ${turnId}\n\nExpanded prompt`,
    workspace_path: null,
    client_turn_id: turnId,
  },
  confirmation: {
    kind: 'turn',
    sessionId,
    turnId,
  },
});

const seedRetryState = () => {
  const targetComposer = buildComposerOperation('session-a', 'turn-a');
  const otherComposer = buildComposerOperation('session-b', 'turn-b');
  const targetInline = buildInlineOperation('session-a', 'skill-turn-a');
  const otherInline = buildInlineOperation('session-b', 'skill-turn-b');
  saveRetryableChatSends(new Map([
    [targetComposer.sessionId, targetComposer],
    [otherComposer.sessionId, otherComposer],
  ]));
  saveRetryableInlineSkillOperations(new Map([
    [targetInline.retryKey, targetInline],
    [otherInline.retryKey, otherInline],
  ]));
};

const successfulClearResponse = (): ClearMemoryResponse => ({
  success: true,
  results: {
    l0: { cleared: true, count: 1 },
    l1: { cleared: true, count: 2 },
    l2: { cleared: true, count: 3 },
    l3: { cleared: true, count: 4 },
    l4: { cleared: true, count: 5 },
    chat_context: { cleared: true, count: 6 },
  },
});

describe('chat retry lifecycle', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    window.localStorage.clear();
    useConversationStore.getState().reset();
    clearAllMock.mockReset();
    listNotificationsMock.mockReset().mockResolvedValue({
      items: [],
      unread_count: 0,
    });
    xhrOpenSpy.mockClear();
  });

  afterEach(() => {
    expect(xhrOpenSpy).not.toHaveBeenCalled();
  });

  afterAll(() => {
    xhrOpenSpy.mockRestore();
  });

  it('clears only the deleted session and announces it after durable success', () => {
    seedRetryState();
    useConversationStore.getState().receiveHistory('session-a', [{
      id: 'message-a',
      messageId: 'message-a',
      role: 'user',
      kind: 'user',
      content: 'Old message',
      timestamp: Date.now(),
      turnId: 'turn-a',
      traceAvailable: false,
    }]);
    const listener = vi.fn();
    window.addEventListener(APP_EVENTS.CHAT_SESSION_DELETED, listener);

    completeChatSessionDeletion('session-a');

    expect(loadRetryableChatSends().has('session-a')).toBe(false);
    expect(loadRetryableChatSends().has('session-b')).toBe(true);
    expect([...loadRetryableInlineSkillOperations().values()].some(
      (operation) => operation.request.session_id === 'session-a',
    )).toBe(false);
    expect([...loadRetryableInlineSkillOperations().values()].some(
      (operation) => operation.request.session_id === 'session-b',
    )).toBe(true);
    expect(useConversationStore.getState().messagesBySession['session-a']).toEqual([]);
    expect(listener).toHaveBeenCalledTimes(1);
    expect((listener.mock.calls[0][0] as CustomEvent).detail).toEqual({
      sessionId: 'session-a',
    });
    window.removeEventListener(APP_EVENTS.CHAT_SESSION_DELETED, listener);
  });

  it('clears persisted retries and cached sessions before announcing a successful full clear', async () => {
    seedRetryState();
    useConversationStore.getState().setCurrentSessionId('session-a');
    useConversationStore.getState().receiveHistory('session-a', [{
      id: 'message-a',
      messageId: 'message-a',
      role: 'user',
      kind: 'user',
      content: 'Old message',
      timestamp: Date.now(),
      turnId: 'turn-a',
      traceAvailable: false,
    }]);
    window.localStorage.setItem(
      CHAT_SESSION_KEY(DEFAULT_USER_ID),
      'session-a',
    );
    clearAllMock.mockResolvedValue(successfulClearResponse());
    const listener = vi.fn();
    window.addEventListener(APP_EVENTS.MEMORY_CLEARED, listener);

    const result = await clearAllMemory();

    expect(result.success).toBe(true);
    expect(window.sessionStorage.getItem(
      CHAT_RETRYABLE_SEND_STORAGE_KEY,
    )).toBeNull();
    expect(window.sessionStorage.getItem(
      INLINE_SKILL_RETRY_STORAGE_KEY,
    )).toBeNull();
    expect(useConversationStore.getState().currentSessionId).toBeNull();
    expect(useConversationStore.getState().orderedSessionIds).toEqual([]);
    expect(useConversationStore.getState().messagesBySession).toEqual({});
    expect(window.localStorage.getItem(
      CHAT_SESSION_KEY(DEFAULT_USER_ID),
    )).toBeNull();
    expect(listNotificationsMock).toHaveBeenCalledTimes(1);
    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener(APP_EVENTS.MEMORY_CLEARED, listener);
  });

  it.each([
    {
      name: 'the backend rejects the request',
      arrange: () => clearAllMock.mockRejectedValue(new Error('offline')),
    },
    {
      name: 'the backend reports an incomplete clear',
      arrange: () => clearAllMock.mockResolvedValue({
        ...successfulClearResponse(),
        success: false,
      }),
    },
  ])('keeps every local state unchanged when $name', async ({ arrange }) => {
    seedRetryState();
    useConversationStore.getState().setCurrentSessionId('session-a');
    window.localStorage.setItem(
      CHAT_SESSION_KEY(DEFAULT_USER_ID),
      'session-a',
    );
    arrange();
    const listener = vi.fn();
    window.addEventListener(APP_EVENTS.MEMORY_CLEARED, listener);

    await expect(clearAllMemory()).rejects.toThrow();

    expect(window.sessionStorage.getItem(
      CHAT_RETRYABLE_SEND_STORAGE_KEY,
    )).not.toBeNull();
    expect(window.sessionStorage.getItem(
      INLINE_SKILL_RETRY_STORAGE_KEY,
    )).not.toBeNull();
    expect(useConversationStore.getState().currentSessionId).toBe('session-a');
    expect(window.localStorage.getItem(
      CHAT_SESSION_KEY(DEFAULT_USER_ID),
    )).toBe('session-a');
    expect(listener).not.toHaveBeenCalled();
    window.removeEventListener(APP_EVENTS.MEMORY_CLEARED, listener);
  });
});
