import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { advanceBrowserContentGeneration } from '@/lib/browserContentGeneration';
import { centerLocalStorage, setCenterStorageScope } from '@/runtime/center-storage';
import {
  CHAT_DRAFT_STORAGE_KEY, captureChatDraftOwner, clearAllChatDrafts, clearChatDraft,
  readChatDraft, writeChatDraft,
} from '@/runtime/chat-draft-storage';

describe('scoped chat text drafts', () => {
  beforeEach(() => { localStorage.clear(); setCenterStorageScope('draft-tests', 'epoch'); });
  afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

  it('restores only the same center, epoch and session', () => {
    const owner = captureChatDraftOwner('a');
    expect(writeChatDraft(owner, 'Unsent text', null).ok).toBe(true);
    expect(readChatDraft(captureChatDraftOwner('a'))).toMatchObject({ ok: true, draft: { text: 'Unsent text' } });
    expect(readChatDraft(captureChatDraftOwner('b'))).toEqual({ ok: true, draft: null });
    setCenterStorageScope('other-center', 'epoch');
    expect(readChatDraft(captureChatDraftOwner('a'))).toEqual({ ok: true, draft: null });
    expect(writeChatDraft(owner, 'Late old draft', null)).toEqual({ ok: false, reason: 'owner_changed' });
    setCenterStorageScope('draft-tests', 'new-epoch');
    expect(readChatDraft(captureChatDraftOwner('a'))).toEqual({ ok: true, draft: null });
    expect(Object.values(localStorage).join('')).not.toContain('Unsent text');
  });

  it('rejects an old write or send acknowledgment after a newer edit', () => {
    const owner = captureChatDraftOwner('a');
    const first = writeChatDraft(owner, 'First', null);
    if (!first.ok || !first.draft) throw new Error('Draft missing');
    const second = writeChatDraft(owner, 'Newer', first.draft.revision);
    expect(second.ok).toBe(true);
    expect(writeChatDraft(owner, '', first.draft.revision)).toEqual({ ok: false, reason: 'conflict' });
    expect(readChatDraft(owner)).toMatchObject({ ok: true, draft: { text: 'Newer' } });
    if (!second.ok || !second.draft) throw new Error('Draft missing');
    expect(writeChatDraft(owner, '', second.draft.revision).ok).toBe(true);
    expect(writeChatDraft(owner, 'Resurrection', null)).toEqual({ ok: false, reason: 'conflict' });
  });

  it('expires drafts after thirty days and rejects invalid persisted data', () => {
    vi.useFakeTimers(); vi.setSystemTime(new Date('2026-09-01'));
    const owner = captureChatDraftOwner('a');
    writeChatDraft(owner, 'Expired', null);
    vi.advanceTimersByTime(31 * 24 * 60 * 60 * 1000);
    expect(readChatDraft(owner)).toEqual({ ok: true, draft: null });
    for (const value of ['{', JSON.stringify({ version: 1, drafts: [{ text: 42 }] })]) {
      centerLocalStorage().setItem(CHAT_DRAFT_STORAGE_KEY, value);
      expect(readChatDraft(owner)).toEqual({ ok: true, draft: null });
    }
  });

  it('bounds persisted drafts to fifty sessions and one hundred KiB', () => {
    for (let i = 0; i < 55; i += 1) expect(writeChatDraft(captureChatDraftOwner(`s${i}`), 'text', null).ok).toBe(true);
    expect(readChatDraft(captureChatDraftOwner('s0'))).toEqual({ ok: true, draft: null });
    expect(readChatDraft(captureChatDraftOwner('s54'))).toMatchObject({ ok: true, draft: { text: 'text' } });
    for (let i = 0; i < 10; i += 1) writeChatDraft(captureChatDraftOwner(`large${i}`), 'x'.repeat(20_000), null);
    expect((centerLocalStorage().getItem(CHAT_DRAFT_STORAGE_KEY)?.length ?? 0) * 2).toBeLessThanOrEqual(100 * 1024);
    expect(writeChatDraft(captureChatDraftOwner('huge'), 'x'.repeat(100 * 1024), null)).toEqual({ ok: false, reason: 'too_large' });
  });

  it('returns a failure when storage throws or silently refuses the write', () => {
    const owner = captureChatDraftOwner('a');
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('Quota'); });
    expect(writeChatDraft(owner, 'Keep in memory', null)).toEqual({ ok: false, reason: 'unavailable' });
    spy.mockImplementation(() => undefined);
    expect(writeChatDraft(owner, 'Keep in memory', null)).toEqual({ ok: false, reason: 'unavailable' });
  });

  it('retires deleted scopes even when storage cleanup fails', () => {
    const owner = captureChatDraftOwner('a');
    writeChatDraft(owner, 'Private', null);
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('Blocked'); });
    expect(clearChatDraft('a')).toBe(false);
    expect(readChatDraft(captureChatDraftOwner('a'))).toEqual({ ok: true, draft: null });
    expect(writeChatDraft(owner, 'Late', null)).toEqual({ ok: false, reason: 'owner_changed' });
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => { throw new Error('Blocked'); });
    expect(clearAllChatDrafts()).toBe(false);
    expect(readChatDraft(captureChatDraftOwner('a'))).toEqual({ ok: true, draft: null });
  });

  it('retires owners after content generation changes', () => {
    const owner = captureChatDraftOwner('a');
    advanceBrowserContentGeneration();
    expect(writeChatDraft(owner, 'Late', null)).toEqual({ ok: false, reason: 'owner_changed' });
  });
});
