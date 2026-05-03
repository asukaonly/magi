/**
 * Composer @-mention picker state.
 *
 * Listens for `@` typed at a word boundary in the composer textarea, opens a
 * picker, and lets the user search MCP resources. Selecting one strips the
 * trailing `@query` token from the input and adds an `mcp_resource` draft.
 *
 * Keyboard: ↑/↓ navigate, Enter selects, Esc closes. Click outside also
 * closes.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { mcpApi, type MCPResource } from '@/api';
import { fuzzyScore } from '@/lib/fuzzyMatch';
import { MRUCache } from '@/lib/mruCache';
import type { DraftMcpResourceAttachment } from './useChatDraftAttachments';

const MENTION_TRIGGER = '@';
const mruCache = new MRUCache('mentions');

const mruKey = (item: { serverId: string; uri: string }): string =>
  `${item.serverId}|${item.uri}`;

export type MentionItem = {
  serverId: string;
  uri: string;
  name: string;
  description?: string;
  mimeType?: string;
};

type MentionState =
  | { open: false }
  | {
    open: true;
    /** Current text after the `@` that anchors the picker. */
    query: string;
    /** Index of `@` in the textarea value (so we can replace the token). */
    triggerIndex: number;
    activeIndex: number;
  };

type AddDraftFn = (
  resource: Omit<DraftMcpResourceAttachment, 'id' | 'kind'>,
) => void;

interface UseChatComposerMentionsOptions {
  inputValue: string;
  setInputValue: (value: string) => void;
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
  addMcpResourceDraft: AddDraftFn;
}

const isWordBoundaryBefore = (text: string, idx: number): boolean => {
  if (idx <= 0) return true;
  const ch = text[idx - 1];
  return /[\s\n\r\t]/.test(ch);
};

const resourceToItem = (resource: MCPResource): MentionItem => ({
  serverId: resource.server_id,
  uri: resource.uri,
  name: typeof resource.name === 'string' && resource.name
    ? resource.name
    : resource.uri,
  description: typeof resource.description === 'string' ? resource.description : undefined,
  mimeType: resource.mimeType,
});

const scoreItem = (item: MentionItem, query: string): number => {
  const name = fuzzyScore(query, item.name);
  const uri = fuzzyScore(query, item.uri);
  const server = fuzzyScore(query, item.serverId);
  return Math.max(name, uri, Math.floor(server * 0.6));
};

