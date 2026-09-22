import { useCallback, useRef, useState } from 'react';
import {
  captureChatDraftOwner, isChatDraftOwnerCurrent, readChatDraft, writeChatDraft,
  forgetUnsavedChatDraft, readUnsavedChatDraft, rememberUnsavedChatDraft,
  type ChatDraftOwner,
} from '@/runtime/chat-draft-storage';

export type ChatDraftSaveState = 'saved' | 'unsaved' | 'conflict' | 'unavailable';
type State = { owner: ChatDraftOwner; text: string; revision: string | null; editRevision: number; saveState: ChatDraftSaveState };

function restore(sessionId: string | null): State {
  const owner = captureChatDraftOwner(sessionId ?? '');
  const result = sessionId ? readChatDraft(owner) : null;
  const unsaved = sessionId ? readUnsavedChatDraft(owner) : undefined;
  // A failed clear must not hide a later persisted edit.
  if (unsaved && !(unsaved.text === '' && result?.ok
    && (result.draft?.revision ?? null) !== unsaved.revision)) {
    return { owner, text: unsaved.text, revision: unsaved.revision, editRevision: 1,
      saveState: result?.ok && (result.draft?.revision ?? null) !== unsaved.revision
        ? 'conflict' : unsaved.saveState };
  }
  return {
    owner, text: result?.ok ? result.draft?.text ?? '' : '',
    revision: result?.ok ? result.draft?.revision ?? null : null,
    editRevision: 0,
    saveState: result?.ok ? 'saved' : 'unavailable',
  };
}

/** Hydrate only on owner changes; edits persist synchronously without delayed replay. */
export function useChatTextDraft(sessionId: string | null) {
  const [stored, setStored] = useState(() => restore(sessionId));
  let state = stored;
  if (stored.owner.sessionId !== (sessionId ?? '') || !isChatDraftOwnerCurrent(stored.owner)) {
    state = restore(sessionId);
    setStored(state);
  }
  const current = useRef(state);
  current.current = state;
  const owner = state.owner;
  const update = useCallback((text: string, acknowledgeSend = false) => {
    if (current.current.owner !== owner || !isChatDraftOwnerCurrent(owner)) return;
    const previous = current.current;
    const result = writeChatDraft(owner, text, previous.revision);
    // Acknowledged text leaves the editor even if disk cleanup fails; newer drafts survive.
    const newer = acknowledgeSend && !result.ok && result.reason === 'conflict'
      ? readChatDraft(owner) : null;
    const next: State = {
      owner,
      text: newer?.ok ? newer.draft?.text ?? '' : text,
      revision: newer?.ok ? newer.draft?.revision ?? null
        : result.ok ? result.draft?.revision ?? null : previous.revision,
      editRevision: previous.editRevision + 1,
      saveState: result.ok || newer?.ok ? 'saved' : result.reason === 'conflict' ? 'conflict'
        : result.reason === 'too_large' ? 'unsaved' : 'unavailable',
    };
    if (next.saveState !== 'saved') rememberUnsavedChatDraft(owner, next.text, next.revision, next.saveState);
    else forgetUnsavedChatDraft(owner);
    current.current = next;
    setStored(next);
  }, [owner]);
  const setText = useCallback((text: string) => update(text), [update]);
  const clear = useCallback(() => update('', true), [update]);
  return { text: state.text, revision: state.revision, editRevision: state.editRevision,
    saveState: state.saveState,
    clearFailed: state.saveState !== 'saved' && state.text === '' && state.editRevision > 0,
    setText, clear };
}
