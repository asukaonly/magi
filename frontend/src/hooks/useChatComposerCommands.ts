/**
 * Composer /-command picker state.
 *
 * Activates only when `/` is at the very start of the textarea (no
 * preceding non-whitespace) — this is the same UX as Claude Code, Discord
 * slash, etc. The picker consumes the canonical backend catalog: client and
 * control commands stay local, tool commands use the command runner, and
 * skills create typed invocations.
 *
 * Selecting a command consumes only the active slash query. Any existing draft
 * remains in the textarea; reasoning modifiers are inserted at its start while
 * action, tool, and skill commands execute without discarding unrelated text.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type React from 'react';
import { useTranslation } from 'react-i18next';
import { commandsApi, type CommandDescriptor, type SkillCommandDescriptor } from '@/api';
import type { ReasoningPreference } from '@/domain/chat/reasoning';
import { fuzzyScore } from '@/lib/fuzzyMatch';
import { MRUCache } from '@/lib/mruCache';

const mruCache = new MRUCache('commands');

export type SlashCommandSource = 'internal' | 'modifier' | 'tool' | 'skill';

export type SlashInternalAction =
  | 'clear'
  | 'new-session'
  | 'cancel'
  | 'help';

export type SlashCommandItem =
  | {
    source: 'internal';
    name: string;
    description: string;
    action: SlashInternalAction;
    icon?: string;
    dangerous?: boolean;
    descriptor?: CommandDescriptor;
  }
  | {
    source: 'modifier';
    name: string;
    description: string;
    preference: ReasoningPreference;
    dangerous?: false;
    descriptor: CommandDescriptor;
  }
  | {
    source: 'tool';
    name: string;
    description: string;
    dangerous: boolean;
    descriptor: CommandDescriptor;
  }
  | {
    source: 'skill';
    name: string;
    description: string;
    argumentHint?: string;
    contextMode?: string;
    descriptor: SkillCommandDescriptor;
  };

type SlashState =
  | { open: false }
  | {
    open: true;
    /** The text after the leading `/`. */
    query: string;
    activeIndex: number;
  };

const CLIENT_ACTIONS = new Set<SlashInternalAction>([
  'clear',
  'new-session',
  'cancel',
  'help',
]);

const isReasoningPreference = (value: unknown): value is ReasoningPreference => (
  value === 'auto' || value === 'fast' || value === 'deep'
);

const mruKey = (item: SlashCommandItem): string => `${item.source}|${item.name}`;

const scoreItem = (item: SlashCommandItem, query: string): number => {
  const name = fuzzyScore(query, item.name);
  const desc = Math.floor(fuzzyScore(query, item.description) * 0.5);
  return Math.max(name, desc);
};

const isAtMessageStart = (value: string, cursor: number): boolean => {
  // We want `/` to be the first non-whitespace character of the textarea.
  // Whitespace before is fine; any non-whitespace before is not.
  const before = value.slice(0, cursor);
  // Cursor must come right after a `/` token: the trailing chars from the
  // last `/` to the cursor must be alphanumeric/-/_ to count as the query.
  const slashIdx = before.lastIndexOf('/');
  if (slashIdx === -1) return false;
  const prefix = before.slice(0, slashIdx);
  if (prefix.trim().length > 0) return false;
  const between = before.slice(slashIdx + 1);
  if (/[\s\n]/.test(between)) return false;
  return true;
};

const removeActiveSlashQuery = (
  value: string,
  cursor: number,
): { value: string; cursor: number } => {
  const safeCursor = Math.max(0, Math.min(cursor, value.length));
  if (!isAtMessageStart(value, safeCursor)) {
    return { value, cursor: safeCursor };
  }

  const slashIndex = value.lastIndexOf('/', Math.max(0, safeCursor - 1));
  const remainingValue = `${value.slice(0, slashIndex)}${value.slice(safeCursor)}`
    .trimStart();
  return { value: remainingValue, cursor: 0 };
};

interface UseChatComposerCommandsOptions {
  setInputValue: (value: string) => void;
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
  allowInlineSkills?: boolean;
  allowMessageModifiers?: boolean;
  allowCancelAction?: boolean;
  onPickInternal: (action: SlashInternalAction) => void | Promise<void>;
  onPickTool: (descriptor: CommandDescriptor) => void;
  onPickSkill: (descriptor: SkillCommandDescriptor) => void;
}

