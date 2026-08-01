import type { ChatSessionListItem } from '@/api';
import type { ChatTimelineMessage } from '@/domain/chat/state';

export type ReadCursor = {
  messageCount: number;
  lastTimestamp: number;
};

const READ_CURSOR_STORAGE_KEY = 'magi.chat.readCursors.v1';
const READ_CURSOR_INITIALIZED_KEY = 'magi.chat.readCursors.initialized.v1';

const canUseLocalStorage = (): boolean => (
  typeof window !== 'undefined' && typeof window.localStorage !== 'undefined'
);

const normalizeNonNegativeInteger = (value: unknown): number => {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric < 0) {
    return 0;
  }
  return Math.trunc(numeric);
};

export const loadReadCursors = (): Record<string, ReadCursor> => {
  if (!canUseLocalStorage()) {
    return {};
  }
  try {
    const raw = window.localStorage.getItem(READ_CURSOR_STORAGE_KEY);
    if (!raw) {
      return {};
    }
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return {};
    }
    const cursors: Record<string, ReadCursor> = {};
    for (const [sessionId, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (!sessionId || !value || typeof value !== 'object' || Array.isArray(value)) {
        continue;
      }
      const cursor = value as Record<string, unknown>;
      cursors[sessionId] = {
        messageCount: normalizeNonNegativeInteger(cursor.messageCount),
        lastTimestamp: normalizeNonNegativeInteger(cursor.lastTimestamp),
      };
    }
    return cursors;
  } catch {
    return {};
  }
};

export const saveReadCursors = (cursors: Record<string, ReadCursor>) => {
  if (!canUseLocalStorage()) {
    return;
  }
  try {
    window.localStorage.setItem(READ_CURSOR_STORAGE_KEY, JSON.stringify(cursors));
    window.localStorage.setItem(READ_CURSOR_INITIALIZED_KEY, 'true');
  } catch {
    // Read cursors are a UX cache; failures should not break chat.
  }
};

export const readCursorsInitialized = (): boolean => {
  if (!canUseLocalStorage()) {
    return false;
  }
  try {
    return window.localStorage.getItem(READ_CURSOR_INITIALIZED_KEY) === 'true';
  } catch {
    return false;
  }
};

export const clearConversationReadCursors = (): boolean => {
  if (!canUseLocalStorage()) {
    return typeof window === 'undefined';
  }
  try {
    window.localStorage.removeItem(READ_CURSOR_STORAGE_KEY);
    window.localStorage.removeItem(READ_CURSOR_INITIALIZED_KEY);
    return window.localStorage.getItem(READ_CURSOR_STORAGE_KEY) === null
      && window.localStorage.getItem(READ_CURSOR_INITIALIZED_KEY) === null;
  } catch {
    return false;
  }
};

const latestTimestampFromMessages = (messages: ChatTimelineMessage[]): number => (
  messages.reduce((latest, message) => {
    const timestamp = normalizeNonNegativeInteger(message.timestamp);
    return Math.max(latest, Math.floor(timestamp / 1000));
  }, 0)
);

export const buildReadCursor = (
  session: ChatSessionListItem | undefined,
  messages: ChatTimelineMessage[] | undefined,
): ReadCursor => {
  const messageCount = Math.max(
    normalizeNonNegativeInteger(session?.message_count),
    normalizeNonNegativeInteger(messages?.length),
  );
  const lastTimestamp = Math.max(
    normalizeNonNegativeInteger(session?.last_timestamp),
    latestTimestampFromMessages(messages || []),
  );
  return { messageCount, lastTimestamp };
};

export const persistSessionReadCursor = (
  sessionId: string | null | undefined,
  session: ChatSessionListItem | undefined,
  messages: ChatTimelineMessage[] | undefined,
) => {
  const normalizedSessionId = String(sessionId || '').trim();
  if (!normalizedSessionId) {
    return;
  }
  const cursors = loadReadCursors();
  cursors[normalizedSessionId] = buildReadCursor(session, messages);
  saveReadCursors(cursors);
};

export const unreadCountFromCursor = (
  session: ChatSessionListItem,
  cursor: ReadCursor | undefined,
): number => {
  const messageCount = normalizeNonNegativeInteger(session.message_count);
  if (!cursor) {
    return messageCount;
  }
  return Math.max(0, messageCount - normalizeNonNegativeInteger(cursor.messageCount));
};
