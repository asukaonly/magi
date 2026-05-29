import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { streamChatPreview, type PreviewTurn } from '../../api/modules/chatPreview';
import {
  personasApi,
  type PersonalityConfig,
  type PersonaGenerationStage,
  type SeedPreview,
} from '../../api/modules/personas';
import type { LLMConfig } from '../../api/modules/config';
import { PersonaPreviewStarterChips } from './PersonaPreviewStarterChips';

const MAX_USER_TURNS_PER_PERSONA = 5;

/**
 * An onboarding-generated (unsaved) persona. Lives in onboarding state until
 * the user finishes onboarding, at which point the parent persists it via
 * `personasApi.create`. The `slug` is a client-only id (e.g. `custom-1`).
 */
export interface CustomPersonaDraft {
  slug: string;
  name: string;
  description: string;
  config: PersonalityConfig;
}

export interface PersonaPreviewChatProps {
  previews: SeedPreview[];
  /**
   * The in-progress (unsaved) onboarding LLM config. Passed to the preview
   * endpoint as `llm_override` and to persona generation, so both work before
   * the user has persisted their selections / started the LLM runtime.
   */
  llmConfig?: LLMConfig;
  /**
   * Fires whenever the active persona changes (including the initial default).
   * The active persona in the rail *is* the selection — the parent's footer
   * "Next" button confirms it and advances.
   */
  onActiveSeedChange?: (seedSlug: string | null) => void;
  /** Custom drafts to re-hydrate (e.g. after an onboarding reload). */
  initialCustomPersonas?: CustomPersonaDraft[];
  /** Fires whenever the set of custom drafts changes, so the parent can persist them. */
  onCustomPersonasChange?: (drafts: CustomPersonaDraft[]) => void;
}

type TranscriptMap = Record<string, PreviewTurn[]>;

interface RailItem {
  slug: string;
  name: string;
  description: string;
  avatar?: string;
  isCustom: boolean;
  config?: PersonalityConfig;
}

/** Avatar with graceful fallback to the persona's initial when the image fails. */
function PreviewAvatar({ name, avatar }: { name: string; avatar?: string }): JSX.Element {
  const [failed, setFailed] = useState(false);
  const url = avatar ? personasApi.getAvatarUrl(avatar) : '';
  const initial = name.trim().charAt(0).toUpperCase() || '?';

  if (!url || failed) {
    return (
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#e6d7c5] text-sm font-semibold text-[#7d685a] dark:bg-[#5b4a3d] dark:text-[#f4eadf]">
        {initial}
      </div>
    );
  }
  return (
    <img
      src={url}
      alt=""
      onError={() => setFailed(true)}
      className="h-10 w-10 shrink-0 rounded-full object-cover"
    />
  );
}

