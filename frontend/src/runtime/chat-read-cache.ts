import { z } from 'zod';
import { messagesApi } from '@/api';
import type { ChatPageMetadata, ConversationHistory, SessionListResponse } from '@/api/modules/messages';
import { parseConversationHistory, parseSessionList } from '@/api/event-contract';
import { DEFAULT_USER_ID } from '@/constants';
import { captureBrowserContentGeneration, isBrowserContentGenerationCurrent } from '@/lib/browserContentGeneration';
import { centerLocalStorage, centerStorageKey } from './center-storage';
import { getRuntimeGeneration, subscribeRuntimeReset } from './config';

export const CHAT_PAGE_SIZE = 50;
const CACHE_KEY = 'magi.chat.read-cache.v1';
const MAX_CACHE_BYTES = 1_048_576;
const MAX_CACHED_SESSIONS = 8;
const MAX_MEMORY_WINDOWS = 20;
const CACHE_TTL_MS = 7 * 24 * 60 * 60 * 1_000;

type Page = ConversationHistory | SessionListResponse;
export type ChatReadSnapshot<T extends Page> = { data: T; checkedAt: number; stale: boolean };
type Window<T extends Page> = { pages: T[]; checkedAt: number; stale: boolean };
type Stored = { version: 1; entries: { key: string; checkedAt: number; data: unknown }[] };
const storedSchema = z.object({
  version: z.literal(1),
  entries: z.array(z.object({ key: z.string(), checkedAt: z.number().finite(), data: z.unknown() })).max(MAX_CACHED_SESSIONS + 1),
});
const histories = new Map<string, Window<ConversationHistory>>();
const sessions = new Map<string, Window<SessionListResponse>>();
const requests = new Map<string, Promise<unknown>>();
const invalidations = new Map<string, number>();
let resetEpoch = 0;

function keyFor(sessionId?: string): string {
  return centerStorageKey(`${CACHE_KEY}:${DEFAULT_USER_ID}:${sessionId === undefined ? 'sessions' : `history:${sessionId}`}`);
}

function guard(key: string): () => void {
  const content = captureBrowserContentGeneration();
  const runtime = getRuntimeGeneration();
  const scope = centerStorageKey(CACHE_KEY);
  const epoch = resetEpoch;
  const local = invalidations.get(key);
  return () => {
    if (!isBrowserContentGenerationCurrent(content) || runtime !== getRuntimeGeneration()
      || scope !== centerStorageKey(CACHE_KEY) || epoch !== resetEpoch || local !== invalidations.get(key)) {
      throw new DOMException('Chat snapshot owner changed', 'AbortError');
    }
  };
}

function readStored(): Stored {
  try {
    const raw = centerLocalStorage().getItem(CACHE_KEY);
    if (raw && raw.length * 2 <= MAX_CACHE_BYTES) {
      const parsed = storedSchema.safeParse(JSON.parse(raw));
      if (parsed.success) return parsed.data;
    }
  } catch { /* Unavailable or invalid cache never prevents a server read. */ }
  return { version: 1, entries: [] };
}

function storeHead(key: string, data: Page, checkedAt: number): void {
  if (key.startsWith('magi.center.unbound.')) return;
  try {
    const entries = readStored().entries.filter((item) => item.key !== key && checkedAt - item.checkedAt < CACHE_TTL_MS);
    entries.unshift({ key, checkedAt, data });
    let historyCount = 0;
    for (let index = 0; index < entries.length;) {
      if (entries[index].key !== keyFor() && ++historyCount > MAX_CACHED_SESSIONS) entries.splice(index, 1);
      else index += 1;
    }
    entries.splice(MAX_CACHED_SESSIONS + 1);
    let serialized = JSON.stringify({ version: 1, entries });
    while (serialized.length * 2 > MAX_CACHE_BYTES && entries.length) {
      entries.pop();
      serialized = JSON.stringify({ version: 1, entries });
    }
    centerLocalStorage().setItem(CACHE_KEY, serialized);
  } catch { /* Quota and storage failures leave the confirmed in-memory snapshot usable. */ }
}

