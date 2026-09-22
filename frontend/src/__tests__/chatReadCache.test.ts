import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { messagesApi } from '@/api';
import { parseConversationHistory, parseSessionList } from '@/api/event-contract';
import type { ConversationHistory, SessionListResponse } from '@/api/modules/messages';
import { DEFAULT_USER_ID } from '@/constants';
import { advanceBrowserContentGeneration } from '@/lib/browserContentGeneration';
import {
  cachedChatHistory, cachedChatSessions, CHAT_PAGE_SIZE, invalidateChatReadCache,
  pageCanLoadMore, refreshChatHistory, refreshChatSessions, resetChatReadMemory,
} from '@/runtime/chat-read-cache';
import { centerLocalStorage, centerStorageKey, setCenterStorageScope } from '@/runtime/center-storage';
import { resetRuntimeInitialization } from '@/runtime/config';
import fixtures from '../../../contracts/api/frontend-events-examples.json';

vi.mock('@/api', () => ({ messagesApi: { getHistory: vi.fn(), listSessions: vi.fn() } }));

const CACHE_KEY = 'magi.chat.read-cache.v1';
const NOW = 1_800_000_000_000;
const historyIds = (value: ConversationHistory | undefined) => value?.messages.map((message) => message.message_id);
const sessionIds = (value: SessionListResponse | undefined) => value?.sessions.map((session) => session.session_id);

function history(ids: string[], revision = 'r1', next: string | null = null, sessionId = 'chat'): ConversationHistory {
  return parseConversationHistory({
    ...fixtures.historyPage, user_id: DEFAULT_USER_ID, session_id: sessionId,
    revision, not_modified: false, has_more: Boolean(next), next_before: next,
    messages: ids.map((id, index) => ({ ...fixtures.message, message_id: id, content: id, timestamp: index + 1 })),
    count: ids.length,
  });
}