export function PersonaPreviewChat({
  previews,
  llmConfig,
  onActiveSeedChange,
  initialCustomPersonas,
  onCustomPersonasChange,
}: PersonaPreviewChatProps): JSX.Element {
  const { t, i18n } = useTranslation('onboarding');
  const sortedPreviews = useMemo(
    () => [...previews].sort((a, b) => a.order - b.order),
    [previews],
  );

  const [customDrafts, setCustomDrafts] = useState<CustomPersonaDraft[]>(
    () => initialCustomPersonas ?? [],
  );
  const customCounterRef = useRef((initialCustomPersonas ?? []).length);

  const railItems = useMemo<RailItem[]>(
    () => [
      ...sortedPreviews.map((p) => ({
        slug: p.seed_slug,
        name: p.name,
        description: p.description,
        avatar: p.avatar,
        isCustom: false,
      })),
      ...customDrafts.map((d) => ({
        slug: d.slug,
        name: d.name,
        description: d.description,
        avatar: '',
        isCustom: true,
        config: d.config,
      })),
    ],
    [sortedPreviews, customDrafts],
  );

  const [activeSeed, setActiveSeed] = useState<string | null>(
    railItems[0]?.slug ?? null,
  );
  const [transcripts, setTranscripts] = useState<TranscriptMap>({});
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);

  // Custom-persona creation state.
  const [mode, setMode] = useState<'chat' | 'create'>('chat');
  const [customDescription, setCustomDescription] = useState('');
  const [generating, setGenerating] = useState(false);
  const [genStages, setGenStages] = useState<PersonaGenerationStage[]>([]);
  const [genError, setGenError] = useState<string | null>(null);

  // If the rail is empty on first render (async load), adopt the first item as
  // the default selection once items arrive.
  useEffect(() => {
    if (activeSeed === null && railItems.length > 0) {
      setActiveSeed(railItems[0].slug);
    }
  }, [activeSeed, railItems]);

  // Notify the parent of the current selection / drafts without depending on
  // the (unstable) callback identity — fire only when the value changes.
  const onActiveSeedChangeRef = useRef(onActiveSeedChange);
  onActiveSeedChangeRef.current = onActiveSeedChange;
  useEffect(() => {
    onActiveSeedChangeRef.current?.(activeSeed);
  }, [activeSeed]);

  const onCustomPersonasChangeRef = useRef(onCustomPersonasChange);
  onCustomPersonasChangeRef.current = onCustomPersonasChange;
  useEffect(() => {
    onCustomPersonasChangeRef.current?.(customDrafts);
  }, [customDrafts]);

  const activeItem = railItems.find((i) => i.slug === activeSeed);
  const activeTranscript = activeSeed ? transcripts[activeSeed] ?? [] : [];
  const userTurnCount = activeTranscript.filter((m) => m.role === 'user').length;
  const capReached = userTurnCount >= MAX_USER_TURNS_PER_PERSONA;

  const appendTurn = useCallback((seedSlug: string, turn: PreviewTurn) => {
    setTranscripts((prev) => {
      const list = prev[seedSlug] ?? [];
      return { ...prev, [seedSlug]: [...list, turn] };
    });
  }, []);

  const updateLastAssistantContent = useCallback(
    (seedSlug: string, deltaText: string) => {
      setTranscripts((prev) => {
        const list = prev[seedSlug] ?? [];
        const lastIdx = list.length - 1;
        if (lastIdx < 0 || list[lastIdx].role !== 'assistant') return prev;
        const updated: PreviewTurn = {
          role: 'assistant',
          content: list[lastIdx].content + deltaText,
        };
        return {
          ...prev,
          [seedSlug]: [...list.slice(0, lastIdx), updated],
        };
      });
    },
    [],
  );

  const send = useCallback(async () => {
    if (!activeSeed || !draft.trim() || busy || capReached) return;
    const userTurn: PreviewTurn = { role: 'user', content: draft.trim() };
    const seed = activeSeed;
    const snapshotHistory = transcripts[seed] ?? [];
    // A custom (unsaved) persona has no seed file — preview it inline.
    const personaOverride =
      activeItem?.isCustom && activeItem.config
        ? {
            name: activeItem.config.name,
            identity_statement: activeItem.config.identity_core.identity_statement,
            sentence_style: activeItem.config.idiolect.sentence_style,
          }
        : undefined;
    appendTurn(seed, userTurn);
    appendTurn(seed, { role: 'assistant', content: '' });
    setDraft('');
    setBusy(true);
    try {
      for await (const chunk of streamChatPreview({
        seed_slug: personaOverride ? undefined : seed,
        persona_override: personaOverride,
        history: snapshotHistory,
        message: userTurn,
        llm_override: llmConfig,
      })) {
        updateLastAssistantContent(seed, chunk);
      }
    } catch (err) {
      updateLastAssistantContent(seed, `\n[error: ${(err as Error).message}]`);
    } finally {
      setBusy(false);
    }
  }, [
    activeSeed,
    activeItem,
    draft,
    busy,
    capReached,
    transcripts,
    llmConfig,
    appendTurn,
    updateLastAssistantContent,
  ]);

  const handleChipPick = useCallback((prompt: string) => {
    setDraft(prompt);
  }, []);

  const handleGenerate = useCallback(async () => {
    const description = customDescription.trim();
    if (!description || generating) return;
    setGenerating(true);
    setGenError(null);
    setGenStages([]);
    try {
      const targetLanguage = (i18n.language || '').startsWith('zh') ? 'Chinese' : 'English';
      const resp = await personasApi.generateWithProgress(
        { description, target_language: targetLanguage, llm_override: llmConfig },
        (snapshot) => setGenStages(snapshot.stages ?? []),
      );
      const config = resp.data;
      if (!config) {
        throw new Error('generation returned no config');
      }
      customCounterRef.current += 1;
      const slug = `custom-${customCounterRef.current}`;
      const newDraft: CustomPersonaDraft = {
        slug,
        name: config.name || description,
        description: config.description || description,
        config,
      };
      setCustomDrafts((prev) => [...prev, newDraft]);
      setActiveSeed(slug);
      setCustomDescription('');
      setMode('chat');
    } catch (err) {
      setGenError((err as Error).message);
    } finally {
      setGenerating(false);
    }
  }, [customDescription, generating, i18n.language, llmConfig]);

  return (
    <div className="grid h-full grid-cols-[200px_1fr] gap-4">
      {/* Left: avatar rail — clicking selects the persona (the active one is
          confirmed by the footer "Next" button). */}
      <div className="flex flex-col gap-2 overflow-y-auto border-r border-[#e6d7c5] pr-2 dark:border-[#5b4a3d]">
        {railItems.map((p) => (
          <button
            key={p.slug}
            type="button"
            onClick={() => {
              setActiveSeed(p.slug);
              setMode('chat');
            }}
            aria-pressed={activeSeed === p.slug && mode === 'chat'}
            className={`flex items-center gap-3 rounded-lg px-3 py-2 text-left transition ${
              activeSeed === p.slug && mode === 'chat'
                ? 'bg-[#f4eadf] dark:bg-[#5b4a3d]'
                : 'hover:bg-[#fbf6ef] dark:hover:bg-[#3d2f25]'
            }`}
          >
            <PreviewAvatar name={p.name} avatar={p.avatar} />
            <div className="min-w-0">
              <div className="truncate text-sm font-medium">{p.name}</div>
              <div className="truncate text-xs text-[#7d685a] dark:text-[#c8b7a7]">
                {p.description}
              </div>
            </div>
          </button>
        ))}

        <button
          type="button"
          data-testid="persona-create-custom"
          onClick={() => {
            setMode('create');
            setGenError(null);
          }}
          aria-pressed={mode === 'create'}
          className={`flex items-center gap-3 rounded-lg border border-dashed border-[#d8c9b8] px-3 py-2 text-left text-sm text-[#7d685a] transition hover:bg-[#fbf6ef] dark:border-[#5b4a3d] dark:text-[#c8b7a7] dark:hover:bg-[#3d2f25] ${
            mode === 'create' ? 'bg-[#f4eadf] dark:bg-[#5b4a3d]' : ''
          }`}
        >
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-dashed border-[#d8c9b8] text-lg dark:border-[#5b4a3d]">
            +
          </span>
          <span className="truncate font-medium">{t('personaPreview.createCustom')}</span>
        </button>
      </div>

      {/* Right: either the preview chat or the custom-persona composer. */}
      {mode === 'create' ? (
        <div className="flex flex-col gap-3">
          <div className="flex-1 overflow-y-auto rounded-lg border border-[#e6d7c5] bg-white p-4 dark:border-[#5b4a3d] dark:bg-[#2a2018]">
            <h3 className="text-sm font-medium">{t('personaPreview.createCustomTitle')}</h3>
            <p className="mt-1 text-xs text-[#7d685a] dark:text-[#c8b7a7]">
              {t('personaPreview.createCustomHint')}
            </p>
            <textarea
              data-testid="persona-custom-description"
              value={customDescription}
              onChange={(e) => setCustomDescription(e.target.value)}
              placeholder={t('personaPreview.customDescriptionPlaceholder')}
              disabled={generating}
              rows={3}
              className="mt-3 w-full rounded-md border border-[#d8c9b8] bg-white px-3 py-2 text-sm dark:border-[#5b4a3d] dark:bg-[#3d2f25]"
            />

            {generating && (
              <div
                data-testid="persona-generation-progress"
                className="mt-3 rounded-md border border-[#e6d7c5] bg-[#fbf6ef] p-3 dark:border-[#5b4a3d] dark:bg-[#3d2f25]"
              >
                <p className="text-xs font-medium text-[#7d685a] dark:text-[#c8b7a7]">
                  {t('personaPreview.generating')}
                </p>
                {genStages.length > 0 && (
                  <ul className="mt-2 space-y-1">
                    {genStages.map((s) => (
                      <li
                        key={s.stage_id}
                        className="flex items-center gap-2 text-xs text-[#7d685a] dark:text-[#c8b7a7]"
                      >
                        <span aria-hidden>
                          {s.status === 'completed' ? '✓' : s.status === 'running' ? '…' : '·'}
                        </span>
                        <span>{s.label || s.stage_id}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            {genError && (
              <p className="mt-3 text-xs text-red-600 dark:text-red-400">
                {t('personaPreview.generationFailed')}: {genError}
              </p>
            )}
          </div>

          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={() => {
                setMode('chat');
                setGenError(null);
              }}
              disabled={generating}
              className="rounded-md px-4 py-2 text-sm text-[#7d685a] underline disabled:opacity-50 dark:text-[#c8b7a7]"
            >
              {t('personaPreview.cancelCreate')}
            </button>
            <button
              type="button"
              data-testid="persona-custom-generate"
              onClick={handleGenerate}
              disabled={!customDescription.trim() || generating}
              className="rounded-md bg-[#35261f] px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-[#f4eadf] dark:text-[#35261f]"
            >
              {generating ? t('personaPreview.generating') : t('personaPreview.generate')}
            </button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <div className="flex-1 overflow-y-auto rounded-lg border border-[#e6d7c5] bg-white p-4 dark:border-[#5b4a3d] dark:bg-[#2a2018]">
            {activeTranscript.length === 0 && (
              <p className="text-sm text-[#7d685a] dark:text-[#c8b7a7]">
                {t('personaPreview.emptyHint')}
              </p>
            )}
            {activeTranscript.map((turn, idx) => (
              <div
                key={idx}
                className={`mb-2 ${turn.role === 'user' ? 'text-right' : 'text-left'}`}
              >
                <span
                  className={`inline-block max-w-[80%] rounded-2xl px-3 py-2 text-sm ${
                    turn.role === 'user'
                      ? 'bg-[#35261f] text-white dark:bg-[#f4eadf] dark:text-[#35261f]'
                      : 'bg-[#f4eadf] text-[#35261f] dark:bg-[#5b4a3d] dark:text-[#f4eadf]'
                  }`}
                >
                  {turn.content}
                </span>
              </div>
            ))}
          </div>

          <PersonaPreviewStarterChips onPick={handleChipPick} />

          <div className="flex items-center gap-2">
            <input
              type="text"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder={t('personaPreview.composerPlaceholder')}
              disabled={capReached}
              className="flex-1 rounded-md border border-[#d8c9b8] bg-white px-3 py-2 text-sm dark:border-[#5b4a3d] dark:bg-[#3d2f25]"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
            />
            <button
              type="button"
              onClick={send}
              disabled={!draft.trim() || busy || capReached}
              className="rounded-md bg-[#35261f] px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-[#f4eadf] dark:text-[#35261f]"
            >
              {t('personaPreview.send')}
            </button>
          </div>

          {capReached && (
            <p className="text-xs text-[#7d685a] dark:text-[#c8b7a7]">
              {t('personaPreview.capReached')}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
