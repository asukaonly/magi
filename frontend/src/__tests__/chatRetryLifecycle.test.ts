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
import { useBackgroundTaskStore } from '@/stores/background-tasks';
import { useChatShellStore } from '@/stores/chat-shell';
import { useNotificationStore } from '@/stores/notifications';

const {
  beginFullDataClearMock,
  clearAllMock,
  clearDesktopLogHistoryMock,
  completeFullDataClearMock,
  listNotificationsMock,
} = vi.hoisted(() => ({
  beginFullDataClearMock: vi.fn(),
  clearAllMock: vi.fn(),
  clearDesktopLogHistoryMock: vi.fn(),
  completeFullDataClearMock: vi.fn(),
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

vi.mock('@/runtime/desktop', () => ({
  beginFullDataClear: beginFullDataClearMock,
  clearDesktopLogHistory: clearDesktopLogHistoryMock,
  completeFullDataClear: completeFullDataClearMock,
  readPendingFullDataClear: vi.fn(),
}));

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
    useBackgroundTaskStore.getState().reset();
    useNotificationStore.setState({
      items: [],
      unreadCount: 0,
      loading: false,
    });
    clearAllMock.mockReset();
    beginFullDataClearMock.mockReset().mockResolvedValue({
      version: 1,
      transactionId: 'clear-chat-retry-test',
    });
    clearDesktopLogHistoryMock.mockReset().mockResolvedValue({
      clearedEntries: 2,
      failedEntries: 0,
    });
    completeFullDataClearMock.mockReset().mockResolvedValue(undefined);
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
    window.localStorage.setItem('magi_onboarding_state', JSON.stringify({
      version: 1,
      current: 2,
      values: { preferences: { language: 'zh' } },
      customPersonas: [{ description: 'private persona draft' }],
      personaCreationDraft: { description: 'private draft' },
      firstContextProgress: {
        draft: 'private answer',
        sessionId: 'session-a',
        turnId: 'turn-a',
      },
    }));
    window.localStorage.setItem(
      'magi.first-context-continuation:session-a',
      JSON.stringify({ version: 1, mode: 'dismissed' }),
    );
    window.localStorage.setItem(
      'magi.composer.mru.mentions',
      JSON.stringify(['filesystem|file:///private/report.txt']),
    );
    window.localStorage.setItem(
      'magi.chat.readCursors.v1',
      JSON.stringify({ 'session-a': { messageCount: 1, lastTimestamp: 1 } }),
    );
    window.localStorage.setItem('magi.chat.readCursors.initialized.v1', 'true');
    window.localStorage.setItem(
      'magi.desktopNotifications.sent.v1',
      JSON.stringify({ ids: ['message-a'] }),
    );
    window.localStorage.setItem(
      'magi.desktopNotifications.preferences.v1',
      JSON.stringify({ desktopNotificationsEnabled: true }),
    );
    window.localStorage.setItem('magi_language', 'zh');
    window.localStorage.setItem('magi-theme-mode', 'dark');
    window.localStorage.setItem('magi_onboarding_completed', 'true');
    useBackgroundTaskStore.getState().hydrate([{
      task_id: 'old-task',
      status: 'running',
      attempt_index: 0,
      spec: {
        user_id: DEFAULT_USER_ID,
        session_id: 'session-a',
        origin_turn_id: 'turn-a',
        title: 'Private task',
        goal: 'Private goal',
        selected_tools: [],
        workspace_path: null,
        trigger_source: 'user',
        priority: 0,
        max_iterations: 1,
        timeout_seconds: null,
      },
      orchestration_id: null,
      user_task_id: null,
      summary: null,
      result_payload: {},
      error: null,
      cancel_reason: null,
      created_at: 1,
      started_at: 1,
      finished_at: null,
      updated_at: 1,
    }], 1);
    useChatShellStore.getState().setTimelinePanel({
      draftQuery: 'private timeline draft',
      moodDays: [{
        date: '2026-07-01',
        dominant_valence: 'warm',
        volatility: 0.1,
        event_count: 1,
        sparkline: [0.5],
      }],
    });
    useNotificationStore.setState({
      items: [{
        id: 7,
        kind: 'suggestion',
        dedupe_key: 'private-suggestion',
        title: 'Private title',
        body: 'Private body',
        payload: { category: 'private payload' },
        status: 'unread',
        created_at_ms: 1,
        read_at_ms: null,
      }],
      unreadCount: 1,
      loading: true,
    });
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
    const onboarding = JSON.parse(
      window.localStorage.getItem('magi_onboarding_state') || '{}',
    );
    expect(onboarding.current).toBe(2);
    expect(onboarding.customPersonas).toEqual([]);
    expect(onboarding.personaCreationDraft).toBeNull();
    expect(onboarding.firstContextProgress).toMatchObject({
      draft: '',
      sessionId: null,
      turnId: null,
    });
    expect(window.localStorage.getItem(
      'magi.first-context-continuation:session-a',
    )).toBeNull();
    expect(window.localStorage.getItem('magi.composer.mru.mentions')).toBeNull();
    expect(window.localStorage.getItem('magi.chat.readCursors.v1')).toBeNull();
    expect(window.localStorage.getItem('magi.chat.readCursors.initialized.v1')).toBeNull();
    expect(window.localStorage.getItem('magi.desktopNotifications.sent.v1')).toBeNull();
    expect(window.localStorage.getItem('magi.desktopNotifications.preferences.v1')).not.toBeNull();
    expect(window.localStorage.getItem('magi_language')).toBe('zh');
    expect(window.localStorage.getItem('magi-theme-mode')).toBe('dark');
    expect(window.localStorage.getItem('magi_onboarding_completed')).toBe('true');
    expect(useBackgroundTaskStore.getState().orderedIds).toEqual([]);
    expect(useChatShellStore.getState().timelinePanel.draftQuery).toBe('');
    expect(useChatShellStore.getState().timelinePanel.moodDays).toEqual([]);
    expect(useNotificationStore.getState().items).toEqual([]);
    expect(useNotificationStore.getState().unreadCount).toBe(0);
    expect(useNotificationStore.getState().loading).toBe(false);
    expect(listNotificationsMock).not.toHaveBeenCalled();
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
