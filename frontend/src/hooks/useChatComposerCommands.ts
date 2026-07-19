/**
 * Composer /-command picker state.
 *
 * Activates only when `/` is at the very start of the textarea (no
 * preceding non-whitespace) — this is the same UX as Claude Code, Discord
 * slash, etc. The picker merges three sources:
 *
 * - **internal** commands (clear / new-session / cancel / help) — these are
 *   handed to the page when selected; destructive actions may request
 *   confirmation before they run.
 * - **tool** commands fetched from `GET /api/commands` — these open a
 *   parameter dialog before running.
 *
 * Selecting a command clears the textarea (no `/cmd` left behind — the
 * invocation will surface as a chat message instead).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type React from 'react';
import { useTranslation } from 'react-i18next';
import { commandsApi, type CommandDescriptor, type SkillCommandDescriptor } from '@/api';
import { fuzzyScore } from '@/lib/fuzzyMatch';
import { MRUCache } from '@/lib/mruCache';

const mruCache = new MRUCache('commands');

export type SlashCommandSource = 'internal' | 'tool' | 'skill';

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

const INTERNAL_COMMANDS: Array<
  Omit<Extract<SlashCommandItem, { source: 'internal' }>, 'description'> & {
    descriptionKey: string;
    descriptionFallback: string;
  }
> = [
  {
    source: 'internal',
    name: 'clear',
    descriptionKey: 'chat.commands.internal.clear',
    descriptionFallback: 'Clear this chat and its related memories',
    action: 'clear',
    dangerous: true,
  },
  {
    source: 'internal',
    name: 'new-session',
    descriptionKey: 'chat.commands.internal.newSession',
    descriptionFallback: 'Start a new chat session',
    action: 'new-session',
  },
  {
    source: 'internal',
    name: 'cancel',
    descriptionKey: 'chat.commands.internal.cancel',
    descriptionFallback: 'Cancel the current run',
    action: 'cancel',
  },
  {
    source: 'internal',
    name: 'help',
    descriptionKey: 'chat.commands.internal.help',
    descriptionFallback: 'List available commands',
    action: 'help',
  },
];

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

interface UseChatComposerCommandsOptions {
  setInputValue: (value: string) => void;
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
  allowInlineSkills?: boolean;
  onPickInternal: (action: SlashInternalAction) => void | Promise<void>;
  onPickTool: (descriptor: CommandDescriptor) => void;
  onPickSkill: (descriptor: SkillCommandDescriptor) => void;
}

export function useChatComposerCommands({
  setInputValue,
  textareaRef,
  allowInlineSkills = true,
  onPickInternal,
  onPickTool,
  onPickSkill,
}: UseChatComposerCommandsOptions) {
  const { t } = useTranslation('app');
  const [state, setState] = useState<SlashState>({ open: false });
  const [tools, setTools] = useState<CommandDescriptor[]>([]);
  const [skills, setSkills] = useState<SkillCommandDescriptor[]>([]);
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
      const [toolList, skillList] = await Promise.all([
        commandsApi.list().catch(() => [] as CommandDescriptor[]),
        commandsApi.listSkills().catch(() => [] as SkillCommandDescriptor[]),
      ]);
      setTools(toolList);
      setSkills(skillList);
      fetchedAtRef.current = now;
    } catch (exc: any) {
      setError(exc?.message ?? String(exc));
    } finally {
      setLoading(false);
    }
  }, []);

  const items = useMemo<SlashCommandItem[]>(() => {
    if (!state.open) return [];
    const merged: SlashCommandItem[] = [
      ...INTERNAL_COMMANDS.map(({ descriptionKey, descriptionFallback, ...command }) => ({
        ...command,
        description: t(descriptionKey, { defaultValue: descriptionFallback }),
      })),
      ...tools.map<SlashCommandItem>((t) => ({
        source: 'tool',
        name: t.name,
        description: t.description,
        dangerous: t.dangerous,
        descriptor: t,
      })),
      ...skills
        .filter((skill) => (
          allowInlineSkills || skill.context_mode === 'fork'
        ))
        .map<SlashCommandItem>((skill) => ({
          source: 'skill',
          name: skill.name,
          description: skill.description,
          argumentHint: skill.argument_hint ?? undefined,
          contextMode: skill.context_mode ?? undefined,
          descriptor: skill,
        })),
    ];
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
      // Within equal score+recency: internals first, then skills, then tools, alpha.
      const sourceRank = (s: SlashCommandSource) =>
        s === 'internal' ? 0 : s === 'skill' ? 1 : 2;
      const aRank = sourceRank(a.item.source);
      const bRank = sourceRank(b.item.source);
      if (aRank !== bRank) return aRank - bRank;
      return a.item.name.localeCompare(b.item.name);
    });
    return scored.map(({ item }) => item);
  }, [allowInlineSkills, skills, state, t, tools]);

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
      // Strip the textarea — the invocation surface is the chat timeline.
      setInputValue('');
      mruCache.recordUse(mruKey(item));
      close();
      if (item.source === 'internal') {
        void onPickInternal(item.action);
      } else if (item.source === 'tool') {
        onPickTool(item.descriptor);
      } else {
        onPickSkill(item.descriptor);
      }
      requestAnimationFrame(() => {
        textareaRef.current?.focus();
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
