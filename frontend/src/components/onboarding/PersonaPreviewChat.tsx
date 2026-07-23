import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { ArrowLeft, Check, CheckCircle2, Circle, ExternalLink, Loader2, PencilLine, RefreshCw } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import { streamChatPreview, type PreviewTurn } from '../../api/modules/chatPreview';
import {
  personasApi,
  type PersonaFidelityLevel,
  type PersonaGenerationIntent,
  type PersonaReferenceDossier,
  type PersonaReferenceSource,
  type PersonaResearchPreference,
  type PersonalityConfig,
  type PersonaIntentResolution,
  type PersonaGenerationStage,
  type PersonaReferenceKind,
  type SeedPreview,
} from '../../api/modules/personas';
import { configApi, type LLMConfig } from '../../api/modules/config';
import { PersonaPreviewStarterChips } from './PersonaPreviewStarterChips';
import { PersonaProfilePanel } from './PersonaProfilePanel';
import { ONBOARDING_FIELD_MUTED_CLASS } from './onboardingStyles';
import {
  candidateToEditableReference,
  defaultFidelityLevel,
  PersonaReferenceEditor,
  type EditablePersonaReference,
} from './PersonaReferenceEditor';

const MAX_USER_TURNS_PER_PERSONA = 5;
const PREVIEW_SEGMENT_SENTINEL = '‖';
const FAKE_IP_COMPATIBILITY_REQUIRED = 'FAKE_IP_COMPATIBILITY_REQUIRED';

type FakeIpCompatibilityRetry =
  | { kind: 'verification'; draft: PersonaCreationDraft }
  | { kind: 'generation'; draft: PersonaCreationDraft; intent: PersonaGenerationIntent };

function errorCode(error: unknown): string | undefined {
  if (!error || typeof error !== 'object' || !('code' in error)) {
    return undefined;
  }
  const code = (error as { code?: unknown }).code;
  return typeof code === 'string' ? code : undefined;
}

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
  referenceDossier?: PersonaReferenceDossier;
  revision?: number;
}