export function useChatComposerMentions({
  inputValue,
  setInputValue,
  textareaRef,
  addMcpResourceDraft,
}: UseChatComposerMentionsOptions) {
  const [state, setState] = useState<MentionState>({ open: false });
  const [resources, setResources] = useState<MentionItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fetchedAtRef = useRef<number>(0);

  const close = useCallback(() => {
    setState({ open: false });
  }, []);

  const fetchResources = useCallback(async (force = false) => {
    const now = Date.now();
    if (!force && now - fetchedAtRef.current < 5_000 && resources.length > 0) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const list = await mcpApi.listResources();
      setResources(list.map(resourceToItem));
      fetchedAtRef.current = now;
    } catch (exc: any) {
      setError(exc?.message ?? String(exc));
    } finally {
      setLoading(false);
    }
  }, [resources.length]);

  /**
   * Detect mention activation/deactivation in response to keystrokes. Should
   * be called from the textarea's `onChange` flow with the value *after* the
   * change applies. Cursor position is read from the textarea ref.
   */
  const onValueChange = useCallback(
    (nextValue: string) => {
      const textarea = textareaRef.current;
      const cursor = textarea?.selectionStart ?? nextValue.length;

      // Find the closest preceding `@` that anchors a mention.
      let triggerIdx = -1;
      for (let i = cursor - 1; i >= 0; i -= 1) {
        const ch = nextValue[i];
        if (ch === MENTION_TRIGGER) {
          if (isWordBoundaryBefore(nextValue, i)) {
            triggerIdx = i;
          }
          break;
        }
        if (/[\s\n\r\t]/.test(ch)) {
          break;
        }
      }

      if (triggerIdx === -1) {
        if (state.open) close();
        return;
      }

      const query = nextValue.slice(triggerIdx + 1, cursor);
      if (/\s/.test(query)) {
        if (state.open) close();
        return;
      }

      if (!state.open || state.triggerIndex !== triggerIdx) {
        setState({
          open: true,
          query,
          triggerIndex: triggerIdx,
          activeIndex: 0,
        });
        void fetchResources();
      } else if (state.query !== query) {
        setState({
          open: true,
          query,
          triggerIndex: triggerIdx,
          activeIndex: 0,
        });
      }
    },
    [close, fetchResources, state, textareaRef],
  );

  const filteredItems = useMemo(() => {
    if (!state.open) return [];
    const scored = resources
      .map((item) => ({
        item,
        score: scoreItem(item, state.query),
        recency: mruCache.recencyRank(mruKey(item)),
      }))
      .filter(({ score }) => score > 0);
    scored.sort((a, b) => {
      if (b.score !== a.score) return b.score - a.score;
      return b.recency - a.recency;
    });
    return scored.map(({ item }) => item).slice(0, 50);
  }, [resources, state]);

  const select = useCallback(
    (item: MentionItem) => {
      if (!state.open) return;
      const before = inputValue.slice(0, state.triggerIndex);
      const textarea = textareaRef.current;
      const cursor = textarea?.selectionStart ?? inputValue.length;
      const after = inputValue.slice(cursor);
      // Strip the @query token entirely; the chip lives in the attachments strip.
      const trimmedBefore = before.replace(/[ \t]+$/, '');
      const trimmedAfter = after.replace(/^[ \t]+/, '');
      const joiner = trimmedBefore && trimmedAfter ? ' ' : '';
      const next = `${trimmedBefore}${joiner}${trimmedAfter}`;
      setInputValue(next);
      addMcpResourceDraft({
        serverId: item.serverId,
        uri: item.uri,
        name: item.name,
        mimeType: item.mimeType,
        description: item.description,
      });
      mruCache.recordUse(mruKey(item));
      close();
      // Restore focus to the textarea after the picker closes.
      requestAnimationFrame(() => {
        textareaRef.current?.focus();
        const caret = trimmedBefore.length + (joiner ? 1 : 0);
        textareaRef.current?.setSelectionRange(caret, caret);
      });
    },
    [addMcpResourceDraft, close, inputValue, setInputValue, state, textareaRef],
  );

  /** Keyboard handler — call before delegating to send-on-Enter logic. */
  const onKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLTextAreaElement>): boolean => {
      if (!state.open) return false;
      if (event.key === 'Escape') {
        event.preventDefault();
        close();
        return true;
      }
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        setState({
          ...state,
          activeIndex: Math.min(state.activeIndex + 1, Math.max(0, filteredItems.length - 1)),
        });
        return true;
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault();
        setState({
          ...state,
          activeIndex: Math.max(state.activeIndex - 1, 0),
        });
        return true;
      }
      if (event.key === 'Home') {
        event.preventDefault();
        setState({ ...state, activeIndex: 0 });
        return true;
      }
      if (event.key === 'End') {
        event.preventDefault();
        setState({
          ...state,
          activeIndex: Math.max(0, filteredItems.length - 1),
        });
        return true;
      }
      if (event.key === 'Enter' || event.key === 'Tab') {
        const item = filteredItems[state.activeIndex];
        if (item) {
          event.preventDefault();
          select(item);
          return true;
        }
      }
      return false;
    },
    [close, filteredItems, select, state],
  );

  const setActiveIndex = useCallback((index: number) => {
    setState((current) => {
      if (!current.open) return current;
      return { ...current, activeIndex: index };
    });
  }, []);

  useEffect(() => {
    if (!state.open) return undefined;
    const handler = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest('[data-mention-picker]')) return;
      if (target?.closest('[data-testid="chat-composer-input"]')) return;
      close();
    };
    window.addEventListener('mousedown', handler);
    return () => window.removeEventListener('mousedown', handler);
  }, [close, state.open]);

  return {
    state,
    items: filteredItems,
    loading,
    error,
    onValueChange,
    onKeyDown,
    select,
    close,
    setActiveIndex,
  };
}