export function useChatComposerCommands({
  setInputValue,
  textareaRef,
  allowInlineSkills = true,
  allowMessageModifiers = true,
  allowCancelAction = false,
  onPickInternal,
  onPickTool,
  onPickSkill,
}: UseChatComposerCommandsOptions) {
  const { t } = useTranslation('app');
  const [state, setState] = useState<SlashState>({ open: false });
  const [catalog, setCatalog] = useState<CommandDescriptor[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fetchedAtRef = useRef<number>(0);

  const close = useCallback(() => setState({ open: false }), []);

  const fetchTools = useCallback(async (force = false) => {
    const now = Date.now();
    if (!force && now - fetchedAtRef.current < 5_000) return;
    setLoading(true);
    setError(null);
    try {
      setCatalog(await commandsApi.list());
      fetchedAtRef.current = now;
    } catch (exc: any) {
      setError(exc?.message ?? String(exc));
    } finally {
      setLoading(false);
    }
  }, []);

  const items = useMemo<SlashCommandItem[]>(() => {
    if (!state.open) return [];
    const description = (
      descriptor: CommandDescriptor | SkillCommandDescriptor,
    ) => (
      descriptor.description_key
        ? t(descriptor.description_key, { defaultValue: descriptor.description })
        : descriptor.description
    );
    const merged = catalog.flatMap<SlashCommandItem>((descriptor) => {
      if ((descriptor.visibility ?? 'composer') !== 'composer') {
        return [];
      }
      if (descriptor.kind === 'tool') {
        return [{
          source: 'tool',
          name: descriptor.name,
          description: description(descriptor),
          dangerous: descriptor.dangerous,
          descriptor,
        }];
      }
      if (descriptor.kind === 'skill') {
        if (!allowInlineSkills && descriptor.context_mode !== 'fork') {
          return [];
        }
        const skill = descriptor as SkillCommandDescriptor;
        return [{
          source: 'skill',
          name: skill.name,
          description: description(skill),
          argumentHint: skill.argument_hint ?? undefined,
          contextMode: skill.context_mode ?? undefined,
          descriptor: skill,
        }];
      }
      if (
        allowMessageModifiers
        && isReasoningPreference(descriptor.reasoning_preference)
      ) {
        return [{
          source: 'modifier',
          name: descriptor.name,
          description: description(descriptor),
          preference: descriptor.reasoning_preference,
          descriptor,
        }];
      }
      if (descriptor.name === 'cancel' && !allowCancelAction) {
        return [];
      }
      if (!CLIENT_ACTIONS.has(descriptor.name as SlashInternalAction)) {
        return [];
      }
      return [{
        source: 'internal',
        name: descriptor.name,
        description: description(descriptor),
        action: descriptor.name as SlashInternalAction,
        dangerous: descriptor.dangerous,
        descriptor,
      }];
    });
    const scored = merged
      .map((item) => ({
        item,
        score: scoreItem(item, state.query),
        recency: mruCache.recencyRank(mruKey(item)),
      }))
      .filter(({ score }) => score > 0);
    scored.sort((a, b) => {
      if (b.score !== a.score) return b.score - a.score;
      if (b.recency !== a.recency) return b.recency - a.recency;
      // Within equal score+recency: local controls first, then skills and tools.
      const sourceRank = (s: SlashCommandSource) =>
        s === 'internal' || s === 'modifier' ? 0 : s === 'skill' ? 1 : 2;
      const aRank = sourceRank(a.item.source);
      const bRank = sourceRank(b.item.source);
      if (aRank !== bRank) return aRank - bRank;
      return a.item.name.localeCompare(b.item.name);
    });
    return scored.map(({ item }) => item);
  }, [allowCancelAction, allowInlineSkills, allowMessageModifiers, catalog, state, t]);

  const onValueChange = useCallback(
    (nextValue: string) => {
      const textarea = textareaRef.current;
      const cursor = textarea?.selectionStart ?? nextValue.length;

      if (!isAtMessageStart(nextValue, cursor)) {
        if (state.open) close();
        return;
      }
      const slashIdx = nextValue.lastIndexOf('/', cursor - 1);
      const query = nextValue.slice(slashIdx + 1, cursor);

      if (!state.open) {
        setState({ open: true, query, activeIndex: 0 });
        void fetchTools();
      } else if (state.query !== query) {
        setState({ open: true, query, activeIndex: 0 });
      }
    },
    [close, fetchTools, state, textareaRef],
  );

  const select = useCallback(
    (item: SlashCommandItem) => {
      mruCache.recordUse(mruKey(item));
      close();
      const textarea = textareaRef.current;
      const currentValue = textarea?.value ?? '';
      const currentCursor = textarea?.selectionStart ?? currentValue.length;
      const remainingDraft = removeActiveSlashQuery(currentValue, currentCursor);
      let nextValue = remainingDraft.value;
      let nextCursor = remainingDraft.cursor;
      if (item.source === 'modifier') {
        const prefix = `/${item.preference} `;
        nextValue = `${prefix}${remainingDraft.value}`;
        nextCursor = prefix.length;
      }
      setInputValue(nextValue);
      if (item.source === 'internal') {
        void onPickInternal(item.action);
      } else if (item.source === 'tool') {
        onPickTool(item.descriptor);
      } else if (item.source === 'skill') {
        onPickSkill(item.descriptor);
      }
      requestAnimationFrame(() => {
        const nextTextarea = textareaRef.current;
        nextTextarea?.focus();
        nextTextarea?.setSelectionRange(nextCursor, nextCursor);
      });
    },
    [close, onPickInternal, onPickSkill, onPickTool, setInputValue, textareaRef],
  );

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
          activeIndex: Math.min(state.activeIndex + 1, Math.max(0, items.length - 1)),
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
        setState({ ...state, activeIndex: Math.max(0, items.length - 1) });
        return true;
      }
      if (event.key === 'Enter' || event.key === 'Tab') {
        const item = items[state.activeIndex];
        if (item) {
          event.preventDefault();
          select(item);
          return true;
        }
      }
      return false;
    },
    [close, items, select, state],
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
      if (target?.closest('[data-slash-picker]')) return;
      if (target?.closest('[data-testid="chat-composer-input"]')) return;
      close();
    };
    window.addEventListener('mousedown', handler);
    return () => window.removeEventListener('mousedown', handler);
  }, [close, state.open]);

  return {
    state,
    items,
    loading,
    error,
    onValueChange,
    onKeyDown,
    select,
    close,
    setActiveIndex,
  };
}