function sessionPage(ids: string[], revision = 'r1', next: string | null = null): SessionListResponse {
  return parseSessionList({
    ...fixtures.sessionPage, user_id: DEFAULT_USER_ID, revision,
    not_modified: false, has_more: Boolean(next), next_before: next,
    sessions: ids.map((id) => ({ ...fixtures.session, session_id: id })), count: ids.length,
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function saveHistory(data: unknown, checkedAt = NOW, sessionId = 'chat'): void {
  centerLocalStorage().setItem(CACHE_KEY, JSON.stringify({ version: 1, entries: [{
    key: centerStorageKey(`${CACHE_KEY}:${DEFAULT_USER_ID}:history:${sessionId}`), checkedAt, data,
  }] }));
}

beforeEach(() => {
  vi.mocked(messagesApi.getHistory).mockReset();
  vi.mocked(messagesApi.listSessions).mockReset();
  vi.spyOn(Date, 'now').mockReturnValue(NOW);
  window.localStorage.clear();
  window.sessionStorage.clear();
  resetRuntimeInitialization();
  setCenterStorageScope('center-a', 'epoch-1');
});

afterEach(() => { resetChatReadMemory(); vi.restoreAllMocks(); });

describe('validated persistent chat snapshots', () => {
  it('restores only the bounded head page as stale while retaining the loaded window in memory', async () => {
    vi.mocked(messagesApi.getHistory)
      .mockResolvedValueOnce(history(['newer'], 'r1', 'older-cursor'))
      .mockResolvedValueOnce(history(['older']));
    await refreshChatHistory('chat');
    const loaded = await refreshChatHistory('chat', true);
    expect(historyIds(loaded.data)).toEqual(['older', 'newer']);
    expect(loaded.stale).toBe(false);

    resetChatReadMemory();
    expect(cachedChatHistory('chat')).toMatchObject({ checkedAt: NOW, stale: true });
    expect(historyIds(cachedChatHistory('chat')?.data)).toEqual(['newer']);
    expect(pageCanLoadMore(cachedChatHistory('chat')?.data)).toBe(true);
  });

  it.each([
    ['invalid count', () => ({ ...history(['one']), count: 2 })],
    ['invalid message', () => ({ ...history(['one']), messages: [{ content: 'missing ownership fields' }] })],
    ['another user', () => ({ ...history(['one']), user_id: 'another-user' })],
    ['another conversation', () => history(['one'], 'r1', null, 'another-chat')],
    ['conditional response', () => ({ ...history([]), not_modified: true })],
  ] as const)('rejects persisted %s', (_label, data) => {
    saveHistory(data());
    expect(cachedChatHistory('chat')).toBeUndefined();
  });

  it.each([NOW - 8 * 24 * 60 * 60 * 1000, NOW + 1])('rejects expired or future timestamps: %i', (checkedAt) => {
    saveHistory(history(['old']), checkedAt);
    expect(cachedChatHistory('chat')).toBeUndefined();
  });

  it('keeps storage bounded and confirmed memory usable when a head exceeds the persistence budget', async () => {
    const huge = history(['large']);
    huge.messages[0].content = 'x'.repeat(600_000);
    vi.mocked(messagesApi.getHistory).mockResolvedValueOnce(huge);
    const result = await refreshChatHistory('chat');
    expect(result.data.messages[0].content).toHaveLength(600_000);
    expect((centerLocalStorage().getItem(CACHE_KEY)?.length ?? 0) * 2).toBeLessThanOrEqual(1_048_576);
    resetChatReadMemory();
    expect(cachedChatHistory('chat')).toBeUndefined();
  });

  it('evicts old persistent heads instead of growing with every visited conversation', async () => {
    for (let index = 0; index < 12; index += 1) {
      const id = `chat-${index}`;
      vi.mocked(messagesApi.getHistory).mockResolvedValueOnce(history([id], 'r1', null, id));
      await refreshChatHistory(id);
    }
    resetChatReadMemory();
    expect(cachedChatHistory('chat-0')).toBeUndefined();
    expect(historyIds(cachedChatHistory('chat-11')?.data)).toEqual(['chat-11']);
    expect(Array.from({ length: 12 }, (_, index) => cachedChatHistory(`chat-${index}`)).filter(Boolean).length).toBeLessThanOrEqual(9);
  });

  it('bounds in-memory conversation windows independently of the persistent budget', async () => {
    for (let index = 0; index < 25; index += 1) {
      const id = `chat-${index}`;
      vi.mocked(messagesApi.getHistory).mockResolvedValueOnce(history([id], 'r1', null, id));
      await refreshChatHistory(id);
    }
    expect(cachedChatHistory('chat-0')).toBeUndefined();
    expect(historyIds(cachedChatHistory('chat-24')?.data)).toEqual(['chat-24']);
    expect(Array.from({ length: 25 }, (_, index) => cachedChatHistory(`chat-${index}`)).filter(Boolean).length).toBeLessThanOrEqual(20);
  });

  it('keeps confirmed data usable when persistent storage rejects writes', async () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new DOMException('Quota exceeded', 'QuotaExceededError'); });
    vi.mocked(messagesApi.getHistory).mockResolvedValueOnce(history(['confirmed']));
    const confirmed = await refreshChatHistory('chat');
    expect(confirmed.stale).toBe(false);
    expect(historyIds(cachedChatHistory('chat')?.data)).toEqual(['confirmed']);
  });

  it('isolates identical conversation IDs across centers and removes obsolete epoch content', async () => {
    vi.mocked(messagesApi.getHistory).mockResolvedValueOnce(history(['center-a']));
    await refreshChatHistory('chat');
    setCenterStorageScope('center-b', 'epoch-1');
    expect(cachedChatHistory('chat')).toBeUndefined();
    vi.mocked(messagesApi.getHistory).mockResolvedValueOnce(history(['center-b']));
    await refreshChatHistory('chat');
    setCenterStorageScope('center-a', 'epoch-1');
    expect(historyIds(cachedChatHistory('chat')?.data)).toEqual(['center-a']);
    setCenterStorageScope('center-a', 'epoch-2');
    expect(cachedChatHistory('chat')).toBeUndefined();
    expect(centerLocalStorage().getItem(CACHE_KEY)).toBeNull();
    setCenterStorageScope('center-b', 'epoch-1');
    expect(historyIds(cachedChatHistory('chat')?.data)).toEqual(['center-b']);
  });
});

