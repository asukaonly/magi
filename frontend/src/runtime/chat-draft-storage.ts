import { z } from 'zod';
import { captureBrowserContentGeneration, isBrowserContentGenerationCurrent } from '@/lib/browserContentGeneration';
import { centerLocalStorage, centerStorageKey } from './center-storage';

export const CHAT_DRAFT_STORAGE_KEY = 'magi.chat.text-drafts.v1';
const MAX_BYTES = 100 * 1024;
const MAX_SESSIONS = 50;
const TTL_MS = 30 * 24 * 60 * 60 * 1000;
const draftSchema = z.object({
  sessionId: z.string().min(1).max(512),
  text: z.string().max(MAX_BYTES / 2),
  revision: z.string().min(1).max(128),
  updatedAt: z.number().finite().nonnegative(),
});
const storeSchema = z.object({ version: z.literal(1), drafts: z.array(draftSchema).max(MAX_SESSIONS) });
export type ChatTextDraft = z.infer<typeof draftSchema>;
export type ChatDraftResult = { ok: true; draft: ChatTextDraft | null }
  | { ok: false; reason: 'unavailable' | 'conflict' | 'owner_changed' | 'too_large' };

const versions = new Map<string, number>();
const retiredSessions = new Set<string>();
const retiredScopes = new Set<string>();
type UnsavedDraft = { owner: ChatDraftOwner; text: string; revision: string | null;
  saveState: 'unsaved' | 'conflict' | 'unavailable'; updatedAt: number };
const unsavedDrafts = new Map<string, UnsavedDraft>();

export type ChatDraftOwner = {
  readonly scope: string;
  readonly sessionId: string;
  readonly contentGeneration: number;
  readonly scopeVersion: number;
  readonly sessionVersion: number;
};

function sessionKey(scope: string, sessionId: string): string { return JSON.stringify([scope, sessionId]); }

export function captureChatDraftOwner(sessionId: string): ChatDraftOwner {
  const scope = centerStorageKey(CHAT_DRAFT_STORAGE_KEY);
  return {
    scope, sessionId, contentGeneration: captureBrowserContentGeneration(),
    scopeVersion: versions.get(scope) ?? 0,
    sessionVersion: versions.get(sessionKey(scope, sessionId)) ?? 0,
  };
}

export function isChatDraftOwnerCurrent(owner: ChatDraftOwner): boolean {
  return owner.scope === centerStorageKey(CHAT_DRAFT_STORAGE_KEY)
    && isBrowserContentGenerationCurrent(owner.contentGeneration)
    && owner.scopeVersion === (versions.get(owner.scope) ?? 0)
    && owner.sessionVersion === (versions.get(sessionKey(owner.scope, owner.sessionId)) ?? 0);
}

/** Keep failed edits through offline/online remounts without treating them as durable. */
export function rememberUnsavedChatDraft(
  owner: ChatDraftOwner, text: string, revision: string | null, saveState: UnsavedDraft['saveState'],
): void {
  if (!isChatDraftOwnerCurrent(owner)) return;
  const key = sessionKey(owner.scope, owner.sessionId);
  const draft: UnsavedDraft = { owner, text, revision, saveState, updatedAt: Date.now() };
  unsavedDrafts.delete(key);
  if (JSON.stringify(draft).length * 2 > MAX_BYTES) return;
  unsavedDrafts.set(key, draft);
  while (unsavedDrafts.size > MAX_SESSIONS || JSON.stringify([...unsavedDrafts.values()]).length * 2 > MAX_BYTES) {
    const oldest = unsavedDrafts.keys().next().value;
    if (oldest === undefined) break;
    unsavedDrafts.delete(oldest);
  }
}

export function readUnsavedChatDraft(owner: ChatDraftOwner): UnsavedDraft | undefined {
  const key = sessionKey(owner.scope, owner.sessionId);
  const draft = unsavedDrafts.get(key);
  if (!draft) return undefined;
  if (!isChatDraftOwnerCurrent(owner) || !isChatDraftOwnerCurrent(draft.owner)
    || Date.now() - draft.updatedAt > TTL_MS) {
    unsavedDrafts.delete(key);
    return undefined;
  }
  return draft;
}

export function forgetUnsavedChatDraft(owner: ChatDraftOwner): void {
  if (isChatDraftOwnerCurrent(owner)) unsavedDrafts.delete(sessionKey(owner.scope, owner.sessionId));
}

