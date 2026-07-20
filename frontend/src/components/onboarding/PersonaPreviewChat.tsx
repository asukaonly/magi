import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useReducedMotion } from 'framer-motion';
import { CheckCircle2, Circle, Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import { streamChatPreview, type PreviewTurn } from '../../api/modules/chatPreview';
import {
  personasApi,
  type PersonaAdaptationMode,
  type PersonaGenerationIntent,
  type PersonalityConfig,
  type PersonaIntentResolution,
  type PersonaGenerationStage,
  type PersonaReferenceKind,
  type SeedPreview,
} from '../../api/modules/personas';
import type { LLMConfig } from '../../api/modules/config';
import { PersonaPreviewStarterChips } from './PersonaPreviewStarterChips';
import { PersonaProfilePanel } from './PersonaProfilePanel';
import {
  candidateToEditableReference,
  defaultAdaptationMode,
  PersonaReferenceEditor,
  type EditablePersonaReference,
} from './PersonaReferenceEditor';

const MAX_USER_TURNS_PER_PERSONA = 5;
const PREVIEW_SEGMENT_SENTINEL = '‖';

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
  originalDescription?: string;
  intent?: PersonaGenerationIntent;
  revision?: number;
}

export interface PersonaCreationDraft {
  draftId: string;
  personaId: string;
  phase: 'editing' | 'resolving' | 'reviewing' | 'generating' | 'failed';
  description: string;
  resolution?: PersonaIntentResolution;
  reference: EditablePersonaReference;
  referenceConfirmed: boolean;
  adaptationMode: PersonaAdaptationMode;
  constraintsText: string;
  generationRequestId?: string;
  generationJobId?: string;
  editingPersonaSlug?: string;
  revision: number;
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
  /** Restores an unfinished custom-persona creation or reference-editing draft. */
  initialCreationDraft?: PersonaCreationDraft | null;
  /** Persists the unfinished custom-persona creation state through onboarding reloads. */
  onCreationDraftChange?: (draft: PersonaCreationDraft | null) => void;
  /**
   * Fires when persona generation starts (true) / finishes (false), so the
   * parent can disable step navigation while a generation is in flight.
   */
  onGeneratingChange?: (generating: boolean) => void;
}

interface PreviewDisplayTurn extends PreviewTurn {
  id?: string;
  kind?: 'message' | 'revision-divider';
  superseded?: boolean;
  streamGroupId?: string;
}

type TranscriptMap = Record<string, PreviewDisplayTurn[]>;

function collapsePreviewHistory(turns: PreviewDisplayTurn[]): PreviewTurn[] {
  return turns.reduce<PreviewTurn[]>((history, turn) => {
    if (turn.kind === 'revision-divider' || turn.superseded) {
      return history;
    }
    const previous = history[history.length - 1];
    if (turn.role === 'assistant' && previous?.role === 'assistant') {
      history[history.length - 1] = {
        role: 'assistant',
        content: `${previous.content}\n${turn.content}`,
      };
      return history;
    }
    history.push({ role: turn.role, content: turn.content });
    return history;
  }, []);
}

function splitPreviewReply(content: string): string[] {
  return content
    .split(PREVIEW_SEGMENT_SENTINEL)
    .map((segment) => segment.trim())
    .filter(Boolean);
}

function createStableId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function createEmptyCreationDraft(): PersonaCreationDraft {
  return {
    draftId: createStableId(),
    personaId: createStableId(),
    phase: 'editing',
    description: '',
    reference: {
      sourceKind: 'original',
      name: '',
      workTitle: '',
      version: '',
      context: '',
    },
    referenceConfirmed: false,
    adaptationMode: 'original',
    constraintsText: '',
    revision: 1,
  };
}

function splitConstraints(value: string): string[] {
  return value
    .split(/\n|；|;/)
    .map((item) => item.trim())
    .filter((item, index, items) => Boolean(item) && items.indexOf(item) === index);
}

function expressionProfileForMode(
  mode: PersonaAdaptationMode,
): PersonaGenerationIntent['expression_profile'] {
  if (mode === 'fictional_immersive') return 'immersive';
  if (mode === 'public_expression' || mode === 'public_image') return 'balanced';
  return 'natural';
}