describe('chat read ownership', () => {
  it.each(['center switch', 'epoch change', 'runtime replacement', 'content generation', 'conversation clear', 'global clear'] as const)(
    'rejects a first in-flight history response after %s', async (change) => {
      const pending = deferred<ConversationHistory>();
      vi.mocked(messagesApi.getHistory).mockReturnValueOnce(pending.promise);
      const read = refreshChatHistory('chat');
      const rejected = expect(read).rejects.toMatchObject({ name: 'AbortError' });
      if (change === 'center switch') setCenterStorageScope('center-b', 'epoch-1');
      else if (change === 'epoch change') setCenterStorageScope('center-a', 'epoch-2');
      else if (change === 'runtime replacement') resetRuntimeInitialization();
      else if (change === 'content generation') advanceBrowserContentGeneration();
      else invalidateChatReadCache(change === 'conversation clear' ? 'chat' : undefined);
      pending.resolve(history(['late private content']));
      await rejected;
      expect(cachedChatHistory('chat')).toBeUndefined();
      expect(centerLocalStorage().getItem(CACHE_KEY) ?? '').not.toContain('late private content');
    },
  );

  it('invalidates the session list and only the confirmed conversation on a targeted mutation', async () => {
    vi.mocked(messagesApi.getHistory)
      .mockResolvedValueOnce(history(['one'], 'r1', null, 'one'))
      .mockResolvedValueOnce(history(['two'], 'r1', null, 'two'));
    vi.mocked(messagesApi.listSessions).mockResolvedValueOnce(sessionPage(['one', 'two']));
    await refreshChatHistory('one'); await refreshChatHistory('two'); await refreshChatSessions();
    expect(invalidateChatReadCache('one')).toBe(true);
    resetChatReadMemory();
    expect(cachedChatHistory('one')).toBeUndefined();
    expect(cachedChatSessions()).toBeUndefined();
    expect(historyIds(cachedChatHistory('two')?.data)).toEqual(['two']);
  });
});

