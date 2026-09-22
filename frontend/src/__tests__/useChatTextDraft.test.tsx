import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useChatTextDraft } from '@/hooks/useChatTextDraft';
import { setCenterStorageScope } from '@/runtime/center-storage';
import { captureChatDraftOwner, clearAllChatDrafts, readChatDraft, writeChatDraft } from '@/runtime/chat-draft-storage';

describe('chat text draft hydration', () => {
  beforeEach(() => { localStorage.clear(); setCenterStorageScope('draft-hook', 'epoch'); clearAllChatDrafts(); });
  afterEach(() => { vi.restoreAllMocks(); });

  it('hydrates synchronously on remount and keeps session drafts separate', () => {
    const hook = renderHook(({ session }) => useChatTextDraft(session), { initialProps: { session: 'a' } });
    act(() => hook.result.current.setText('Session A'));
    hook.rerender({ session: 'b' });
    expect(hook.result.current.text).toBe('');
    act(() => hook.result.current.setText('Session B'));
    hook.rerender({ session: 'a' });
    expect(hook.result.current.text).toBe('Session A');
    hook.unmount();
    const online = renderHook(() => useChatTextDraft('a'));
    expect(online.result.current.text).toBe('Session A');
    expect(online.result.current.saveState).toBe('saved');
    act(() => online.result.current.setText('Newly typed'));
    online.rerender();
    expect(online.result.current.text).toBe('Newly typed');
  });

  it('preserves the visible text and reports failed persistence', () => {
    const hook = renderHook(() => useChatTextDraft('a'));
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('Quota'); });
    act(() => hook.result.current.setText('Unstored text'));
    expect(hook.result.current.text).toBe('Unstored text');
    expect(hook.result.current.saveState).toBe('unavailable');
    act(() => hook.result.current.clear());
    expect(hook.result.current.text).toBe('Unstored text');
  });

  it('retains failed edits across session changes and offline-to-online remounts', () => {
    const hook = renderHook(({ session }) => useChatTextDraft(session), { initialProps: { session: 'a' } });
    const storage = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('Quota'); });
    act(() => hook.result.current.setText('Keep across reconnect'));
    hook.rerender({ session: 'b' });
    act(() => hook.result.current.setText('Another unsaved draft'));
    hook.rerender({ session: 'a' });
    expect(hook.result.current.text).toBe('Keep across reconnect');
    hook.unmount();
    const online = renderHook(() => useChatTextDraft('a'));
    expect(online.result.current.text).toBe('Keep across reconnect');
    expect(online.result.current.saveState).toBe('unavailable');
    storage.mockRestore();
    act(() => online.result.current.setText('Saved after reconnect'));
    expect(online.result.current.saveState).toBe('saved');
  });

  it('retains unsaved text as a conflict when persisted content changed before remount', () => {
    const hook = renderHook(() => useChatTextDraft('a'));
    act(() => hook.result.current.setText('Base'));
    const revision = hook.result.current.revision;
    const storage = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('Quota'); });
    act(() => hook.result.current.setText('Unsaved local edit'));
    hook.unmount();
    storage.mockRestore();
    const owner = captureChatDraftOwner('a');
    const newer = { version: 1, drafts: [{ sessionId: 'a', text: 'New durable text', revision: 'newer', updatedAt: Date.now() }] };
    for (let i = 0; i < localStorage.length; i += 1) {
      const key = localStorage.key(i);
      if (key?.endsWith('magi.chat.text-drafts.v1')) localStorage.setItem(key, JSON.stringify(newer));
    }
    const online = renderHook(() => useChatTextDraft('a'));
    expect(online.result.current.text).toBe('Unsaved local edit');
    expect(online.result.current.saveState).toBe('conflict');
    expect(online.result.current.revision).toBe(revision);
    act(() => online.result.current.setText('Keep editing'));
    expect(readChatDraft(owner)).toMatchObject({ ok: true, draft: { text: 'New durable text' } });
  });

  it('never erases a newer persisted draft when acknowledging an older send', () => {
    const hook = renderHook(() => useChatTextDraft('a'));
    act(() => hook.result.current.setText('Submitted'));
    writeChatDraft(captureChatDraftOwner('a'), 'Newer other editor', hook.result.current.revision);
    act(() => hook.result.current.clear());
    expect(hook.result.current.saveState).toBe('conflict');
    expect(readChatDraft(captureChatDraftOwner('a'))).toMatchObject({ ok: true, draft: { text: 'Newer other editor' } });
  });

  it('ignores a captured setter after switching centers', () => {
    const hook = renderHook(() => useChatTextDraft('a'));
    const previous = hook.result.current.setText;
    setCenterStorageScope('different', 'epoch');
    hook.rerender();
    act(() => previous('Wrong center'));
    expect(hook.result.current.text).toBe('');
    expect(readChatDraft(captureChatDraftOwner('a'))).toEqual({ ok: true, draft: null });
  });

  it('erases failed in-memory edits when conversation content is cleared', () => {
    const hook = renderHook(() => useChatTextDraft('a'));
    const storage = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('Quota'); });
    act(() => hook.result.current.setText('Private memory-only draft'));
    hook.unmount();
    storage.mockRestore();
    clearAllChatDrafts();
    const next = renderHook(() => useChatTextDraft('a'));
    expect(next.result.current.text).toBe('');
  });
});