function buildGenerationIntent(draft: PersonaCreationDraft): PersonaGenerationIntent {
  const explicitConstraints = splitConstraints(draft.constraintsText);
  if (draft.reference.sourceKind === 'original') {
    return {
      source_kind: 'original',
      reference: null,
      adaptation_mode: 'original',
      expression_profile: 'natural',
      explicit_constraints: explicitConstraints,
    };
  }
  return {
    source_kind: draft.reference.sourceKind,
    reference: {
      source_kind: draft.reference.sourceKind,
      name: draft.reference.name.trim(),
      work_title: draft.reference.workTitle.trim() || null,
      version: draft.reference.version.trim() || null,
      context: draft.reference.context.trim() || null,
      user_confirmed: true,
    },
    adaptation_mode: draft.adaptationMode,
    expression_profile: expressionProfileForMode(draft.adaptationMode),
    explicit_constraints: explicitConstraints,
  };
}

function referenceSummary(intent?: PersonaGenerationIntent): string {
  const reference = intent?.reference;
  if (!reference) return '';
  return [
    reference.name,
    reference.work_title ? `《${reference.work_title}》` : '',
    reference.version || '',
  ].filter(Boolean).join(' · ');
}

interface RailItem {
  slug: string;
  name: string;
  description: string;
  avatar?: string;
  isCustom: boolean;
  config?: PersonalityConfig;
  customDraft?: CustomPersonaDraft;
}