describe('chat read pagination and reconciliation', () => {
  it('revalidates an unchanged head without discarding older loaded pages', async () => {
    vi.mocked(messagesApi.getHistory)
      .mockResolvedValueOnce(history(['newer'], 'r1', 'c1'))
      .mockResolvedValueOnce(history(['older']))
      .mockResolvedValueOnce({ ...history([]), not_modified: true });
    await refreshChatHistory('chat'); await refreshChatHistory('chat', true);
    vi.mocked(Date.now).mockReturnValue(NOW + 500);
    const refreshed = await refreshChatHistory('chat');
    expect(messagesApi.getHistory).toHaveBeenLastCalledWith(DEFAULT_USER_ID, 'chat', { limit: CHAT_PAGE_SIZE, known_revision: 'r1' });
    expect(historyIds(refreshed.data)).toEqual(['older', 'newer']);
    expect(refreshed.checkedAt).toBe(NOW + 500);
    expect(refreshed.stale).toBe(false);
  });

  it('rebuilds every loaded page atomically after the revision changes', async () => {
    const rebuiltTail = deferred<ConversationHistory>();
    vi.mocked(messagesApi.getHistory)
      .mockResolvedValueOnce(history(['old-newer'], 'r1', 'old-cursor'))
      .mockResolvedValueOnce(history(['deleted-older']))
      .mockResolvedValueOnce(history(['new-head'], 'r2', 'new-cursor'))
      .mockReturnValueOnce(rebuiltTail.promise);
    await refreshChatHistory('chat'); await refreshChatHistory('chat', true);
    const pending = refreshChatHistory('chat');
    await Promise.resolve(); await Promise.resolve();
    expect(historyIds(cachedChatHistory('chat')?.data)).toEqual(['deleted-older', 'old-newer']);
    rebuiltTail.resolve(history(['remaining-older'], 'r2'));
    const refreshed = await pending;
    expect(historyIds(refreshed.data)).toEqual(['remaining-older', 'new-head']);
    expect(refreshed.data.revision).toBe('r2');
    expect(messagesApi.getHistory).toHaveBeenLastCalledWith(DEFAULT_USER_ID, 'chat', { limit: CHAT_PAGE_SIZE, before: 'new-cursor' });
  });

  it('shares concurrent initial refreshes and concurrent requests for the same older page', async () => {
    const head = deferred<ConversationHistory>();
    vi.mocked(messagesApi.getHistory).mockReturnValueOnce(head.promise);
    const first = refreshChatHistory('chat');
    const second = refreshChatHistory('chat');
    expect(messagesApi.getHistory).toHaveBeenCalledTimes(1);
    head.resolve(history(['head'], 'r1', 'c1'));
    expect(await first).toEqual(await second);

    const older = deferred<ConversationHistory>();
    vi.mocked(messagesApi.getHistory).mockReturnValueOnce(older.promise).mockResolvedValue(history(['unexpected-extra-page']));
    const olderFirst = refreshChatHistory('chat', true);
    const olderSecond = refreshChatHistory('chat', true);
    older.resolve(history(['middle'], 'r1', 'c2'));
    expect(await olderFirst).toEqual(await olderSecond);
    expect(messagesApi.getHistory).toHaveBeenCalledTimes(2);
    expect(historyIds(cachedChatHistory('chat')?.data)).toEqual(['middle', 'head']);
  });

  it('waits for an active refresh before loading the older page from its new revision', async () => {
    vi.mocked(messagesApi.getHistory).mockResolvedValueOnce(history(['old'], 'r1', 'old-cursor'));
    await refreshChatHistory('chat');
    const head = deferred<ConversationHistory>();
    vi.mocked(messagesApi.getHistory).mockReturnValueOnce(head.promise).mockResolvedValueOnce(history(['older-new'], 'r2'));
    const refresh = refreshChatHistory('chat');
    const older = refreshChatHistory('chat', true);
    head.resolve(history(['head-new'], 'r2', 'new-cursor'));
    await refresh;
    expect(historyIds((await older).data)).toEqual(['older-new', 'head-new']);
    expect(messagesApi.getHistory).toHaveBeenLastCalledWith(DEFAULT_USER_ID, 'chat', { limit: CHAT_PAGE_SIZE, before: 'new-cursor' });
  });

  it('serializes waiting retries after the first concurrent refresh fails', async () => {
    const firstResponse = deferred<ConversationHistory>();
    const retryResponse = deferred<ConversationHistory>();
    vi.mocked(messagesApi.getHistory)
      .mockReturnValueOnce(firstResponse.promise)
      .mockReturnValueOnce(retryResponse.promise)
      .mockResolvedValue(history(['unexpected-extra-request']));
    const first = refreshChatHistory('chat');
    const failed = expect(first).rejects.toThrow('Disconnected');
    const waiting = [refreshChatHistory('chat'), refreshChatHistory('chat'), refreshChatHistory('chat')];
    firstResponse.reject(new Error('Disconnected'));
    await failed;
    expect(messagesApi.getHistory).toHaveBeenCalledTimes(2);
    retryResponse.resolve(history(['recovered']));
    const results = await Promise.all(waiting);
    expect(results.map((result) => historyIds(result.data))).toEqual([['recovered'], ['recovered'], ['recovered']]);
    expect(messagesApi.getHistory).toHaveBeenCalledTimes(2);
  });

  it('restarts at the head after a stale cursor without mixing revisions', async () => {
    vi.mocked(messagesApi.getHistory)
      .mockResolvedValueOnce(history(['obsolete'], 'r1', 'stale-cursor'))
      .mockRejectedValueOnce({ status: 409 })
      .mockResolvedValueOnce(history(['current'], 'r2', 'fresh-cursor'));
    await refreshChatHistory('chat');
    const refreshed = await refreshChatHistory('chat', true);
    expect(historyIds(refreshed.data)).toEqual(['current']);
    expect(messagesApi.getHistory).toHaveBeenLastCalledWith(DEFAULT_USER_ID, 'chat', { limit: CHAT_PAGE_SIZE });
    expect(refreshed.data.next_before).toBe('fresh-cursor');
  });

  it('retains a failed snapshot as stale and never partially commits a mixed revision', async () => {
    vi.mocked(messagesApi.getHistory)
      .mockResolvedValueOnce(history(['head'], 'r1', 'c1'))
      .mockResolvedValueOnce(history(['tail']))
      .mockResolvedValueOnce(history(['new-head'], 'r2', 'c2'))
      .mockRejectedValueOnce(new Error('Disconnected'));
    await refreshChatHistory('chat'); await refreshChatHistory('chat', true);
    await expect(refreshChatHistory('chat')).rejects.toThrow('Disconnected');
    const retained = cachedChatHistory('chat');
    expect(retained?.stale).toBe(true);
    expect(retained?.data.revision).toBe('r1');
    expect(historyIds(retained?.data)).toEqual(['tail', 'head']);
  });

  it('combines and deduplicates session pages, then conditionally revalidates the loaded list', async () => {
    vi.mocked(messagesApi.listSessions)
      .mockResolvedValueOnce(sessionPage(['newer', 'shared'], 's1', 'older-cursor'))
      .mockResolvedValueOnce(sessionPage(['shared', 'older'], 's1'))
      .mockResolvedValueOnce({ ...sessionPage([], 's1'), not_modified: true });
    await refreshChatSessions();
    const paged = await refreshChatSessions(true);
    expect(sessionIds(paged.data)).toEqual(['newer', 'shared', 'older']);
    expect(paged.data.count).toBe(3);
    const refreshed = await refreshChatSessions();
    expect(sessionIds(refreshed.data)).toEqual(['newer', 'shared', 'older']);
    expect(messagesApi.listSessions).toHaveBeenLastCalledWith(DEFAULT_USER_ID, CHAT_PAGE_SIZE, { known_revision: 's1' });
    resetChatReadMemory();
    expect(sessionIds(cachedChatSessions()?.data)).toEqual(['newer', 'shared']);
    expect(cachedChatSessions()?.stale).toBe(true);
  });
});
