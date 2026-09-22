import { useCallback, useRef, useState } from 'react';
import {
  captureChatDraftOwner, isChatDraftOwnerCurrent, readChatDraft, writeChatDraft,
  readUnsavedChatDraft, rememberUnsavedChatDraft,
  type ChatDraftOwner,
} from '@/runtime/chat-draft-storage';

export type ChatDraftSaveState = 'saved' | 'unsaved' | 'conflict' | 'unavailable';
type State = { owner: ChatDraftOwner; text: string; revision: string | null; saveState: ChatDraftSaveState };

function restore(sessionId: string | null): State {
  const owner = captureChatDraftOwner(sessionId ?? '');
  const result = sessionId ? readChatDraft(owner) : null;
  const unsaved = sessionId ? readUnsavedChatDraft(owner) : undefined;
  if (unsaved) {
    return { owner, text: unsaved.text, revision: unsaved.revision,
      saveState: result?.ok && (result.draft?.revision ?? null) !== unsaved.revision
        ? 'conflict' : unsaved.saveState };
  }
  return {
    owner, text: result?.ok ? result.draft?.text ?? '' : '',
    revision: result?.ok ? result.draft?.revision ?? null : null,
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
  const update = useCallback((text: string, clearOnlyIfSaved = false) => {
    if (current.current.owner !== owner || !isChatDraftOwnerCurrent(owner)) return;
    const previous = current.current;
    const result = writeChatDraft(owner, text, previous.revision);
    const next: State = {
      owner,
      text: !result.ok && clearOnlyIfSaved ? previous.text : text,
      revision: result.ok ? result.draft?.revision ?? null : previous.revision,
      saveState: result.ok ? 'saved' : result.reason === 'conflict' ? 'conflict'
        : result.reason === 'too_large' ? 'unsaved' : 'unavailable',
    };
    if (next.saveState !== 'saved') rememberUnsavedChatDraft(owner, next.text, next.revision, next.saveState);
    current.current = next;
    setStored(next);
  }, [owner]);
  const setText = useCallback((text: string) => update(text), [update]);
  const clear = useCallback(() => update('', true), [update]);
  return { text: state.text, revision: state.revision, saveState: state.saveState, setText, clear };
}