export interface PersonaCreationDraft {
  draftId: string;
  personaId: string;
  phase: 'editing' | 'resolving' | 'reviewing' | 'verifying' | 'generating' | 'failed';
  description: string;
  resolution?: PersonaIntentResolution;
  reference: EditablePersonaReference;
  referenceConfirmed: boolean;
  fidelityLevel: PersonaFidelityLevel;
  researchPreference: PersonaResearchPreference;
  referenceUrlsText: string;
  referenceModified: boolean;
  identityVerified: boolean;
  verificationFingerprint?: string;
  verificationSources: PersonaReferenceSource[];
  verificationWarning?: string;
  forceResearchRefresh: boolean;
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
    fidelityLevel: 'natural',
    researchPreference: 'disabled',
    referenceUrlsText: '',
    referenceModified: false,
    identityVerified: false,
    verificationSources: [],
    forceResearchRefresh: false,
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

function expressionLevelForFidelity(
  fidelityLevel: PersonaFidelityLevel,
): PersonaGenerationIntent['expression_level'] {
  if (fidelityLevel === 'traits') return 'low';
  if (fidelityLevel === 'faithful') return 'high_contextual';
  return 'balanced';
}

function splitReferenceUrls(value: string): string[] {
  return value
    .split(/\n|,|，/)
    .map((item) => item.trim())
    .filter((item, index, items) => Boolean(item) && items.indexOf(item) === index);
}

function referenceUrlsAreValid(value: string): boolean {
  const urls = splitReferenceUrls(value);
  if (urls.length > 4) return false;
  return urls.every((value) => {
    try {
      const url = new URL(value);
      return url.protocol === 'http:' || url.protocol === 'https:';
    } catch {
      return false;
    }
  });
}

function buildGenerationIntent(draft: PersonaCreationDraft): PersonaGenerationIntent {
  const explicitConstraints = splitConstraints(draft.constraintsText);
  if (draft.reference.sourceKind === 'original') {
    return {
      source_kind: 'original',
      reference: null,
      fidelity_level: 'natural',
      expression_level: 'balanced',
      research: {
        preference: 'disabled',
        force_refresh: false,
        reference_urls: [],
        identity_confidence: 1,
        identity_ambiguous: false,
        identity_verified: false,
        reference_modified: false,
        verification_fingerprint: null,
      },
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
    fidelity_level: draft.fidelityLevel,
    expression_level: expressionLevelForFidelity(draft.fidelityLevel),
    research: {
      preference:
        draft.reference.sourceKind === 'private_person_reference'
          ? 'disabled'
          : draft.researchPreference,
      force_refresh:
        draft.researchPreference === 'disabled' ? false : draft.forceResearchRefresh,
      reference_urls:
        draft.reference.sourceKind === 'private_person_reference' ||
        draft.researchPreference === 'disabled'
          ? []
          : splitReferenceUrls(draft.referenceUrlsText),
      identity_confidence: draft.resolution?.confidence ?? 0,
      identity_ambiguous: draft.resolution?.status === 'ambiguous',
      identity_verified: draft.identityVerified,
      reference_modified: draft.referenceModified,
      verification_fingerprint: draft.verificationFingerprint || null,
    },
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
function PreviewAvatar({ name, avatar, size = 'md' }: { name: string; avatar?: string; size?: 'md' | 'lg' }): JSX.Element {
  const [failed, setFailed] = useState(false);
  const url = avatar ? personasApi.getAvatarUrl(avatar) : '';
  const initial = name.trim().charAt(0).toUpperCase() || '?';
  const boxClass = size === 'lg' ? 'h-16 w-16' : 'h-10 w-10';
  const textClass = size === 'lg' ? 'text-lg' : 'text-sm';

  if (!url || failed) {
    return (
      <div className={cn('flex shrink-0 items-center justify-center rounded-full bg-muted font-semibold text-muted-foreground', boxClass, textClass)}>
        {initial}
      </div>
    );
  }
  return (
    <img
      src={url}
      alt=""
      onError={() => setFailed(true)}
      className={cn('shrink-0 rounded-full object-cover', boxClass)}
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
  // Two-stage flow: picker grid → detail (preview / composer). Restoring an
  // unfinished creation lands directly in the detail composer.
  const [stage, setStage] = useState<'picker' | 'detail'>(
    () => initialCreationDraft ? 'detail' : 'picker',
  );
  const [presetProfiles, setPresetProfiles] = useState<Record<string, PresetProfileState>>({});
  const [creationDraft, setCreationDraft] = useState<PersonaCreationDraft | null>(
    () => initialCreationDraft ?? null,
  );
  const [descriptionExpanded, setDescriptionExpanded] = useState(
    () =>
      !initialCreationDraft ||
      (initialCreationDraft.phase !== 'reviewing' && initialCreationDraft.phase !== 'failed'),
  );
  const creationDraftRef = useRef<PersonaCreationDraft | null>(initialCreationDraft ?? null);
  const [genStages, setGenStages] = useState<PersonaGenerationStage[]>([]);
  const [genError, setGenError] = useState<string | null>(null);
  const [fakeIpCompatibilityRetry, setFakeIpCompatibilityRetry] =
    useState<FakeIpCompatibilityRetry | null>(null);
  const [enablingFakeIpCompatibility, setEnablingFakeIpCompatibility] = useState(false);
  const resumedGenerationJobIdsRef = useRef(new Set<string>());
  const creationSubmissionInFlightRef = useRef(false);
  const restoredCreationDraftHandledRef = useRef(false);

  const publishCreationDraft = useCallback(
    (next: PersonaCreationDraft | null) => {
      creationDraftRef.current = next;
      setCreationDraft(next);
      onCreationDraftChange?.(next);
    },
    [onCreationDraftChange],
  );

  useEffect(() => {
    if (restoredCreationDraftHandledRef.current) return;
    restoredCreationDraftHandledRef.current = true;
    const restored = creationDraftRef.current;
    if (!restored) return;
    if (restored.phase === 'resolving' || restored.phase === 'verifying') {
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
    creationDraft?.phase === 'resolving' ||
    creationDraft?.phase === 'verifying' ||
    creationDraft?.phase === 'generating';
  const creationBlocksNavigation =
    generating ||
    (stage === 'detail' && mode === 'create' && creationDraft !== null);
  useEffect(() => {
    onGeneratingChangeRef.current?.(creationBlocksNavigation);
  }, [creationBlocksNavigation]);

  const activeItem = railItems.find((i) => i.slug === activeSeed);
  const profileLocale = locale || 'en';
  const activeProfileKey = activeItem && !activeItem.isCustom
    ? `${profileLocale}:${activeItem.slug}`
    : null;
  const activeProfileState = activeProfileKey ? presetProfiles[activeProfileKey] : undefined;
  const activeProfileConfig = activeItem?.config ?? activeProfileState?.config;
  const activeTranscript = activeSeed ? transcripts[activeSeed] ?? [] : [];
  const transcriptScrollRef = useRef<HTMLDivElement | null>(null);

  // 新消息/流式更新时把消息区滚到底部,行为对齐真实聊天。
  useEffect(() => {
    const el = transcriptScrollRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [activeTranscript]);
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

  // Picker entry point: select the persona and jump straight into chat or
  // profile detail. Profile loading uses the clicked item directly because
  // `activeItem` still reflects the previous selection in this render cycle.
  const enterPersona = useCallback(
    (item: RailItem, nextMode: 'chat' | 'profile') => {
      onActiveSeedChange(item.slug);
      if (nextMode === 'profile') {
        setMode('profile');
        void loadPresetProfile(item);
      } else {
        setMode('chat');
      }
      setStage('detail');
    },
    [loadPresetProfile, onActiveSeedChange],
  );

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
      setFakeIpCompatibilityRetry(null);
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
          referenceDossier: resp.reference_dossier,
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
        const failedDraft: PersonaCreationDraft = {
          ...workingDraft,
          phase: 'failed',
          generationRequestId: undefined,
          generationJobId: undefined,
        };
        if (errorCode(err) === FAKE_IP_COMPATIBILITY_REQUIRED) {
          setGenError(t('settings.fakeIpCompatibilityPromptDesc', { ns: 'app' }));
          setFakeIpCompatibilityRetry({
            kind: 'generation',
            draft: failedDraft,
            intent,
          });
        } else {
          setGenError(
            message === 'Personality generation timed out'
              ? t('personaPreview.generationTimedOut')
              : message || t('personaPreview.generationFailedUnknown'),
          );
        }
        publishCreationDraft(failedDraft);
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
    (sourceDraft: PersonaCreationDraft, resolution: PersonaIntentResolution): PersonaCreationDraft => {
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
          // 至多一个候选时,编辑器里的默认值(首选候选 + 默认出场方式)
          // 无需用户再点一次即可确认;多个候选才要求显式选择。
          resolution.status === 'resolved' ||
          resolution.status === 'original' ||
          resolution.candidates.length <= 1,
        fidelityLevel: defaultFidelityLevel(reference.sourceKind),
        researchPreference:
          reference.sourceKind === 'original' || reference.sourceKind === 'private_person_reference'
            ? 'disabled'
            : 'auto',
        referenceUrlsText: '',
        referenceModified: false,
        identityVerified: false,
        verificationFingerprint: undefined,
        verificationSources: [],
        verificationWarning: undefined,
        forceResearchRefresh: false,
        constraintsText: resolution.explicit_constraints.join('\n'),
      };
    },
    [],
  );

  const verifyDraftReference = useCallback(
    async (sourceDraft: PersonaCreationDraft): Promise<PersonaCreationDraft | null> => {
      if (
        sourceDraft.reference.sourceKind === 'original' ||
        sourceDraft.reference.sourceKind === 'private_person_reference' ||
        sourceDraft.researchPreference === 'disabled' ||
        sourceDraft.identityVerified
      ) {
        return sourceDraft;
      }
      const verifyingDraft: PersonaCreationDraft = {
        ...sourceDraft,
        phase: 'verifying',
      };
      publishCreationDraft(verifyingDraft);
      setFakeIpCompatibilityRetry(null);
      try {
        const targetLanguage = (i18n.language || '').startsWith('zh') ? 'Chinese' : 'English';
        const response = await personasApi.verifyReferenceIdentity({
          description: sourceDraft.description,
          reference: {
            source_kind: sourceDraft.reference.sourceKind,
            name: sourceDraft.reference.name.trim(),
            work_title: sourceDraft.reference.workTitle.trim() || null,
            version: sourceDraft.reference.version.trim() || null,
            context: sourceDraft.reference.context.trim() || null,
            user_confirmed: true,
          },
          target_language: targetLanguage,
          reference_urls: splitReferenceUrls(sourceDraft.referenceUrlsText),
          llm_override: llmConfig,
        });
        const verification = response.data;
        if (!verification) {
          throw new Error('Reference verification returned no result');
        }
        const canonical = verification.canonical_identity;
        const reference: EditablePersonaReference = canonical
          ? {
              sourceKind: canonical.source_kind,
              name: canonical.name,
              workTitle: canonical.work_title || '',
              version: canonical.version || '',
              context: canonical.context || '',
            }
          : sourceDraft.reference;
        if (verification.requires_confirmation || verification.status === 'ambiguous') {
          const identities = [
            ...(canonical ? [canonical] : []),
            ...verification.alternatives,
          ];
          const candidates = identities.map((identity, index) => ({
            candidate_id: `verified-candidate-${index + 1}`,
            source_kind: identity.source_kind,
            name: identity.name,
            work_title: identity.work_title || null,
            version: identity.version || null,
            context: identity.context || null,
            confidence: verification.confidence,
          }));
          publishCreationDraft({
            ...sourceDraft,
            phase: 'reviewing',
            reference,
            referenceConfirmed: false,
            resolution: {
              status: candidates.length > 1 ? 'ambiguous' : 'resolved',
              candidates,
              selected_candidate_id: candidates[0]?.candidate_id || null,
              confidence: verification.confidence,
              requires_confirmation: true,
              explicit_constraints: splitConstraints(sourceDraft.constraintsText),
            },
            identityVerified: verification.status === 'verified',
            verificationFingerprint: verification.reference_fingerprint || undefined,
            verificationSources: verification.sources,
            verificationWarning: verification.warning || undefined,
          });
          setGenError(verification.warning || t('personaPreview.reference.verificationNeedsReview'));
          return null;
        }
        const verifiedDraft: PersonaCreationDraft = {
          ...sourceDraft,
          phase: 'reviewing',
          reference,
          identityVerified: verification.status === 'verified',
          verificationFingerprint: verification.reference_fingerprint || undefined,
          verificationSources: verification.sources,
          verificationWarning: verification.warning || undefined,
        };
        publishCreationDraft(verifiedDraft);
        return verifiedDraft;
      } catch (error) {
        if (errorCode(error) === FAKE_IP_COMPATIBILITY_REQUIRED) {
          const failedDraft: PersonaCreationDraft = {
            ...sourceDraft,
            phase: 'failed',
            generationRequestId: undefined,
            generationJobId: undefined,
          };
          publishCreationDraft(failedDraft);
          setGenError(t('settings.fakeIpCompatibilityPromptDesc', { ns: 'app' }));
          setFakeIpCompatibilityRetry({ kind: 'verification', draft: failedDraft });
          return null;
        }
        const warning = (error as Error).message || t('personaPreview.reference.verificationUnavailable');
        const fallbackDraft: PersonaCreationDraft = {
          ...sourceDraft,
          phase: sourceDraft.fidelityLevel === 'faithful' ? 'failed' : 'reviewing',
          identityVerified: false,
          verificationWarning: warning,
        };
        publishCreationDraft(fallbackDraft);
        if (sourceDraft.fidelityLevel === 'faithful') {
          setGenError(t('personaPreview.reference.faithfulVerificationRequired'));
          return null;
        }
        return fallbackDraft;
      }
    },
    [i18n.language, llmConfig, publishCreationDraft, t],
  );

  const handleResolveOrGenerate = useCallback(async () => {
    const sourceDraft = creationDraftRef.current;
    const description = sourceDraft?.description.trim() || '';
    if (
      !sourceDraft ||
      disabled ||
      !description ||
      generating ||
      creationSubmissionInFlightRef.current
    ) {
      return;
    }

    creationSubmissionInFlightRef.current = true;
    try {
      if (sourceDraft.phase === 'reviewing' || sourceDraft.phase === 'failed') {
        if (!sourceDraft.referenceConfirmed) return;
        if (sourceDraft.reference.sourceKind !== 'original' && !sourceDraft.reference.name.trim()) {
          return;
        }
        const retryDraft: PersonaCreationDraft = {
          ...sourceDraft,
          generationRequestId: createStableId(),
          generationJobId: undefined,
        };
        const verifiedDraft = await verifyDraftReference(retryDraft);
        if (!verifiedDraft) return;
        await runGeneration(verifiedDraft, buildGenerationIntent(verifiedDraft));
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
        setDescriptionExpanded(false);
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
        setDescriptionExpanded(false);
        publishCreationDraft(applyResolution(resolvingDraft, fallbackResolution));
        setGenError(t('personaPreview.reference.resolveFailed'));
      }
    } finally {
      creationSubmissionInFlightRef.current = false;
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
    verifyDraftReference,
  ]);

  const enableFakeIpCompatibilityAndRetry = useCallback(async () => {
    const pendingRetry = fakeIpCompatibilityRetry;
    if (!pendingRetry || enablingFakeIpCompatibility) {
      return;
    }
    setEnablingFakeIpCompatibility(true);
    setGenError(null);
    try {
      const response = await configApi.get();
      if (!response.data) {
        throw new Error(t('personaPreview.generationFailedUnknown'));
      }
      const nextConfig = structuredClone(response.data);
      nextConfig.tools.builtIn.webFetch.allowRfc2544BenchmarkRange = true;
      await configApi.update(nextConfig);
      setFakeIpCompatibilityRetry(null);

      if (pendingRetry.kind === 'verification') {
        const verifiedDraft = await verifyDraftReference(pendingRetry.draft);
        if (verifiedDraft) {
          await runGeneration(verifiedDraft, buildGenerationIntent(verifiedDraft));
        }
        return;
      }
      await runGeneration(pendingRetry.draft, pendingRetry.intent);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setGenError(t('settings.fakeIpCompatibilityEnableFailed', { ns: 'app', message }));
    } finally {
      setEnablingFakeIpCompatibility(false);
    }
  }, [
    enablingFakeIpCompatibility,
    fakeIpCompatibilityRetry,
    runGeneration,
    t,
    verifyDraftReference,
  ]);

  const editCustomReference = useCallback(
    (customDraft: CustomPersonaDraft, forceResearchRefresh = false) => {
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
        fidelityLevel: intent?.fidelity_level || defaultFidelityLevel(editableReference.sourceKind),
        researchPreference:
          intent?.research.preference ||
          (editableReference.sourceKind === 'original' || editableReference.sourceKind === 'private_person_reference'
            ? 'disabled'
            : 'auto'),
        referenceUrlsText: intent?.research.reference_urls.join('\n') || '',
        referenceModified: false,
        identityVerified: forceResearchRefresh ? false : intent?.research.identity_verified || false,
        verificationFingerprint: forceResearchRefresh ? undefined : intent?.research.verification_fingerprint || undefined,
        verificationSources: forceResearchRefresh ? [] : customDraft.referenceDossier?.sources || [],
        verificationWarning: forceResearchRefresh ? undefined : customDraft.referenceDossier?.warning || undefined,
        forceResearchRefresh,
        constraintsText: (intent?.explicit_constraints || []).join('\n'),
        editingPersonaSlug: customDraft.slug,
        revision: (customDraft.revision || 1) + 1,
      });
      setDescriptionExpanded(false);
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
      ) &&
      (
        creationDraft.reference.sourceKind === 'original' ||
        creationDraft.reference.sourceKind === 'private_person_reference' ||
        creationDraft.researchPreference === 'disabled' ||
        referenceUrlsAreValid(creationDraft.referenceUrlsText)
      )
    );
  const generationButtonLabel =
    creationDraft?.phase === 'resolving'
      ? t('personaPreview.reference.resolving')
      : creationDraft?.phase === 'verifying'
        ? t('personaPreview.reference.verifying')
      : creationDraft?.phase === 'generating'
        ? t('personaPreview.generating')
        : creationNeedsConfirmation
          ? t('personaPreview.reference.confirmAndGenerate')
          : t('personaPreview.generate');
  const showDescriptionSummary =
    Boolean(creationDraft?.resolution) && creationNeedsConfirmation;
  const showDescriptionEditor = !showDescriptionSummary || descriptionExpanded;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      {confirmationError && (
        <div
          role="alert"
          className="rounded-lg border border-destructive/35 bg-destructive/10 px-4 py-3 text-sm text-destructive"
        >
          {confirmationError}
        </div>
      )}
      {/* 标题与模式 tab 同行:让左 rail 和右内容区顶部对齐。detail 阶段左侧带返回 picker 的按钮。 */}
      <div className="flex flex-wrap items-center justify-between gap-3 px-1">
        <div className="flex min-w-0 items-center gap-1.5">
          {stage === 'detail' ? (
            <button
              type="button"
              data-testid="persona-back-to-picker"
              onClick={() => setStage('picker')}
              disabled={disabled}
              aria-label={t('personaPreview.backToPicker')}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors duration-200 hover:bg-muted/70 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20 disabled:opacity-40 motion-reduce:transition-none"
            >
              <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            </button>
          ) : null}
          {stage === 'detail' && mode !== 'create' && activeItem ? (
            <div className="flex min-w-0 items-center gap-3">
              <PreviewAvatar name={activeItem.name} avatar={activeItem.avatar} />
              <h1 className="truncate font-onboarding-display text-[1.65rem] font-bold leading-snug text-foreground">
                {activeItem.name}
              </h1>
            </div>
          ) : (
            <h1 className="font-onboarding-display text-[1.9rem] font-bold leading-snug text-foreground">
              {stage === 'detail' && mode === 'create'
                ? t('personaPreview.createCustomTitle')
                : t('steps.personaPreview')}
            </h1>
          )}
        </div>
        {stage === 'detail' && mode !== 'create' ? (
          <div
            role="group"
            aria-label={t('personaPreview.modeLabel', { name: activeItem?.name || '' })}
            className="flex w-fit shrink-0 items-center gap-1 rounded-lg bg-muted/45 p-1"
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
        ) : null}
      </div>
      <AnimatePresence initial={false} mode="wait">
        {stage === 'picker' ? (
          <motion.div
            key="persona-picker"
            className="min-h-0 flex-1 overflow-y-auto"
            initial={shouldReduceMotion ? false : { opacity: 0, x: -16 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: shouldReduceMotion ? 0 : 0.24, ease: [0.22, 1, 0.36, 1] }}
          >
            {/* Picker: 大卡片网格,先看全貌再进入单个预览。卡片主体点击=选中并开聊;
                hover/聚焦时底部浮现「和我聊聊 / 看看简介」两个入口。 */}
            <div className="grid grid-cols-2 gap-3 p-1 sm:grid-cols-3 xl:grid-cols-4">
              {railItems.map((p) => {
                const selected = activeSeed === p.slug;
                return (
                  <div
                    key={p.slug}
                    className={cn(
                      'group relative flex flex-col items-center gap-3 rounded-xl px-4 py-6 text-center shadow-[inset_0_0_0_1px_hsl(var(--border)/0.58)] transition-[background-color,box-shadow,transform] duration-200 hover:-translate-y-0.5 hover:bg-card hover:shadow-[inset_0_0_0_1px_hsl(var(--primary)/0.35),0_10px_28px_-24px_hsl(var(--foreground)/0.3)] motion-reduce:transform-none motion-reduce:transition-none',
                      selected
                        ? 'bg-card shadow-[inset_0_0_0_1px_hsl(var(--primary)/0.38)]'
                        : 'bg-transparent',
                    )}
                  >
                    <button
                      type="button"
                      data-testid={`persona-pick-${p.slug}`}
                      aria-pressed={selected}
                      aria-label={p.name}
                      disabled={disabled}
                      onClick={() => onActiveSeedChange(p.slug)}
                      className="absolute inset-0 rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20"
                    />
                    {selected ? (
                      <span
                        aria-hidden="true"
                        className="absolute right-3 top-3 z-10 flex h-5 w-5 items-center justify-center rounded-full bg-primary text-primary-foreground"
                      >
                        <Check className="h-3 w-3" />
                      </span>
                    ) : null}
                    <span className="pointer-events-none flex min-w-0 flex-col items-center gap-3">
                      <PreviewAvatar name={p.name} avatar={p.avatar} size="lg" />
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-semibold text-foreground">{p.name}</span>
                      </span>
                    </span>
                    <span className="relative flex h-9 w-full items-center justify-center">
                      <span className="pointer-events-none absolute inset-0 flex items-start justify-center text-xs leading-5 text-muted-foreground transition-opacity duration-200 line-clamp-2 group-hover:opacity-0 group-focus-within:opacity-0 motion-reduce:transition-none">
                        {p.description}
                      </span>
                      <span className="absolute inset-0 z-10 flex items-center justify-center gap-1.5 opacity-0 transition-opacity duration-200 group-hover:opacity-100 group-focus-within:opacity-100 motion-reduce:transition-none">
                        <button
                          type="button"
                          data-testid={`persona-chat-${p.slug}`}
                          disabled={disabled}
                          onClick={() => enterPersona(p, 'chat')}
                          className="rounded-md bg-muted px-2.5 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary"
                        >
                          {t('personaPreview.chatAction')}
                        </button>
                        <button
                          type="button"
                          data-testid={`persona-profile-${p.slug}`}
                          disabled={disabled}
                          onClick={() => enterPersona(p, 'profile')}
                          className="rounded-md bg-muted px-2.5 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                        >
                          {t('personaPreview.profileAction')}
                        </button>
                      </span>
                    </span>
                  </div>
                );
              })}
              <button
                type="button"
                data-testid="persona-create-custom"
                aria-pressed={false}
                disabled={disabled}
                onClick={() => {
                  if (!creationDraftRef.current) {
                    publishCreationDraft(createEmptyCreationDraft());
                  }
                  setDescriptionExpanded(true);
                  setMode('create');
                  setGenError(null);
                  setStage('detail');
                }}
                className="group flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border px-4 py-6 text-center text-muted-foreground transition-colors duration-200 hover:border-primary/45 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20 motion-reduce:transition-none"
              >
                <span className="flex h-16 w-16 items-center justify-center rounded-full bg-muted/70 text-2xl shadow-[inset_0_0_0_1px_hsl(var(--border)/0.65)] transition-colors group-hover:text-foreground">
                  +
                </span>
                <span className="text-sm font-semibold">{t('personaPreview.createCustom')}</span>
              </button>
            </div>
          </motion.div>
        ) : (
          <motion.div
            key="persona-detail"
            className="flex min-h-0 flex-1 flex-col"
            initial={shouldReduceMotion ? false : { opacity: 0, x: 16 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: shouldReduceMotion ? 0 : 0.24, ease: [0.22, 1, 0.36, 1] }}
          >
      <fieldset
        disabled={disabled}
        className="m-0 flex min-h-0 min-w-0 flex-1 flex-col border-0 p-0"
      >
        <legend className="sr-only">{t('steps.personaPreview')}</legend>
      {/* Detail: either the preview chat or the custom-persona composer.
          人格切换统一回到 picker 完成,这里不再有左侧 rail。 */}
      {mode === 'create' ? (
        <div className="flex min-h-0 flex-1 flex-col gap-4">
          <motion.div layout className="flex-1 overflow-y-auto px-1 py-1 sm:px-4 sm:py-3 lg:px-7">
            <AnimatePresence initial={false} mode="popLayout">
              {showDescriptionSummary && !descriptionExpanded ? (
                <motion.div
                  layout
                  key="description-summary"
                  data-testid="persona-custom-description-summary"
                  initial={shouldReduceMotion ? false : { opacity: 0, y: -8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={shouldReduceMotion ? undefined : { opacity: 0, y: -5 }}
                  transition={{ duration: shouldReduceMotion ? 0 : 0.24, ease: [0.22, 1, 0.36, 1] }}
                  className="flex items-center justify-between gap-4 rounded-lg bg-accent/75 px-4 py-3 shadow-[inset_0_0_0_1px_hsl(var(--primary)/0.12)]"
                >
                  <p className="min-w-0 truncate text-sm font-semibold text-foreground">
                    {creationDraft?.description}
                  </p>
                  <button
                    type="button"
                    data-testid="persona-custom-description-edit"
                    onClick={() => setDescriptionExpanded(true)}
                    className="group flex shrink-0 items-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium text-muted-foreground transition-colors duration-200 hover:bg-background/65 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/15 motion-reduce:transition-none"
                  >
                    <PencilLine className="h-3.5 w-3.5" aria-hidden="true" />
                    {t('personaPreview.reference.edit')}
                  </button>
                </motion.div>
              ) : null}
            </AnimatePresence>

            <motion.div
              layout
              aria-hidden={!showDescriptionEditor}
              className={cn(
                'grid transition-[grid-template-rows,opacity] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] motion-reduce:transition-none',
                showDescriptionEditor
                  ? 'grid-rows-[1fr] opacity-100'
                  : 'pointer-events-none grid-rows-[0fr] opacity-0',
              )}
            >
              <div className="min-h-0 overflow-hidden">
                <div>
                  {!showDescriptionSummary && (
                    <>
                      <h3 className="text-base font-semibold tracking-[-0.01em] text-foreground">
                        {t('personaPreview.createCustomTitle')}
                      </h3>
                      <p className="mt-1.5 max-w-2xl text-sm leading-6 text-muted-foreground">
                        {t('personaPreview.createCustomHint')}
                      </p>
                    </>
                  )}
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
                      setDescriptionExpanded(true);
                      setGenError(null);
                      setGenStages([]);
                    }}
                    placeholder={t('personaPreview.customDescriptionPlaceholder')}
                    disabled={generating || !showDescriptionEditor}
                    tabIndex={showDescriptionEditor ? undefined : -1}
                    rows={2}
                    className={cn(
                      'w-full resize-none rounded-lg px-4 py-3 text-base leading-7 disabled:opacity-70',
                      ONBOARDING_FIELD_MUTED_CLASS,
                      !showDescriptionSummary && 'mt-4',
                    )}
                  />
                </div>
              </div>
            </motion.div>

            <AnimatePresence initial={false}>
              {creationDraft?.resolution && creationNeedsConfirmation ? (
                <motion.div
                  layout
                  key="persona-reference-editor"
                  initial={shouldReduceMotion ? false : { opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={shouldReduceMotion ? undefined : { opacity: 0, y: 8 }}
                  transition={{ duration: shouldReduceMotion ? 0 : 0.28, ease: [0.22, 1, 0.36, 1] }}
                >
                  <PersonaReferenceEditor
                    resolution={creationDraft.resolution}
                    value={creationDraft.reference}
                    fidelityLevel={creationDraft.fidelityLevel}
                    constraintsText={creationDraft.constraintsText}
                    researchPreference={creationDraft.researchPreference}
                    referenceUrlsText={creationDraft.referenceUrlsText}
                    referenceUrlsValid={referenceUrlsAreValid(creationDraft.referenceUrlsText)}
                    disabled={generating}
                    onChange={(reference) => {
                      publishCreationDraft({
                        ...creationDraft,
                        reference,
                        referenceConfirmed: true,
                        referenceModified: true,
                        identityVerified: false,
                        verificationFingerprint: undefined,
                        verificationSources: [],
                        verificationWarning: undefined,
                        fidelityLevel:
                          reference.sourceKind === creationDraft.reference.sourceKind
                            ? creationDraft.fidelityLevel
                            : defaultFidelityLevel(reference.sourceKind),
                        researchPreference:
                          reference.sourceKind === 'original' || reference.sourceKind === 'private_person_reference'
                            ? 'disabled'
                            : creationDraft.researchPreference === 'disabled'
                              ? 'auto'
                              : creationDraft.researchPreference,
                        referenceUrlsText:
                          reference.sourceKind === 'original' || reference.sourceKind === 'private_person_reference'
                            ? ''
                            : creationDraft.referenceUrlsText,
                      });
                    }}
                    onFidelityLevelChange={(fidelityLevel) => {
                      publishCreationDraft({
                        ...creationDraft,
                        fidelityLevel,
                        referenceConfirmed: true,
                      });
                    }}
                    onConstraintsTextChange={(constraintsText) => {
                      publishCreationDraft({
                        ...creationDraft,
                        constraintsText,
                      });
                    }}
                    onResearchPreferenceChange={(researchPreference) => {
                      publishCreationDraft({
                        ...creationDraft,
                        researchPreference,
                        identityVerified: false,
                        verificationFingerprint: undefined,
                        verificationSources: [],
                        verificationWarning: undefined,
                      });
                    }}
                    onReferenceUrlsTextChange={(referenceUrlsText) => {
                      publishCreationDraft({
                        ...creationDraft,
                        referenceUrlsText,
                        identityVerified: false,
                        verificationFingerprint: undefined,
                        verificationSources: [],
                        verificationWarning: undefined,
                      });
                    }}
                  />
                  {creationDraft.verificationSources.length > 0 && (
                    <details
                      data-testid="persona-reference-verification-sources"
                      className="mt-4 rounded-lg border border-border/45 bg-muted/20 px-3 py-2"
                    >
                      <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
                        {t('personaPreview.reference.verificationSources', {
                          count: creationDraft.verificationSources.length,
                        })}
                      </summary>
                      <div className="mt-2 space-y-1 border-t border-border/40 pt-2">
                        {creationDraft.verificationSources.map((source) => (
                          <a
                            key={source.source_id}
                            href={source.url}
                            target="_blank"
                            rel="noreferrer"
                            className="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 text-xs hover:bg-background"
                          >
                            <span className="truncate">{source.title || source.domain}</span>
                            <ExternalLink className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                          </a>
                        ))}
                      </div>
                    </details>
                  )}
                </motion.div>
              ) : null}
            </AnimatePresence>

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
                      : creationDraft?.phase === 'verifying'
                        ? t('personaPreview.reference.verifying')
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

            {fakeIpCompatibilityRetry ? (
              <div
                className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-500/35 bg-amber-500/10 px-3 py-2.5"
                role="alert"
                data-testid="persona-fake-ip-compatibility"
              >
                <div className="min-w-0 flex-1">
                  <div className="text-xs font-medium text-foreground">
                    {t('settings.fakeIpCompatibilityPromptTitle', { ns: 'app' })}
                  </div>
                  <div className="mt-0.5 text-[11px] leading-4 text-muted-foreground">
                    {genError || t('settings.fakeIpCompatibilityPromptDesc', { ns: 'app' })}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => void enableFakeIpCompatibilityAndRetry()}
                  disabled={enablingFakeIpCompatibility}
                  className="shrink-0 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition hover:bg-primary/90 disabled:opacity-50"
                >
                  {enablingFakeIpCompatibility
                    ? t('settings.fakeIpCompatibilityEnabling', { ns: 'app' })
                    : t('settings.fakeIpCompatibilityEnableRetry', { ns: 'app' })}
                </button>
              </div>
            ) : genError ? (
              <p className="mt-3 text-xs text-destructive" role="alert">
                {genError}
              </p>
            ) : null}
          </motion.div>

          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={() => {
                setMode('chat');
                setStage('picker');
                setGenError(null);
                setFakeIpCompatibilityRetry(null);
                publishCreationDraft(null);
              }}
              disabled={generating}
              className="rounded-md px-4 py-2 text-sm text-muted-foreground transition-colors duration-200 hover:bg-muted/70 hover:text-foreground disabled:opacity-50 motion-reduce:transition-none"
            >
              {t('personaPreview.cancelCreate')}
            </button>
            <button
              type="button"
              data-testid="persona-custom-generate"
              onClick={() => void handleResolveOrGenerate()}
              aria-busy={generating}
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
        <div className="flex min-h-0 flex-1 flex-col gap-3">
          {activeItem?.customDraft?.intent?.reference && (
            <div className="space-y-2">
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
              <details
                data-testid="persona-reference-sources"
                className="rounded-lg border border-border/45 bg-background/60 px-3 py-2"
              >
                <summary className="cursor-pointer list-none text-xs text-muted-foreground">
                  {activeItem.customDraft.referenceDossier?.grounding_status === 'verified'
                    ? t('personaPreview.reference.sourcesVerified', {
                        count: activeItem.customDraft.referenceDossier.sources.length,
                      })
                    : activeItem.customDraft.referenceDossier?.grounding_status === 'unavailable'
                      ? t('personaPreview.reference.sourcesUnavailable')
                      : activeItem.customDraft.referenceDossier?.grounding_status === 'insufficient'
                        ? t('personaPreview.reference.sourcesInsufficient')
                        : t('personaPreview.reference.sourcesUnverified')}
                </summary>
                <div className="mt-2 space-y-2 border-t border-border/40 pt-2">
                  {activeItem.customDraft.referenceDossier?.sources.map((source) => (
                    <a
                      key={source.source_id}
                      href={source.url}
                      target="_blank"
                      rel="noreferrer"
                      className="flex items-start justify-between gap-3 rounded-md px-2 py-1.5 text-xs hover:bg-muted/55"
                    >
                      <span className="min-w-0">
                        <span className="block truncate font-medium text-foreground">
                          {source.title || source.domain}
                        </span>
                        <span className="block truncate text-muted-foreground">{source.domain}</span>
                      </span>
                      <ExternalLink className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
                    </a>
                  ))}
                  {activeItem.customDraft.referenceDossier?.warning && (
                    <p className="px-2 text-xs leading-5 text-muted-foreground">
                      {activeItem.customDraft.referenceDossier.warning}
                    </p>
                  )}
                  <button
                    type="button"
                    data-testid="persona-reference-refresh"
                    onClick={() => editCustomReference(activeItem.customDraft!, true)}
                    className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium text-primary hover:bg-primary/10"
                  >
                    <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                    {t('personaPreview.reference.refreshSources')}
                  </button>
                </div>
              </details>
            </div>
          )}
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
              <div
                ref={transcriptScrollRef}
                className="flex-1 overflow-y-auto rounded-xl bg-muted/40 p-4"
              >
                {activeTranscript.length === 0 && (
                  <div className="flex h-full items-center justify-center">
                    <p className="max-w-sm text-center text-sm leading-6 text-muted-foreground">
                      {t('personaPreview.emptyHint')}
                    </p>
                  </div>
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
                      className="min-w-0 flex-1 rounded-md border border-border/55 bg-background px-3 py-2 text-sm text-foreground outline-none transition-[border-color,box-shadow] duration-200 placeholder:text-muted-foreground/60 focus-visible:border-primary/45 focus-visible:ring-2 focus-visible:ring-primary/15"
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
                  className="flex-1 rounded-md border border-border/55 bg-background px-3 py-2 text-sm text-foreground outline-none transition-[border-color,box-shadow] duration-200 focus-visible:border-primary/45 focus-visible:ring-2 focus-visible:ring-primary/15"
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
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