interface PresetProfileState {
  status: 'loading' | 'success' | 'error';
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
  initialCreationDraft,
  onCreationDraftChange,
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
        customDraft: d,
      })),
    ],
    [sortedPreviews, customDrafts],
  );

  const [transcripts, setTranscripts] = useState<TranscriptMap>({});
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [adjustmentDraft, setAdjustmentDraft] = useState('');
  const [adjusting, setAdjusting] = useState(false);
  const [adjustmentError, setAdjustmentError] = useState<string | null>(null);

  // Custom-persona creation state.
  const [mode, setMode] = useState<'chat' | 'profile' | 'create'>(
    () => initialCreationDraft ? 'create' : 'chat',
  );
  const [presetProfiles, setPresetProfiles] = useState<Record<string, PresetProfileState>>({});
  const [creationDraft, setCreationDraft] = useState<PersonaCreationDraft | null>(
    () => initialCreationDraft ?? null,
  );
  const creationDraftRef = useRef<PersonaCreationDraft | null>(initialCreationDraft ?? null);
  const [genStages, setGenStages] = useState<PersonaGenerationStage[]>([]);
  const [genError, setGenError] = useState<string | null>(null);
  const resumedGenerationJobIdsRef = useRef(new Set<string>());

  const publishCreationDraft = useCallback(
    (next: PersonaCreationDraft | null) => {
      creationDraftRef.current = next;
      setCreationDraft(next);
      onCreationDraftChange?.(next);
    },
    [onCreationDraftChange],
  );

  useEffect(() => {
    const restored = creationDraftRef.current;
    if (!restored) return;
    if (restored.phase === 'resolving') {
      publishCreationDraft({ ...restored, phase: 'editing' });
      return;
    }
    if (restored.phase === 'generating' && !restored.generationJobId) {
      publishCreationDraft({
        ...restored,
        phase: 'failed',
        generationRequestId: undefined,
      });
    }
  }, [publishCreationDraft]);

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
  const generating =
    creationDraft?.phase === 'resolving' || creationDraft?.phase === 'generating';
  const creationInProgress = mode === 'create' && creationDraft !== null;
  useEffect(() => {
    onGeneratingChangeRef.current?.(creationInProgress);
  }, [creationInProgress]);

  const activeItem = railItems.find((i) => i.slug === activeSeed);
  const profileLocale = locale || 'en';
  const activeProfileKey = activeItem && !activeItem.isCustom
    ? `${profileLocale}:${activeItem.slug}`
    : null;
  const activeProfileState = activeProfileKey ? presetProfiles[activeProfileKey] : undefined;
  const activeProfileConfig = activeItem?.config ?? activeProfileState?.config;
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

  const appendTurn = useCallback((seedSlug: string, turn: PreviewDisplayTurn) => {
    setTranscripts((prev) => {
      const list = prev[seedSlug] ?? [];
      return { ...prev, [seedSlug]: [...list, turn] };
    });
  }, []);

  const updateAssistantStreamContent = useCallback(
    (seedSlug: string, content: string) => {
      setTranscripts((prev) => {
        const list = prev[seedSlug] ?? [];
        let currentUserIdx = list.length - 1;
        while (currentUserIdx >= 0 && list[currentUserIdx].role !== 'user') {
          currentUserIdx -= 1;
        }
        if (currentUserIdx < 0 || currentUserIdx === list.length - 1) return prev;
        const segments = splitPreviewReply(content);
        const assistantTurns = (segments.length > 0 ? segments : [content]).map<PreviewTurn>(
          (segment) => ({ role: 'assistant', content: segment }),
        );
        return {
          ...prev,
          [seedSlug]: [...list.slice(0, currentUserIdx + 1), ...assistantTurns],
        };
      });
    },
    [],
  );

  const updateAdjustmentStreamContent = useCallback(
    (seedSlug: string, streamGroupId: string, content: string) => {
      setTranscripts((prev) => {
        const list = prev[seedSlug] ?? [];
        const firstIndex = list.findIndex((turn) => turn.streamGroupId === streamGroupId);
        if (firstIndex < 0) return prev;
        const withoutGroup = list.filter((turn) => turn.streamGroupId !== streamGroupId);
        const segments = splitPreviewReply(content);
        const assistantTurns = (segments.length > 0 ? segments : [content]).map<PreviewDisplayTurn>(
          (segment) => ({
            role: 'assistant',
            content: segment,
            streamGroupId,
          }),
        );
        return {
          ...prev,
          [seedSlug]: [
            ...withoutGroup.slice(0, firstIndex),
            ...assistantTurns,
            ...withoutGroup.slice(firstIndex),
          ],
        };
      });
    },
    [],
  );

  const send = useCallback(async () => {
    if (
      disabled ||
      !activeSeed ||
      !draft.trim() ||
      busy ||
      adjusting ||
      capReached
    ) {
      return;
    }
    const userTurn: PreviewTurn = { role: 'user', content: draft.trim() };
    const seed = activeSeed;
    const snapshotHistory = collapsePreviewHistory(transcripts[seed] ?? []);
    // A custom (unsaved) persona has no seed file — preview it inline.
    const personaOverride =
      activeItem?.isCustom && activeItem.config
        ? activeItem.config
        : undefined;
    appendTurn(seed, userTurn);
    appendTurn(seed, { role: 'assistant', content: '' });
    setDraft('');
    setBusy(true);
    let responseText = '';
    try {
      for await (const chunk of streamChatPreview({
        seed_slug: personaOverride ? undefined : seed,
        locale,
        persona_override: personaOverride,
        history: snapshotHistory,
        message: userTurn,
        llm_override: llmConfig,
      })) {
        responseText += chunk;
        updateAssistantStreamContent(seed, responseText);
      }
    } catch (err) {
      const prefix = responseText ? `${responseText}\n` : '';
      updateAssistantStreamContent(seed, `${prefix}[error: ${(err as Error).message}]`);
    } finally {
      setBusy(false);
    }
  }, [
    activeSeed,
    activeItem,
    disabled,
    draft,
    busy,
    adjusting,
    capReached,
    transcripts,
    locale,
    llmConfig,
    appendTurn,
    updateAssistantStreamContent,
  ]);

  const handleChipPick = useCallback((prompt: string) => {
    setDraft(prompt);
  }, []);

  const loadPresetProfile = useCallback(
    async (item: RailItem, force = false) => {
      if (item.isCustom || item.config) return;
      const key = `${profileLocale}:${item.slug}`;
      const cached = presetProfiles[key];
      if (!force && (cached?.status === 'loading' || cached?.status === 'success')) return;

      setPresetProfiles((prev) => ({ ...prev, [key]: { status: 'loading' } }));
      try {
        const response = await personasApi.getPresetConfig(item.slug, profileLocale);
        if (!response.data) throw new Error('Persona profile is unavailable');
        setPresetProfiles((prev) => ({
          ...prev,
          [key]: { status: 'success', config: response.data },
        }));
      } catch {
        setPresetProfiles((prev) => ({ ...prev, [key]: { status: 'error' } }));
      }
    },
    [presetProfiles, profileLocale],
  );

  const showActiveProfile = useCallback(() => {
    if (!activeItem) return;
    setMode('profile');
    void loadPresetProfile(activeItem);
  }, [activeItem, loadPresetProfile]);

  const runGeneration = useCallback(
    async (
      sourceDraft: PersonaCreationDraft,
      intent: PersonaGenerationIntent,
      existingJobId?: string,
    ) => {
      const description = sourceDraft.description.trim();
      if (disabled || !description) return;
      let workingDraft: PersonaCreationDraft = {
        ...sourceDraft,
        phase: 'generating',
        generationRequestId:
          existingJobId
            ? sourceDraft.generationRequestId
            : sourceDraft.generationRequestId || createStableId(),
        generationJobId: existingJobId || sourceDraft.generationJobId,
      };
      publishCreationDraft(workingDraft);
      setGenError(null);
      setGenStages([]);
      try {
        const targetLanguage = (i18n.language || '').startsWith('zh') ? 'Chinese' : 'English';
        const resp = await personasApi.generateWithProgress(
          {
            description,
            target_language: targetLanguage,
            llm_override: llmConfig,
            draft_id: workingDraft.draftId,
            request_id: workingDraft.generationRequestId,
            intent,
          },
          (snapshot) => {
            setGenStages(snapshot.stages ?? []);
            if (
              snapshot.job_id &&
              workingDraft.generationJobId !== snapshot.job_id
            ) {
              workingDraft = {
                ...workingDraft,
                generationJobId: snapshot.job_id,
              };
              publishCreationDraft(workingDraft);
            }
          },
          existingJobId,
        );
        const config = resp.data;
        if (!config) {
          throw new Error('generation returned no config');
        }
        const slug =
          workingDraft.editingPersonaSlug ||
          `onboarding-custom-${workingDraft.personaId}`;
        const newDraft: CustomPersonaDraft = {
          personaId: workingDraft.personaId,
          slug,
          name: config.name || description,
          description: config.description || description,
          config,
          originalDescription: description,
          intent,
          revision: workingDraft.revision,
        };
        const existingIndex = customDrafts.findIndex(
          (item) =>
            item.slug === workingDraft.editingPersonaSlug ||
            item.personaId === workingDraft.personaId,
        );
        const nextDrafts =
          existingIndex >= 0
            ? customDrafts.map((item, index) => index === existingIndex ? newDraft : item)
            : [...customDrafts, newDraft];
        if (workingDraft.editingPersonaSlug) {
          setTranscripts((previous) => {
            const next = { ...previous };
            delete next[slug];
            return next;
          });
        }
        setCustomDrafts(nextDrafts);
        onCustomPersonasChange?.(nextDrafts);
        onActiveSeedChange(slug);
        publishCreationDraft(null);
        setMode('chat');
      } catch (err) {
        const message = (err as Error).message;
        setGenError(
          message === 'Personality generation timed out'
            ? t('personaPreview.generationTimedOut')
            : message || t('personaPreview.generationFailedUnknown'),
        );
        publishCreationDraft({
          ...workingDraft,
          phase: 'failed',
          generationRequestId: undefined,
          generationJobId: undefined,
        });
      }
    },
    [
      customDrafts,
      disabled,
      i18n.language,
      llmConfig,
      onActiveSeedChange,
      onCustomPersonasChange,
      publishCreationDraft,
      t,
    ],
  );

  const applyResolution = useCallback(
    (sourceDraft: PersonaCreationDraft, resolution: PersonaIntentResolution) => {
      const selected =
        resolution.candidates.find(
          (candidate) => candidate.candidate_id === resolution.selected_candidate_id,
        ) ?? resolution.candidates[0];
      const reference =
        resolution.status === 'original'
          ? {
              sourceKind: 'original' as const,
              name: '',
              workTitle: '',
              version: '',
              context: '',
            }
          : selected
            ? candidateToEditableReference(selected)
            : {
                sourceKind: 'fictional_reference' as const,
                name: '',
                workTitle: '',
                version: '',
                context: '',
              };
      return {
        ...sourceDraft,
        phase: 'reviewing' as const,
        resolution,
        reference,
        referenceConfirmed:
          resolution.status === 'resolved' || resolution.status === 'original',
        adaptationMode: defaultAdaptationMode(reference.sourceKind),
        constraintsText: resolution.explicit_constraints.join('\n'),
      };
    },
    [],
  );

  const handleResolveOrGenerate = useCallback(async () => {
    const sourceDraft = creationDraftRef.current;
    const description = sourceDraft?.description.trim() || '';
    if (!sourceDraft || disabled || !description || generating) return;

    if (sourceDraft.phase === 'reviewing' || sourceDraft.phase === 'failed') {
      if (!sourceDraft.referenceConfirmed) return;
      if (sourceDraft.reference.sourceKind !== 'original' && !sourceDraft.reference.name.trim()) {
        return;
      }
      const retryDraft = {
        ...sourceDraft,
        generationRequestId: createStableId(),
        generationJobId: undefined,
      };
      await runGeneration(retryDraft, buildGenerationIntent(retryDraft));
      return;
    }

    const resolvingDraft: PersonaCreationDraft = {
      ...sourceDraft,
      phase: 'resolving',
    };
    publishCreationDraft(resolvingDraft);
    setGenError(null);
    try {
      const targetLanguage = (i18n.language || '').startsWith('zh') ? 'Chinese' : 'English';
      const response = await personasApi.resolveGenerationIntent({
        description,
        target_language: targetLanguage,
        llm_override: llmConfig,
      });
      if (!response.data) {
        throw new Error('Persona intent resolution returned no result');
      }
      const reviewedDraft = applyResolution(resolvingDraft, response.data);
      if (response.data.status === 'original') {
        await runGeneration(reviewedDraft, buildGenerationIntent(reviewedDraft));
        return;
      }
      publishCreationDraft(reviewedDraft);
    } catch {
      const fallbackResolution: PersonaIntentResolution = {
        status: 'unknown',
        candidates: [],
        selected_candidate_id: null,
        confidence: 0,
        requires_confirmation: true,
        explicit_constraints: [],
      };
      publishCreationDraft(applyResolution(resolvingDraft, fallbackResolution));
      setGenError(t('personaPreview.reference.resolveFailed'));
    }
  }, [
    applyResolution,
    disabled,
    generating,
    i18n.language,
    llmConfig,
    publishCreationDraft,
    runGeneration,
    t,
  ]);

  const editCustomReference = useCallback(
    (customDraft: CustomPersonaDraft) => {
      const intent = customDraft.intent;
      const reference = intent?.reference;
      const sourceKind = intent?.source_kind ?? 'original';
      const editableReference: EditablePersonaReference =
        sourceKind === 'original' || !reference
          ? {
              sourceKind: 'original',
              name: '',
              workTitle: '',
              version: '',
              context: '',
            }
          : {
              sourceKind: sourceKind as PersonaReferenceKind,
              name: reference.name,
              workTitle: reference.work_title || '',
              version: reference.version || '',
              context: reference.context || '',
            };
      const candidate =
        editableReference.sourceKind === 'original'
          ? []
          : [{
              candidate_id: 'candidate-1',
              source_kind: editableReference.sourceKind,
              name: editableReference.name,
              work_title: editableReference.workTitle || null,
              version: editableReference.version || null,
              context: editableReference.context || null,
              confidence: 1,
            }];
      publishCreationDraft({
        draftId: createStableId(),
        personaId: customDraft.personaId,
        phase: 'reviewing',
        description: customDraft.originalDescription || customDraft.description,
        resolution: {
          status: editableReference.sourceKind === 'original' ? 'original' : 'resolved',
          candidates: candidate,
          selected_candidate_id: candidate[0]?.candidate_id || null,
          confidence: 1,
          requires_confirmation: editableReference.sourceKind !== 'original',
          explicit_constraints: intent?.explicit_constraints || [],
        },
        reference: editableReference,
        referenceConfirmed: true,
        adaptationMode: intent?.adaptation_mode || defaultAdaptationMode(editableReference.sourceKind),
        constraintsText: (intent?.explicit_constraints || []).join('\n'),
        editingPersonaSlug: customDraft.slug,
        revision: (customDraft.revision || 1) + 1,
      });
      setGenError(null);
      setGenStages([]);
      setMode('create');
    },
    [publishCreationDraft],
  );

  const adjustActivePersona = useCallback(async () => {
    const instruction = adjustmentDraft.trim();
    const customDraft = activeItem?.customDraft;
    const seed = activeSeed;
    if (
      !instruction ||
      !customDraft ||
      !seed ||
      disabled ||
      busy ||
      adjusting
    ) {
      return;
    }
    setAdjusting(true);
    setAdjustmentError(null);
    try {
      const targetLanguage = (i18n.language || '').startsWith('zh') ? 'Chinese' : 'English';
      const response = await personasApi.adjust({
        current_config: customDraft.config,
        instruction,
        scope: 'auto',
        target_language: targetLanguage,
        intent: customDraft.intent,
        llm_override: llmConfig,
      });
      if (!response.data) {
        throw new Error('Persona adjustment returned no config');
      }
      const updatedDraft: CustomPersonaDraft = {
        ...customDraft,
        name: response.data.name || customDraft.name,
        description: response.data.description || customDraft.description,
        config: response.data,
        revision: (customDraft.revision || 1) + 1,
      };
      const nextDrafts = customDrafts.map((item) =>
        item.slug === customDraft.slug ? updatedDraft : item,
      );
      setCustomDrafts(nextDrafts);
      onCustomPersonasChange?.(nextDrafts);
      setAdjustmentDraft('');

      const currentTurns = transcripts[seed] ?? [];
      let lastUserIndex = currentTurns.length - 1;
      while (lastUserIndex >= 0 && currentTurns[lastUserIndex].role !== 'user') {
        lastUserIndex -= 1;
      }
      if (lastUserIndex < 0) {
        return;
      }

      const lastUser = currentTurns[lastUserIndex];
      const history = collapsePreviewHistory(currentTurns.slice(0, lastUserIndex));
      const streamGroupId = createStableId();
      setTranscripts((prev) => {
        const list = prev[seed] ?? [];
        return {
          ...prev,
          [seed]: [
            ...list.map((turn, index) =>
              index > lastUserIndex && turn.role === 'assistant'
                ? { ...turn, superseded: true }
                : turn,
            ),
            {
              id: createStableId(),
              kind: 'revision-divider',
              role: 'assistant',
              content: '',
            },
            {
              id: createStableId(),
              role: 'assistant',
              content: '',
              streamGroupId,
            },
          ],
        };
      });

      let responseText = '';
      try {
        for await (const chunk of streamChatPreview({
          persona_override: response.data,
          history,
          message: { role: 'user', content: lastUser.content },
          llm_override: llmConfig,
          locale,
        })) {
          responseText += chunk;
          updateAdjustmentStreamContent(seed, streamGroupId, responseText);
        }
      } catch (error) {
        const prefix = responseText ? `${responseText}\n` : '';
        updateAdjustmentStreamContent(
          seed,
          streamGroupId,
          `${prefix}[error: ${(error as Error).message}]`,
        );
      }
    } catch (error) {
      setAdjustmentError(
        (error as Error).message || t('personaPreview.adjustment.failed'),
      );
    } finally {
      setAdjusting(false);
    }
  }, [
    activeItem,
    activeSeed,
    adjustmentDraft,
    adjusting,
    busy,
    customDrafts,
    disabled,
    i18n.language,
    llmConfig,
    locale,
    onCustomPersonasChange,
    t,
    transcripts,
    updateAdjustmentStreamContent,
  ]);

  useEffect(() => {
    const restored = creationDraftRef.current;
    const jobId = restored?.generationJobId;
    if (
      !restored ||
      restored.phase !== 'generating' ||
      !jobId ||
      resumedGenerationJobIdsRef.current.has(jobId)
    ) {
      return;
    }
    resumedGenerationJobIdsRef.current.add(jobId);
    void runGeneration(restored, buildGenerationIntent(restored), jobId);
  }, [runGeneration]);

  const creationNeedsConfirmation =
    creationDraft?.phase === 'reviewing' || creationDraft?.phase === 'failed';
  const creationReferenceValid =
    !creationNeedsConfirmation ||
    (
      creationDraft.referenceConfirmed &&
      (
        creationDraft.reference.sourceKind === 'original' ||
        Boolean(creationDraft.reference.name.trim())
      )
    );
  const generationButtonLabel =
    creationDraft?.phase === 'resolving'
      ? t('personaPreview.reference.resolving')
      : creationDraft?.phase === 'generating'
        ? t('personaPreview.generating')
        : creationNeedsConfirmation
          ? t('personaPreview.reference.confirmAndGenerate')
          : t('personaPreview.generate');

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
            aria-pressed={activeSeed === p.slug && mode !== 'create'}
            className={`flex items-center gap-3 rounded-lg px-3 py-2 text-left transition ${
              activeSeed === p.slug && mode !== 'create'
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
            if (!creationDraftRef.current) {
              publishCreationDraft(createEmptyCreationDraft());
            }
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
        <div className="flex min-h-0 flex-col gap-4">
          <div className="flex-1 overflow-y-auto rounded-lg border border-border/50 bg-muted/10 p-4">
            <h3 className="text-base font-semibold text-foreground">{t('personaPreview.createCustomTitle')}</h3>
            <p className="mt-1 text-xs text-muted-foreground">
              {t('personaPreview.createCustomHint')}
            </p>
            <textarea
              data-testid="persona-custom-description"
              value={creationDraft?.description || ''}
              onChange={(event) => {
                const currentDraft = creationDraftRef.current ?? createEmptyCreationDraft();
                publishCreationDraft({
                  ...currentDraft,
                  phase: 'editing',
                  description: event.target.value,
                  resolution: undefined,
                  referenceConfirmed: false,
                  generationRequestId: undefined,
                  generationJobId: undefined,
                });
                setGenError(null);
                setGenStages([]);
              }}
              placeholder={t('personaPreview.customDescriptionPlaceholder')}
              disabled={generating}
              rows={3}
              className="mt-4 w-full rounded-lg border border-border/45 bg-muted/35 px-4 py-3 text-base leading-7 text-foreground shadow-inner shadow-background/40 outline-none transition-colors placeholder:text-muted-foreground/60 focus:border-primary/35 focus:bg-background/80 focus:ring-2 focus:ring-primary/15 disabled:opacity-70"
            />

            {creationDraft?.resolution && creationNeedsConfirmation && (
              <PersonaReferenceEditor
                resolution={creationDraft.resolution}
                value={creationDraft.reference}
                adaptationMode={creationDraft.adaptationMode}
                constraintsText={creationDraft.constraintsText}
                disabled={generating}
                onChange={(reference) => {
                  publishCreationDraft({
                    ...creationDraft,
                    reference,
                    referenceConfirmed: true,
                    adaptationMode:
                      reference.sourceKind === creationDraft.reference.sourceKind
                        ? creationDraft.adaptationMode
                        : defaultAdaptationMode(reference.sourceKind),
                  });
                }}
                onAdaptationModeChange={(adaptationMode) => {
                  publishCreationDraft({
                    ...creationDraft,
                    adaptationMode,
                    referenceConfirmed: true,
                  });
                }}
                onConstraintsTextChange={(constraintsText) => {
                  publishCreationDraft({
                    ...creationDraft,
                    constraintsText,
                  });
                }}
              />
            )}

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
                  <span>
                    {creationDraft?.phase === 'resolving'
                      ? t('personaPreview.reference.resolving')
                      : t('personaPreview.generating')}
                  </span>
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
              <p className="mt-3 text-xs text-destructive" role="alert">
                {genError}
              </p>
            )}
          </div>

          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={() => {
                setMode('chat');
                setGenError(null);
                publishCreationDraft(null);
              }}
              disabled={generating}
              className="rounded-md px-4 py-2 text-sm text-muted-foreground underline disabled:opacity-50"
            >
              {t('personaPreview.cancelCreate')}
            </button>
            <button
              type="button"
              data-testid="persona-custom-generate"
              onClick={() => void handleResolveOrGenerate()}
              disabled={
                !creationDraft?.description.trim() ||
                generating ||
                !creationReferenceValid
              }
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition hover:bg-primary/90 disabled:opacity-50"
            >
              {generationButtonLabel}
            </button>
          </div>
        </div>
      ) : (
        <div className="flex min-h-0 flex-col gap-3">
          {activeItem?.customDraft?.intent?.reference && (
            <div
              data-testid="persona-reference-summary"
              className="flex items-center justify-between gap-3 rounded-lg border border-border/55 bg-muted/25 px-3 py-2"
            >
              <div className="min-w-0">
                <div className="text-xs text-muted-foreground">
                  {t('personaPreview.reference.currentReference')}
                </div>
                <div className="truncate text-sm font-medium text-foreground">
                  {referenceSummary(activeItem.customDraft.intent)}
                </div>
              </div>
              <button
                type="button"
                data-testid="persona-reference-edit"
                onClick={() => editCustomReference(activeItem.customDraft!)}
                className="shrink-0 rounded-md px-2.5 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary/10"
              >
                {t('personaPreview.reference.edit')}
              </button>
            </div>
          )}
          <div
            role="group"
            aria-label={t('personaPreview.modeLabel', { name: activeItem?.name || '' })}
            className="flex w-fit shrink-0 self-end items-center gap-1 rounded-xl bg-muted/45 p-1"
          >
            <button
              type="button"
              data-testid="persona-mode-chat"
              aria-pressed={mode === 'chat'}
              onClick={() => setMode('chat')}
              className={cn(
                'rounded-md px-3 py-1.5 text-sm transition-colors',
                mode === 'chat'
                  ? 'bg-background font-medium text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {t('personaPreview.talkWith', { name: activeItem?.name || '' })}
            </button>
            <button
              type="button"
              data-testid="persona-mode-profile"
              aria-pressed={mode === 'profile'}
              onClick={showActiveProfile}
              disabled={!activeItem}
              className={cn(
                'rounded-md px-3 py-1.5 text-sm transition-colors disabled:opacity-50',
                mode === 'profile'
                  ? 'bg-background font-medium text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {t('personaPreview.learnAbout', { name: activeItem?.name || '' })}
            </button>
          </div>

          {mode === 'profile' ? (
            activeProfileConfig ? (
              <PersonaProfilePanel
                key={activeItem?.slug}
                config={activeProfileConfig}
              />
            ) : activeProfileState?.status === 'error' ? (
              <div
                data-testid="persona-profile-error"
                role="alert"
                className="flex flex-1 flex-col items-center justify-center rounded-lg border border-border/55 bg-background px-6 text-center"
              >
                <p className="text-sm text-muted-foreground">
                  {t('personaPreview.profileLoadFailed', { name: activeItem?.name || '' })}
                </p>
                <button
                  type="button"
                  className="mt-3 rounded-md border border-border px-3 py-2 text-sm font-medium text-foreground transition-colors hover:bg-muted"
                  onClick={() => {
                    if (activeItem) void loadPresetProfile(activeItem, true);
                  }}
                >
                  {t('personaPreview.profileRetry')}
                </button>
              </div>
            ) : (
              <div
                data-testid="persona-profile-loading"
                role="status"
                className="flex flex-1 flex-col items-center justify-center rounded-lg border border-border/55 bg-background px-6 text-center"
              >
                <Loader2
                  className={cn('h-5 w-5 text-primary', !shouldReduceMotion && 'animate-spin')}
                  aria-hidden="true"
                />
                <p className="mt-3 text-sm text-muted-foreground">
                  {t('personaPreview.profileLoading', { name: activeItem?.name || '' })}
                </p>
              </div>
            )
          ) : (
            <>
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
                  turn.kind === 'revision-divider' ? (
                    <div
                      key={turn.id || `divider-${idx}`}
                      data-testid="persona-adjustment-divider"
                      className="my-4 flex items-center gap-3 text-xs text-muted-foreground"
                    >
                      <span className="h-px flex-1 bg-border" />
                      <span>{t('personaPreview.adjustment.reanswered')}</span>
                      <span className="h-px flex-1 bg-border" />
                    </div>
                  ) : (
                  <div
                    key={turn.id || idx}
                    className={`mb-2 flex ${turn.role === 'user' ? 'justify-end' : 'justify-start'}`}
                  >
                    <span
                      data-testid={
                        turn.role === 'assistant'
                          ? 'persona-preview-assistant-bubble'
                          : 'persona-preview-user-bubble'
                      }
                      className={`inline-block max-w-[80%] whitespace-pre-wrap border border-border/55 bg-card px-4 py-2.5 text-sm text-foreground shadow-sm ${
                        turn.role === 'user'
                          ? 'rounded-xl rounded-tr-sm'
                          : 'rounded-xl rounded-tl-sm'
                      } ${turn.superseded ? 'opacity-55' : ''}`}
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
                  )
                ))}
              </div>

              <PersonaPreviewStarterChips onPick={handleChipPick} />

              {activeItem?.customDraft && (
                <div
                  data-testid="persona-adjustment-panel"
                  className="rounded-lg border border-border/55 bg-muted/20 p-3"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <div className="text-sm font-medium text-foreground">
                        {t('personaPreview.adjustment.title')}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {t('personaPreview.adjustment.hint')}
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {(['shorter', 'lessPerformative', 'moreNatural'] as const).map((key) => (
                        <button
                          key={key}
                          type="button"
                          disabled={adjusting}
                          onClick={() => setAdjustmentDraft(t(`personaPreview.adjustment.quick.${key}`))}
                          className="rounded-full border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted disabled:opacity-50"
                        >
                          {t(`personaPreview.adjustment.quick.${key}`)}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="mt-2 flex items-center gap-2">
                    <input
                      data-testid="persona-adjustment-input"
                      value={adjustmentDraft}
                      disabled={adjusting}
                      onChange={(event) => setAdjustmentDraft(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' && !event.shiftKey) {
                          event.preventDefault();
                          void adjustActivePersona();
                        }
                      }}
                      placeholder={t('personaPreview.adjustment.placeholder')}
                      className="min-w-0 flex-1 rounded-md border border-border/55 bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/60"
                    />
                    <button
                      type="button"
                      data-testid="persona-adjustment-submit"
                      disabled={!adjustmentDraft.trim() || adjusting || busy}
                      onClick={() => void adjustActivePersona()}
                      className="rounded-md border border-primary/40 px-3 py-2 text-sm font-medium text-primary transition-colors hover:bg-primary/10 disabled:opacity-50"
                    >
                      {adjusting
                        ? t('personaPreview.adjustment.adjusting')
                        : t('personaPreview.adjustment.submit')}
                    </button>
                  </div>
                  {adjustmentError && (
                    <p className="mt-2 text-xs text-destructive" role="alert">
                      {adjustmentError}
                    </p>
                  )}
                </div>
              )}

              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  placeholder={t('personaPreview.composerPlaceholder')}
                  disabled={adjusting || capReached}
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
                  disabled={!draft.trim() || busy || adjusting || capReached}
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
            </>
          )}
        </div>
      )}
      </fieldset>
    </div>
  );
}
