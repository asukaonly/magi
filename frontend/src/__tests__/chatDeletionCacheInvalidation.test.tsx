import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { messagesApi } from '@/api';
import { parseConversationHistory, parseSessionList } from '@/api/event-contract';
import type { ConversationHistory } from '@/api/modules/messages';
import { DEFAULT_USER_ID } from '@/constants';
import { normalizeHistoryMessages } from '@/domain/chat/state';
import { captureChatHistoryGuard, isChatHistoryGuardCurrent } from '@/hooks/chatRetryInvalidation';
import { useChatMessageMutations } from '@/hooks/useChatMessageMutations';
import { resetRealtimeChatProjectionRetirementForTests } from '@/realtime/chat-projection-retirement';
import { applyRealtimeStoreProjection } from '@/realtime/store-projection';
import {
  cachedChatHistory, cachedChatSessions, refreshChatHistory, refreshChatSessions, resetChatReadMemory,
} from '@/runtime/chat-read-cache';
import { centerLocalStorage, setCenterStorageScope } from '@/runtime/center-storage';
import { useConversationStore } from '@/stores/conversation-store';
import fixtures from '../../../contracts/api/frontend-events-examples.json';

vi.mock('@/api', () => ({ messagesApi: {
  getHistory: vi.fn(), listSessions: vi.fn(), deleteMessage: vi.fn(), labelMessage: vi.fn(),
} }));
vi.mock('sonner', () => ({ toast: { error: vi.fn(), warning: vi.fn() } }));

const CACHE_KEY = 'magi.chat.read-cache.v1';
const sessionId = 'deleted-message-session';
const messageId = 'private-deleted-message';
const confirmedDelete = {
  success: true, user_id: DEFAULT_USER_ID, session_id: sessionId,
  deleted_message_id: messageId, cleanup_pending: false,
};

function history(owner = sessionId): ConversationHistory {
  return parseConversationHistory({
    ...fixtures.historyPage, user_id: DEFAULT_USER_ID, session_id: owner,
    messages: [{ ...fixtures.message, message_id: messageId, turn_id: null, content: messageId }], count: 1,
  });
}

async function seedSnapshots(): Promise<void> {
  vi.mocked(messagesApi.getHistory).mockResolvedValue(history());
  await refreshChatHistory(sessionId);
  vi.mocked(messagesApi.listSessions).mockResolvedValue(parseSessionList({
    ...fixtures.sessionPage, user_id: DEFAULT_USER_ID,
    sessions: [{ ...fixtures.session, session_id: sessionId }], count: 1,
  }));
  await refreshChatSessions();
  expect(cachedChatHistory(sessionId)?.data.messages).toHaveLength(1);
  expect(cachedChatSessions()?.data.sessions).toHaveLength(1);
}

function beginOldHistoryRead() {
  let resolve!: (value: ConversationHistory) => void;
  vi.mocked(messagesApi.getHistory).mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
  const read = refreshChatHistory(sessionId);
  const rejection = expect(read).rejects.toMatchObject({ name: 'AbortError' });
  return async () => { resolve(history()); await rejection; };
}

function expectSnapshotsErased(): void {
  expect(cachedChatHistory(sessionId)).toBeUndefined();
  expect(cachedChatSessions()).toBeUndefined();
  expect(centerLocalStorage().getItem(CACHE_KEY)).not.toContain(messageId);
  resetChatReadMemory();
  expect(cachedChatHistory(sessionId)).toBeUndefined();
}

function renderMutations() {
  return renderHook(() => useChatMessageMutations({
    currentSessionId: sessionId, activeLabelMessageId: null,
    applyMessageLabel: vi.fn(), removeMessage: vi.fn(), clearRetryableTurn: vi.fn(),
    clearPendingResponseTurn: vi.fn(), clearComposerReferenceToMessage: vi.fn(),
    closeLabelPopover: vi.fn(), closeMessageContextMenu: vi.fn(),
    normalizeCopyText: (value) => value, translate: (key) => key,
  }));
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  resetChatReadMemory();
  setCenterStorageScope('message-deletion-center', 'epoch-1');
  resetRealtimeChatProjectionRetirementForTests();
  useConversationStore.getState().reset();
  vi.mocked(messagesApi.deleteMessage).mockResolvedValue(confirmedDelete);
});

afterEach(() => { resetChatReadMemory(); resetRealtimeChatProjectionRetirementForTests(); });

describe('message deletion snapshot ownership', () => {
  it.each([undefined, 'turn-1'])('erases confirmed deletion with turn %s and rejects a late history response', async (turnId) => {
    await seedSnapshots();
    const historyGuard = captureChatHistoryGuard(sessionId);
    const settleOldRead = beginOldHistoryRead();
    const hook = renderMutations();

    await act(async () => {
      await hook.result.current.handleDeleteMessage({ ...normalizeHistoryMessages(history().messages)[0], turnId });
    });

    await settleOldRead();
    expect(isChatHistoryGuardCurrent(historyGuard)).toBe(false);
    expectSnapshotsErased();
  });

  it.each([
    { ...confirmedDelete, success: false },
    { ...confirmedDelete, session_id: 'another-session' },
    { ...confirmedDelete, deleted_message_id: 'another-message' },
  ])('retains snapshots if the deletion is not confirmed for its exact owner', async (response) => {
    await seedSnapshots();
    const historyGuard = captureChatHistoryGuard(sessionId);
    vi.mocked(messagesApi.deleteMessage).mockResolvedValue(response);
    const hook = renderMutations();

    await act(async () => {
      await hook.result.current.handleDeleteMessage(normalizeHistoryMessages(history().messages)[0]);
    });

    expect(isChatHistoryGuardCurrent(historyGuard)).toBe(true);
    resetChatReadMemory();
    expect(cachedChatHistory(sessionId)?.data.messages[0].message_id).toBe(messageId);
  });

  it('erases a remote hidden message from disk and rejects its older response', async () => {
    await seedSnapshots();
    const historyGuard = captureChatHistoryGuard(sessionId);
    const settleOldRead = beginOldHistoryRead();
    useConversationStore.getState().upsertMessage(sessionId, normalizeHistoryMessages(history().messages)[0]);

    expect(applyRealtimeStoreProjection({ event: 'chat_message_hidden', data: {
      session_id: sessionId, message_id: messageId,
    } })).toBe(true);

    expect(useConversationStore.getState().messagesBySession[sessionId]).toEqual([]);
    await settleOldRead();
    expect(isChatHistoryGuardCurrent(historyGuard)).toBe(false);
    expectSnapshotsErased();
  });

  it('retains snapshots when a remote hidden event has a mismatched session summary', async () => {
    await seedSnapshots();
    const historyGuard = captureChatHistoryGuard(sessionId);

    expect(applyRealtimeStoreProjection({ event: 'chat_message_hidden', data: {
      session_id: sessionId, message_id: messageId,
      session_summary: { ...fixtures.session, session_id: 'another-session' },
    } })).toBe(false);

    expect(isChatHistoryGuardCurrent(historyGuard)).toBe(true);
    resetChatReadMemory();
    expect(cachedChatHistory(sessionId)?.data.messages[0].message_id).toBe(messageId);
  });
});