function readEntries(): ChatTextDraft[] {
  const scope = centerStorageKey(CHAT_DRAFT_STORAGE_KEY);
  if (retiredScopes.has(scope)) return [];
  const raw = centerLocalStorage().getItem(CHAT_DRAFT_STORAGE_KEY);
  if (!raw || raw.length * 2 > MAX_BYTES) return [];
  let value: unknown;
  try { value = JSON.parse(raw); } catch { return []; }
  const parsed = storeSchema.safeParse(value);
  if (!parsed.success) return [];
  const now = Date.now();
  const seen = new Set<string>();
  return parsed.data.drafts.filter((draft) => {
    if (seen.has(draft.sessionId) || retiredSessions.has(sessionKey(scope, draft.sessionId))
      || draft.updatedAt > now || now - draft.updatedAt > TTL_MS) return false;
    seen.add(draft.sessionId);
    return true;
  });
}

export function readChatDraft(owner: ChatDraftOwner): ChatDraftResult {
  if (!isChatDraftOwnerCurrent(owner)) return { ok: false, reason: 'owner_changed' };
  if (owner.scope.startsWith('magi.center.unbound.')) return { ok: false, reason: 'unavailable' };
  try { return { ok: true, draft: readEntries().find((draft) => draft.sessionId === owner.sessionId) ?? null }; }
  catch { return { ok: false, reason: 'unavailable' }; }
}

/** A draft revision owns both edits and send acknowledgments; empty drafts retain a tombstone. */
export function writeChatDraft(owner: ChatDraftOwner, text: string, expectedRevision: string | null): ChatDraftResult {
  if (!isChatDraftOwnerCurrent(owner)) return { ok: false, reason: 'owner_changed' };
  if (owner.scope.startsWith('magi.center.unbound.') || !owner.sessionId || owner.sessionId.length > 512) {
    return { ok: false, reason: 'unavailable' };
  }
  if (text.length * 2 > MAX_BYTES) return { ok: false, reason: 'too_large' };
  try {
    const entries = readEntries();
    const current = entries.find((draft) => draft.sessionId === owner.sessionId);
    if ((current?.revision ?? null) !== expectedRevision) return { ok: false, reason: 'conflict' };
    const draft: ChatTextDraft = { sessionId: owner.sessionId, text, revision: crypto.randomUUID(), updatedAt: Date.now() };
    const drafts = [draft, ...entries.filter((entry) => entry.sessionId !== owner.sessionId)].slice(0, MAX_SESSIONS);
    let serialized = JSON.stringify({ version: 1, drafts });
    while (serialized.length * 2 > MAX_BYTES && drafts.length > 1) {
      drafts.pop(); serialized = JSON.stringify({ version: 1, drafts });
    }
    if (serialized.length * 2 > MAX_BYTES) return { ok: false, reason: 'too_large' };
    const storage = centerLocalStorage();
    storage.setItem(CHAT_DRAFT_STORAGE_KEY, serialized);
    if (storage.getItem(CHAT_DRAFT_STORAGE_KEY) !== serialized) return { ok: false, reason: 'unavailable' };
    retiredScopes.delete(owner.scope);
    retiredSessions.delete(sessionKey(owner.scope, owner.sessionId));
    unsavedDrafts.delete(sessionKey(owner.scope, owner.sessionId));
    return { ok: true, draft };
  } catch { return { ok: false, reason: 'unavailable' }; }
}

export function clearChatDraft(sessionId: string): boolean {
  const scope = centerStorageKey(CHAT_DRAFT_STORAGE_KEY);
  const key = sessionKey(scope, sessionId);
  versions.set(key, (versions.get(key) ?? 0) + 1);
  retiredSessions.add(key);
  unsavedDrafts.delete(key);
  try {
    const storage = centerLocalStorage();
    const serialized = JSON.stringify({ version: 1, drafts: readEntries() });
    storage.setItem(CHAT_DRAFT_STORAGE_KEY, serialized);
    return storage.getItem(CHAT_DRAFT_STORAGE_KEY) === serialized;
  } catch { return false; }
}

export function clearAllChatDrafts(): boolean {
  const scope = centerStorageKey(CHAT_DRAFT_STORAGE_KEY);
  versions.set(scope, (versions.get(scope) ?? 0) + 1);
  retiredScopes.add(scope);
  // Epoch reconciliation may already have rebound storage before cleanup runs.
  unsavedDrafts.clear();
  try {
    const storage = centerLocalStorage();
    storage.removeItem(CHAT_DRAFT_STORAGE_KEY);
    return storage.getItem(CHAT_DRAFT_STORAGE_KEY) === null;
  } catch { return false; }
}