function restore<T extends Page>(key: string, parse: (value: unknown) => T): Window<T> | undefined {
  if (invalidations.has(key)) return undefined;
  const saved = readStored().entries.find((item) => item.key === key);
  if (!saved || saved.checkedAt > Date.now() || Date.now() - saved.checkedAt > CACHE_TTL_MS) return undefined;
  try {
    const data = parse(saved.data);
    if (data.not_modified || data.user_id !== DEFAULT_USER_ID) return undefined;
    return { pages: [data], checkedAt: saved.checkedAt, stale: true };
  } catch { return undefined; }
}

function retain<T extends Page>(map: Map<string, Window<T>>, key: string, window: Window<T>): void {
  map.delete(key);
  map.set(key, window);
  while (map.size > MAX_MEMORY_WINDOWS) {
    const oldest = map.keys().next().value;
    if (oldest === undefined) break;
    map.delete(oldest);
  }
}

function combineHistory(window: Window<ConversationHistory>): ChatReadSnapshot<ConversationHistory> {
  const head = window.pages[0];
  const tail = window.pages[window.pages.length - 1];
  const seen = new Set<string>();
  const messages = window.pages.slice().reverse().flatMap((page) => page.messages).filter((message) => {
    const key = message.message_id || `${message.turn_id}:${message.kind}:${message.timestamp}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  return { data: { ...head, messages, count: messages.length, has_more: tail.has_more, next_before: tail.next_before }, checkedAt: window.checkedAt, stale: window.stale };
}

function combineSessions(window: Window<SessionListResponse>): ChatReadSnapshot<SessionListResponse> {
  const head = window.pages[0];
  const tail = window.pages[window.pages.length - 1];
  const seen = new Set<string>();
  const items = window.pages.flatMap((page) => page.sessions).filter((item) => {
    if (seen.has(item.session_id)) return false;
    seen.add(item.session_id);
    return true;
  });
  return { data: { ...head, sessions: items, count: items.length, has_more: tail.has_more, next_before: tail.next_before }, checkedAt: window.checkedAt, stale: window.stale };
}

export function cachedChatHistory(sessionId: string): ChatReadSnapshot<ConversationHistory> | undefined {
  const key = keyFor(sessionId);
  const window = histories.get(key) ?? restore(key, parseConversationHistory);
  if (!window || window.pages[0].session_id !== sessionId) return undefined;
  retain(histories, key, window);
  return combineHistory(window);
}

export function cachedChatSessions(): ChatReadSnapshot<SessionListResponse> | undefined {
  const key = keyFor();
  const window = sessions.get(key) ?? restore(key, parseSessionList);
  if (!window) return undefined;
  retain(sessions, key, window);
  return combineSessions(window);
}

export type OfflineChatSnapshot = {
  sessionId: string;
  title: string;
  checkedAt: number;
  history?: ChatReadSnapshot<ConversationHistory>;
};

/** Read only persisted heads; never request missing pages or attachment content. */
export function savedOfflineChats(): OfflineChatSnapshot[] {
  const list = restore(keyFor(), parseSessionList);
  const items = new Map<string, OfflineChatSnapshot>();
  for (const session of list?.pages[0].sessions ?? []) {
    items.set(session.session_id, { sessionId: session.session_id, title: session.title, checkedAt: list!.checkedAt });
  }
  const prefix = keyFor('');
  for (const entry of readStored().entries) {
    if (!entry.key.startsWith(prefix)) continue;
    const sessionId = entry.key.slice(prefix.length);
    const history = restore(entry.key, parseConversationHistory);
    if (!history || history.pages[0].session_id !== sessionId) continue;
    const existing = items.get(sessionId);
    items.set(sessionId, {
      sessionId,
      title: existing?.title ?? history.pages[0].messages.find((message) => message.role === 'user')?.content.slice(0, 80) ?? '',
      checkedAt: history.checkedAt,
      history: combineHistory(history),
    });
  }
  return [...items.values()];
}

function stalePage(error: unknown): boolean {
  return typeof error === 'object' && error !== null && 'status' in error && error.status === 409;
}

async function readWindow<T extends Page>(
  key: string,
  map: Map<string, Window<T>>,
  fetchPage: (query: { before?: string; known_revision?: string }) => Promise<T>,
  older: boolean,
): Promise<Window<T>> {
  const assertCurrent = guard(key);
  const desiredPageCount = (map.get(key)?.pages.length ?? 0) + 1;
  // One owner serializes refresh and pagination for each resource; other resources stay independent.
  while (requests.has(key)) {
    const pending = requests.get(key)!;
    try { await pending; } catch { /* This caller may retry after the previous read failed. */ }
    assertCurrent();
    const latest = map.get(key);
    if (latest && !latest.stale && (!older || latest.pages.length >= desiredPageCount)) return latest;
  }
  const run = async (): Promise<Window<T>> => {
    let existing = map.get(key);
    const pageCount = Math.max(1, existing?.pages.length ?? 1);
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        let pages: T[];
        const tail = existing?.pages[existing.pages.length - 1];
        if (older && tail && !tail.has_more) return existing!;
        if (older && tail?.next_before) {
          const next = await fetchPage({ before: tail.next_before });
          assertCurrent();
          if (next.not_modified || next.revision !== existing?.pages[0].revision) throw { status: 409 };
          pages = [...existing.pages, next];
        } else {
          const head = await fetchPage(existing ? { known_revision: existing.pages[0].revision } : {});
          assertCurrent();
          if (head.not_modified) {
            if (!existing || existing.pages[0].revision !== head.revision) throw new Error('Unowned chat cache validation');
            pages = existing.pages;
          } else {
            pages = [head];
            // Reconcile the loaded window atomically so deleted rows never survive in old pages.
            while (pages.length < pageCount && pages[pages.length - 1].next_before) {
              const next = await fetchPage({ before: pages[pages.length - 1].next_before! });
              assertCurrent();
              if (next.not_modified || next.revision !== head.revision) throw { status: 409 };
              pages.push(next);
            }
          }
        }
        const window = { pages, checkedAt: Date.now(), stale: false };
        assertCurrent();
        retain(map, key, window);
        storeHead(key, pages[0], window.checkedAt);
        return window;
      } catch (error) {
        assertCurrent();
        if (attempt === 0 && stalePage(error)) { existing = undefined; older = false; continue; }
        const retained = map.get(key);
        if (retained) retained.stale = true;
        throw error;
      }
    }
    throw new Error('Chat snapshot changed during pagination');
  };
  const request = run();
  requests.set(key, request);
  try { return await request; }
  finally { if (requests.get(key) === request) requests.delete(key); }
}

export async function refreshChatHistory(sessionId: string, older = false): Promise<ChatReadSnapshot<ConversationHistory>> {
  cachedChatHistory(sessionId);
  return combineHistory(await readWindow(keyFor(sessionId), histories,
    (query) => messagesApi.getHistory(DEFAULT_USER_ID, sessionId, { limit: CHAT_PAGE_SIZE, ...query }), older));
}

export async function refreshChatSessions(older = false): Promise<ChatReadSnapshot<SessionListResponse>> {
  cachedChatSessions();
  return combineSessions(await readWindow(keyFor(), sessions,
    (query) => messagesApi.listSessions(DEFAULT_USER_ID, CHAT_PAGE_SIZE, query), older));
}

/** Erase payloads as soon as their owning domain mutation is confirmed. */
export function invalidateChatReadCache(sessionId?: string): boolean {
  if (sessionId === undefined) resetEpoch += 1;
  const keys = sessionId === undefined ? [keyFor(), ...histories.keys()] : [keyFor(), keyFor(sessionId)];
  for (const key of keys) {
    invalidations.set(key, (invalidations.get(key) ?? 0) + 1);
    histories.delete(key);
    sessions.delete(key);
    requests.delete(key);
  }
  try {
    const storage = centerLocalStorage();
    if (sessionId !== undefined) {
      try {
        const retained = JSON.stringify({ version: 1, entries: readStored().entries.filter((item) => !keys.includes(item.key)) });
        storage.setItem(CACHE_KEY, retained);
        if (storage.getItem(CACHE_KEY) === retained) return true;
      } catch { /* Removal can still succeed when storage refuses a rewrite. */ }
    }
    storage.removeItem(CACHE_KEY);
    return storage.getItem(CACHE_KEY) === null;
  } catch { return false; }
}

export function resetChatReadMemory(): void {
  resetEpoch += 1;
  histories.clear(); sessions.clear(); requests.clear(); invalidations.clear();
}
subscribeRuntimeReset(resetChatReadMemory);

export function pageCanLoadMore(page: ChatPageMetadata | undefined): boolean {
  return Boolean(page?.has_more && page.next_before);
}
