import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useReducedMotion } from 'framer-motion';
import { CheckCircle2, Circle, Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
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
 * An onboarding-generated persona draft with its final stable registry ID.
 * The parent persists the draft before attempting registry creation.
 */
export interface CustomPersonaDraft {
  personaId: string;
  slug: string;
  name: string;
  description: string;
  config: PersonalityConfig;
}

export interface PersonaPreviewChatProps {
  previews: SeedPreview[];
  /** Whether builtin seed previews are still loading. */
  previewsLoading: boolean;
  /** The persona slug selected by the parent onboarding flow. */
  activeSeed: string | null;
  /**
   * Seed locale ("zh" / "en") the previews were loaded with — forwarded to the
   * preview endpoint so a seed_slug resolves against the right preset folder.
   */
  locale?: string;
  /**
   * The in-progress (unsaved) onboarding LLM config. Passed to the preview
   * endpoint as `llm_override` and to persona generation, so both work before
   * the user has persisted their selections / started the LLM runtime.
   */
  llmConfig?: LLMConfig;
  /** Requests a selection change from the parent onboarding flow. */
  onActiveSeedChange: (seedSlug: string | null) => void;
  /** Disables all persona interactions while the selection is being confirmed. */
  disabled: boolean;
  /** Persistent confirmation failure shown until retry or selection change. */
  confirmationError: string | null;
  /** Custom drafts to re-hydrate (e.g. after an onboarding reload). */
  initialCustomPersonas?: CustomPersonaDraft[];
  /** Fires whenever the set of custom drafts changes, so the parent can persist them. */
  onCustomPersonasChange?: (drafts: CustomPersonaDraft[]) => void;
  /**
   * Fires when persona generation starts (true) / finishes (false), so the
   * parent can disable step navigation while a generation is in flight.
   */
  onGeneratingChange?: (generating: boolean) => void;
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

function stageStatusIcon(status: string, shouldReduceMotion: boolean): JSX.Element {
  if (status === 'completed') {
    return <CheckCircle2 className="h-4 w-4 text-primary" aria-hidden="true" />;
  }
  if (status === 'running') {
    return (
      <Loader2
        data-testid="persona-generation-stage-spinner"
        className={cn('h-4 w-4 text-primary', !shouldReduceMotion && 'animate-spin')}
        aria-hidden="true"
      />
    );
  }
  return <Circle className="h-3.5 w-3.5 text-muted-foreground/45" aria-hidden="true" />;
}

/** Avatar with graceful fallback to the persona's initial when the image fails. */
function PreviewAvatar({ name, avatar }: { name: string; avatar?: string }): JSX.Element {
  const [failed, setFailed] = useState(false);
  const url = avatar ? personasApi.getAvatarUrl(avatar) : '';
  const initial = name.trim().charAt(0).toUpperCase() || '?';

  if (!url || failed) {
    return (
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-muted text-sm font-semibold text-muted-foreground">
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

/**
 * Three-dot "typing…" animation shown inside an assistant bubble while we wait
 * for the preview stream's first chunk (otherwise the empty bubble reads as a
 * frozen UI). Reuses the global `magiPendingDot` keyframes and honors
 * reduced-motion by holding the dots static.
 */
function TypingDots({
  shouldReduceMotion,
  label,
}: {
  shouldReduceMotion: boolean;
  label: string;
}): JSX.Element {
  return (
    <span className="flex items-center gap-1.5 py-0.5" role="status" aria-label={label}>
      {[0, 180, 360].map((delay) => (
        <span
          key={delay}
          aria-hidden
          className="block h-1.5 w-1.5 rounded-full bg-muted-foreground/70"
          style={
            shouldReduceMotion
              ? undefined
              : { animation: `magiPendingDot 1.2s ease-in-out ${delay}ms infinite` }
          }
        />
      ))}
    </span>
  );
}

export function PersonaPreviewChat({
  previews,
  previewsLoading,
  activeSeed,
  locale,
  llmConfig,
  onActiveSeedChange,
  disabled,
  confirmationError,
  initialCustomPersonas,
  onCustomPersonasChange,
  onGeneratingChange,
}: PersonaPreviewChatProps): JSX.Element {
  const { t, i18n } = useTranslation('onboarding');
  const shouldReduceMotion = useReducedMotion() ?? false;
  const sortedPreviews = useMemo(
    () => [...previews].sort((a, b) => a.order - b.order),
    [previews],
  );

  const [customDrafts, setCustomDrafts] = useState<CustomPersonaDraft[]>(
    () => initialCustomPersonas ?? [],
  );

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

  const [transcripts, setTranscripts] = useState<TranscriptMap>({});
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);

  // Custom-persona creation state.
  const [mode, setMode] = useState<'chat' | 'create'>('chat');
  const [customDescription, setCustomDescription] = useState('');
  const [generating, setGenerating] = useState(false);
  const [genStages, setGenStages] = useState<PersonaGenerationStage[]>([]);
  const [genError, setGenError] = useState<string | null>(null);

  // An empty rail can be a temporary async loading state, so it must not clear
  // or replace the parent's selection. Once a non-empty rail arrives, request
  // a fallback only when the saved selection is no longer available.
  useEffect(() => {
    if (
      !previewsLoading &&
      !disabled &&
      railItems.length > 0 &&
      !railItems.some((item) => item.slug === activeSeed)
    ) {
      onActiveSeedChange(railItems[0].slug);
    }
  }, [activeSeed, disabled, onActiveSeedChange, previewsLoading, railItems]);

  const onGeneratingChangeRef = useRef(onGeneratingChange);
  onGeneratingChangeRef.current = onGeneratingChange;
  useEffect(() => {
    onGeneratingChangeRef.current?.(generating);
  }, [generating]);

  const activeItem = railItems.find((i) => i.slug === activeSeed);
  const activeTranscript = activeSeed ? transcripts[activeSeed] ?? [] : [];
  const userTurnCount = activeTranscript.filter((m) => m.role === 'user').length;
  const capReached = userTurnCount >= MAX_USER_TURNS_PER_PERSONA;
  const getGenerationStageLabel = useCallback(
    (stage: PersonaGenerationStage) =>
      t(`personaPreview.generationStages.${stage.stage_id}`, {
        defaultValue: stage.label || stage.stage_id,
      }),
    [t],
  );

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
    if (disabled || !activeSeed || !draft.trim() || busy || capReached) return;
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
        locale,
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
    disabled,
    draft,
    busy,
    capReached,
    transcripts,
    locale,
    llmConfig,
    appendTurn,
    updateLastAssistantContent,
  ]);

  const handleChipPick = useCallback((prompt: string) => {
    setDraft(prompt);
  }, []);

  const handleGenerate = useCallback(async () => {
    const description = customDescription.trim();
    if (disabled || !description || generating) return;
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
      const personaId = crypto.randomUUID();
      const slug = `onboarding-custom-${personaId}`;
      const newDraft: CustomPersonaDraft = {
        personaId,
        slug,
        name: config.name || description,
        description: config.description || description,
        config,
      };
      const nextDrafts = [...customDrafts, newDraft];
      setCustomDrafts(nextDrafts);
      onCustomPersonasChange?.(nextDrafts);
      onActiveSeedChange(slug);
      setCustomDescription('');
      setMode('chat');
    } catch (err) {
      const message = (err as Error).message;
      setGenError(
        message === 'Personality generation timed out'
          ? t('personaPreview.generationTimedOut')
          : message || t('personaPreview.generationFailedUnknown'),
      );
    } finally {
      setGenerating(false);
    }
  }, [
    customDescription,
    customDrafts,
    disabled,
    generating,
    i18n.language,
    llmConfig,
    onActiveSeedChange,
    onCustomPersonasChange,
    t,
  ]);

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      {confirmationError && (
        <div
          role="alert"
          className="rounded-lg border border-destructive/35 bg-destructive/10 px-4 py-3 text-sm text-destructive"
        >
          {confirmationError}
        </div>
      )}
      <fieldset
        disabled={disabled}
        className="m-0 grid min-h-0 min-w-0 flex-1 grid-cols-[200px_1fr] gap-4 border-0 p-0"
      >
        <legend className="sr-only">{t('steps.personaPreview')}</legend>
      {/* Left: avatar rail — clicking selects the persona (the active one is
          confirmed by the footer "Next" button). */}
      <div className="flex flex-col gap-2 overflow-y-auto border-r border-border/55 pr-2">
        {railItems.map((p) => (
          <button
            key={p.slug}
            type="button"
            onClick={() => {
              onActiveSeedChange(p.slug);
              setMode('chat');
            }}
            aria-pressed={activeSeed === p.slug && mode === 'chat'}
            className={`flex items-center gap-3 rounded-lg px-3 py-2 text-left transition ${
              activeSeed === p.slug && mode === 'chat'
                ? 'bg-muted'
                : 'hover:bg-muted/50'
            }`}
          >
            <PreviewAvatar name={p.name} avatar={p.avatar} />
            <div className="min-w-0">
              <div className="truncate text-sm font-medium text-foreground">{p.name}</div>
              <div className="truncate text-xs text-muted-foreground">
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
          className={`flex items-center gap-3 rounded-lg border border-dashed border-border px-3 py-2 text-left text-sm text-muted-foreground transition hover:bg-muted/50 ${
            mode === 'create' ? 'bg-muted' : ''
          }`}
        >
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-dashed border-border text-lg">
            +
          </span>
          <span className="truncate font-medium">{t('personaPreview.createCustom')}</span>
        </button>
      </div>

      {/* Right: either the preview chat or the custom-persona composer. */}
      {mode === 'create' ? (
        <div className="flex min-h-0 flex-col gap-3">
          <div className="flex-1 overflow-y-auto rounded-lg border border-border/50 bg-muted/10 p-4">
            <h3 className="text-base font-semibold text-foreground">{t('personaPreview.createCustomTitle')}</h3>
            <p className="mt-1 text-xs text-muted-foreground">
              {t('personaPreview.createCustomHint')}
            </p>
            <textarea
              data-testid="persona-custom-description"
              value={customDescription}
              onChange={(e) => setCustomDescription(e.target.value)}
              placeholder={t('personaPreview.customDescriptionPlaceholder')}
              disabled={generating}
              rows={3}
              className="mt-4 w-full rounded-lg border border-border/45 bg-muted/35 px-4 py-3 text-base leading-7 text-foreground shadow-inner shadow-background/40 outline-none transition-colors placeholder:text-muted-foreground/60 focus:border-primary/35 focus:bg-background/80 focus:ring-2 focus:ring-primary/15 disabled:opacity-70"
            />

            {generating && (
              <div
                data-testid="persona-generation-progress"
                role="status"
                aria-live="polite"
                className="mt-4 overflow-hidden rounded-lg border border-border/45 bg-muted/30 p-4"
              >
                <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                  <span
                    className={cn(
                      'h-2 w-2 rounded-full bg-primary',
                      !shouldReduceMotion && 'animate-pulse',
                    )}
                    aria-hidden="true"
                  />
                  <span>{t('personaPreview.generating')}</span>
                </div>
                {genStages.length > 0 && (
                  <ul className="mt-3 space-y-1.5">
                    {genStages.map((s) => {
                      const isRunning = s.status === 'running';
                      const isCompleted = s.status === 'completed';
                      return (
                        <li
                          key={s.stage_id}
                          data-testid={isRunning ? 'persona-generation-stage-running' : undefined}
                          aria-current={isRunning ? 'step' : undefined}
                          className={cn(
                            'flex items-center gap-3 rounded-md px-2.5 py-2 text-sm transition-colors duration-300',
                            isRunning && 'bg-background/80 text-foreground shadow-sm',
                            isCompleted && 'text-foreground/80',
                            !isRunning && !isCompleted && 'text-muted-foreground/70',
                          )}
                        >
                          <span className="flex h-5 w-5 shrink-0 items-center justify-center">
                            {stageStatusIcon(s.status, shouldReduceMotion)}
                          </span>
                          <span className={cn(isRunning && 'font-medium')}>
                            {getGenerationStageLabel(s)}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            )}

            {genError && (
              <p className="mt-3 text-xs text-destructive">
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
              className="rounded-md px-4 py-2 text-sm text-muted-foreground underline disabled:opacity-50"
            >
              {t('personaPreview.cancelCreate')}
            </button>
            <button
              type="button"
              data-testid="persona-custom-generate"
              onClick={handleGenerate}
              disabled={!customDescription.trim() || generating}
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition hover:bg-primary/90 disabled:opacity-50"
            >
              {generating ? t('personaPreview.generating') : t('personaPreview.generate')}
            </button>
          </div>
        </div>
      ) : (
        <div className="flex min-h-0 flex-col gap-3">
          {/* Mirrors the real chat surface: bg-background scroll area with
              bg-card bubbles, so the preview reads like the app you're about
              to enter. */}
          <div className="flex-1 overflow-y-auto rounded-lg border border-border/55 bg-background p-4">
            {activeTranscript.length === 0 && (
              <p className="text-sm text-muted-foreground">
                {t('personaPreview.emptyHint')}
              </p>
            )}
            {activeTranscript.map((turn, idx) => (
              <div
                key={idx}
                className={`mb-2 flex ${turn.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <span
                  className={`inline-block max-w-[80%] whitespace-pre-wrap border border-border/55 bg-card px-4 py-2.5 text-sm text-foreground shadow-sm ${
                    turn.role === 'user'
                      ? 'rounded-xl rounded-tr-sm'
                      : 'rounded-xl rounded-tl-sm'
                  }`}
                >
                  {turn.role === 'assistant' && turn.content === '' ? (
                    <TypingDots
                      shouldReduceMotion={shouldReduceMotion}
                      label={t('personaPreview.waiting')}
                    />
                  ) : (
                    turn.content
                  )}
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
              className="flex-1 rounded-md border border-border/55 bg-background px-3 py-2 text-sm text-foreground"
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
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition hover:bg-primary/90 disabled:opacity-50"
            >
              {t('personaPreview.send')}
            </button>
          </div>

          {capReached && (
            <p className="text-xs text-muted-foreground">
              {t('personaPreview.capReached')}
            </p>
          )}
        </div>
      )}
      </fieldset>
    </div>
  );
}
