/**
 * usePersonality hook - Manages personality configuration state and operations.
 *
 * This hook encapsulates all personality-related business logic including:
 * - Loading and saving personality configurations
 * - Switching between personalities
 * - AI generation
 * - CRUD operations
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useCenterRefresh } from '@/hooks/useCenterRefresh';
import { useRequestOwner } from '@/hooks/useRequestOwner';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';
import {
  personasApi,
  DEFAULT_PERSONALITY_CONFIG,
  PERSONA_GENERATION_STAGE_IDS,
  type PersonalityConfig,
  type PersonaGenerationStage,
  type PersonaSummary,
  type PersonaDetail,
  type SignatureTrigger,
  type PersonaGenerationStageId,
} from '@/api/modules/personas';
import { handleError } from '@/utils/error-handler';
import { formatPersonaValidationIssues, validatePersonalityConfig } from '@/utils/personaValidation';

// ============================================================================
// Types
// ============================================================================

export interface PersonalityInfo {
  id: string;          // persona_id (UUID)
  name: string;        // display name
  displayName: string;
  subtitle?: string;
  avatar?: string;
}

export interface UsePersonalityOptions {
  initialPersonalityId?: string;
}

export interface UsePersonalityReturn {
  // State
  config: PersonalityConfig;
  list: PersonalityInfo[];
  currentId: string;
  selectedId: string;
  isNewMode: boolean;
  loading: boolean;
  saving: boolean;
  conflict: boolean;
  generating: boolean;
  generationProgress: number;
  generationStageKey: PersonaGenerationStageId;
  switching: boolean;
  selectedInfo: PersonalityInfo | undefined;
  switchPrompt: {
    phrase: string;
    fromName: string;
    toName: string;
    targetId: string;
  } | null;

  // Form state
  prompt: string;
  setPrompt: (value: string) => void;

  // Actions
  patch: (fn: (draft: PersonalityConfig) => void) => void;
  selectPersonality: (id: string) => void;
  startNewPersonality: () => void;
  cancelNewPersonality: () => void;
  save: () => Promise<void>;
  generate: () => Promise<void>;
  switchPersonality: () => Promise<void>;
  confirmSwitchPersonality: () => Promise<void>;
  cancelSwitchPersonality: () => void;
  deletePersonality: () => Promise<void>;
  deleteConfirmOpen: boolean;
  requestDeletePersonality: () => void;
  confirmDeletePersonality: () => Promise<void>;
  cancelDeletePersonality: () => void;
  reload: () => Promise<void>;
}

// ============================================================================
// Constants
// ============================================================================

const CONFIDENCE_OPTIONS = ['Extremely High', 'High', 'Medium', 'Low'] as const;
const buildPendingGenerationStages = (): PersonaGenerationStage[] =>
  PERSONA_GENERATION_STAGE_IDS.map((stageId) => ({ stage_id: stageId, status: 'pending' }));

const getGenerationStageKey = (stages: PersonaGenerationStage[]): PersonaGenerationStageId => {
  const running = stages.find((stage) => stage.status === 'running');
  const pending = stages.find((stage) => stage.status === 'pending');
  const active = running || pending || stages[stages.length - 1];
  return PERSONA_GENERATION_STAGE_IDS.includes(active?.stage_id as PersonaGenerationStageId)
    ? (active.stage_id as PersonaGenerationStageId)
    : PERSONA_GENERATION_STAGE_IDS[0];
};

const getGenerationTargetLanguage = (uiLanguage?: string): string => {
  const language = (uiLanguage || '').toLowerCase();
  if (language.startsWith('zh')) return 'Chinese';
  if (language.startsWith('ja')) return 'Japanese';
  return 'English';
};

const getGenerationProgress = (stages: PersonaGenerationStage[], generating: boolean): number => {
  if (!generating || stages.length === 0) return 0;
  const completedCount = stages.filter((stage) => stage.status === 'completed').length;
  const failedCount = stages.filter((stage) => stage.status === 'failed').length;
  if (completedCount + failedCount >= stages.length) {
    return 100;
  }
  return Math.round((completedCount / stages.length) * 100);
};

// ============================================================================
// Helper Functions
// ============================================================================

const normalizeTrigger = (item: Partial<SignatureTrigger>): SignatureTrigger => ({
  trigger_id: item.trigger_id || '',
  activates_when: item.activates_when || '',
  behavior_shift: item.behavior_shift || '',
  intensity_levels: item.intensity_levels || {},
  exit_behavior: item.exit_behavior || '',
});

const mergeConfig = (incoming: Partial<PersonalityConfig>): PersonalityConfig => {
  const next = structuredClone(DEFAULT_PERSONALITY_CONFIG);
  next.name = incoming.name || next.name;
  next.avatar = incoming.avatar || next.avatar;
  next.description = incoming.description || next.description;
  next.appearance_prompt = incoming.appearance_prompt || next.appearance_prompt;
  next.identity_core = { ...next.identity_core, ...(incoming.identity_core || {}) };
  next.idiolect = { ...next.idiolect, ...(incoming.idiolect || {}) };
  next.registers = { ...next.registers, ...(incoming.registers || {}) };
  next.quiet_hours = incoming.quiet_hours ?? next.quiet_hours;
  const triggers = incoming.signature_triggers || next.signature_triggers;
  next.signature_triggers = triggers.length > 0 ? triggers.map(normalizeTrigger) : [normalizeTrigger({})];
  next.persona_layers = incoming.persona_layers ?? next.persona_layers;
  next.dynamic_state_rules = incoming.dynamic_state_rules ?? next.dynamic_state_rules;
  next.milestone_conditions = incoming.milestone_conditions ?? next.milestone_conditions;
  next.interim_lines = incoming.interim_lines ?? next.interim_lines;
  next.bootstrap = incoming.bootstrap ?? next.bootstrap;
  return next;
};

const parseLines = (value: string): string[] =>
  value
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean);

const toLines = (items: string[]): string => items.join('\n');

const getInitials = (name: string): string => {
  const words = name.split(/[\s_-]+/).filter(Boolean);
  if (words.length === 0) return name.charAt(0).toUpperCase();
  if (words.length === 1) return words[0].charAt(0).toUpperCase();
  return (words[0].charAt(0) + words[words.length - 1].charAt(0)).toUpperCase();
};

const requirePersonaSnapshot = (detail: PersonaDetail | null | undefined, id?: string): PersonaDetail => {
  if (!detail || (id && detail.persona_id !== id) || !Number.isFinite(detail.updated_at) || detail.updated_at < 0) {
    throw new Error('Invalid persona snapshot');
  }
  return detail;
};

// ============================================================================
// Hook Implementation
// ============================================================================

export function usePersonality(
  options: UsePersonalityOptions = {}
): UsePersonalityReturn {
  const { initialPersonalityId } = options;
  const { t, i18n } = useTranslation('app');
  const beginRequest = useRequestOwner();
  const view = useRef({ id: initialPersonalityId || '', generation: 0 });
  const baseline = useRef<{ id: string; revision: number; config: PersonalityConfig } | null>(null);
  const createId = useRef('');
  const savePending = useRef(false);
  const generationPending = useRef(false);
  const [conflict, setConflict] = useState(false);

  // Loading states
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [generationStages, setGenerationStages] = useState<PersonaGenerationStage[]>(buildPendingGenerationStages);
  const [switching, setSwitching] = useState(false);

  // Personality state – identity is now UUID-based
  const [currentId, setCurrentId] = useState('');
  const [selectedId, setSelectedIdState] = useState(initialPersonalityId || '');
  const setSelectedId = useCallback((id: string) => {
    view.current = { id, generation: view.current.generation + 1 };
    baseline.current = null;
    beginRequest('detail');
    beginRequest('generation');
    setSelectedIdState(id);
    setLoading(false);
    generationPending.current = false;
    setGenerating(false);
    setConflict(false);
  }, [beginRequest]);
  const [isNewMode, setIsNewMode] = useState(false);
  const [config, setConfigState] = useState<PersonalityConfig>(DEFAULT_PERSONALITY_CONFIG);
  const configRef = useRef(config);
  const setConfig = useCallback((next: PersonalityConfig) => {
    configRef.current = next;
    setConfigState(next);
  }, []);
  const [list, setList] = useState<PersonalityInfo[]>([]);

  // Form state
  const [prompt, setPrompt] = useState('');
  const [switchPrompt, setSwitchPrompt] = useState<{
    phrase: string;
    fromName: string;
    toName: string;
    targetId: string;
  } | null>(null);

  // ============================================================================
  // Patch Function
  // ============================================================================

  const patch = useCallback((fn: (draft: PersonalityConfig) => void) => {
    const next = structuredClone(configRef.current);
    fn(next);
    setConfig(next);
  }, [setConfig]);

  // ============================================================================
  // Data Loading (registry-backed)
  // ============================================================================

  const loadList = useCallback(async () => {
    const isCurrent = beginRequest('list');
    try {
      const result = await personasApi.list();
      const summaries: PersonaSummary[] = result.data || [];
      const items: PersonalityInfo[] = summaries.map((s) => ({
        id: s.persona_id,
        name: s.name,
        displayName: s.name,
        subtitle: s.description || '',
        avatar: s.avatar_path || '',
      }));
      if (isCurrent()) setList(items);
    } catch {
      // Keep the last usable registry during a temporary connection failure.
    }
  }, [beginRequest]);

  const loadCurrent = useCallback(async (): Promise<string> => {
    const isCurrent = beginRequest('active');
    try {
      const result = await personasApi.getActive();
      const activeId = result.persona_id ?? '';
      if (!isCurrent()) return '';
      setCurrentId(activeId);
      return activeId;
    } catch {
      return '';
    }
  }, [beginRequest]);

  const loadOne = useCallback(
    async (id: string, silent = false) => {
      if (!id) return;
      const selected = view.current;
      if (selected.id !== id) return;
      const saved = baseline.current;
      const draft = configRef.current;
      if (silent && (!saved || JSON.stringify(draft) !== JSON.stringify(saved.config) || savePending.current || generationPending.current)) return;
      const isCurrent = beginRequest('detail');
      if (!silent) setLoading(true);
      try {
        const result = await personasApi.get(id);
        const detail = requirePersonaSnapshot(result.data, id);
        if (!isCurrent() || view.current !== selected || baseline.current !== saved || configRef.current !== draft) return;
        const next = mergeConfig(detail.config as Partial<PersonalityConfig>);
        baseline.current = { id, revision: detail.updated_at, config: next };
        setConfig(next);
        setConflict(false);
      } catch {
        if (isCurrent() && !silent) toast.error(t('personality.loadFailed'));
      } finally {
        if (isCurrent()) setLoading(false);
      }
    },
    [t, beginRequest, setConfig]
  );

  // Initial load
  useEffect(() => {
    let active = true;
    const init = async () => {
      const [activeId] = await Promise.all([loadCurrent(), loadList()]);
      if (!active) return;
      const targetId = view.current.id || activeId;
      if (targetId && targetId !== '__new__') {
        if (!view.current.id) setSelectedId(targetId);
        await loadOne(targetId, baseline.current !== null);
      }
    };
    void init();
    return () => { active = false; };
  }, [loadCurrent, loadList, loadOne, setSelectedId]);

  useCenterRefresh(async () => {
    await Promise.all([loadList(), loadCurrent(), view.current.id === '__new__' ? Promise.resolve() : loadOne(view.current.id, true)]);
  });

  // ============================================================================
  // Actions
  // ============================================================================

  const selectPersonality = useCallback(
    (id: string) => {
      if (isNewMode) {
        setIsNewMode(false);
      }
      setSelectedId(id);
      void loadOne(id);
    },
    [isNewMode, loadOne, setSelectedId]
  );

  const startNewPersonality = useCallback(() => {
    createId.current = crypto.randomUUID();
    setIsNewMode(true);
    setSelectedId('__new__');
    setConfig(structuredClone(DEFAULT_PERSONALITY_CONFIG));
  }, [setConfig, setSelectedId]);

  const cancelNewPersonality = useCallback(() => {
    setIsNewMode(false);
    setSelectedId(currentId);
    void loadOne(currentId);
  }, [currentId, loadOne, setSelectedId]);

  const selectedInfo = useMemo(
    () => list.find((item) => item.id === selectedId),
    [list, selectedId]
  );

  const save = useCallback(async () => {
    if (savePending.current || loading) return;
    const selected = view.current;
    const submitted = configRef.current;
    const saved = baseline.current;
    if (!isNewMode && (!saved || saved.id !== selected.id)) return;
    const validation = validatePersonalityConfig(config);
    if (!validation.isMinimumReady) {
      toast.warning(t('personality.validation.missing', {
        fields: formatPersonaValidationIssues(validation.minimumIssues, t).join(', '),
      }));
      return;
    }

    // Validate name in create mode
    if (isNewMode) {
      const name = config.name?.trim();
      if (!name) {
        toast.warning(t('personality.nameRequired'));
        return;
      }
    }

    savePending.current = true;
    setSaving(true);
    const isCurrent = beginRequest('save');
    try {
      if (isNewMode) {
        const result = await personasApi.create({ persona_id: createId.current, config_json: JSON.stringify(submitted) });
        const detail = requirePersonaSnapshot(result.data, createId.current);
        if (!isCurrent() || view.current !== selected) return;
        const newerDraft = configRef.current !== submitted;
        const next = mergeConfig(detail.config as Partial<PersonalityConfig>);
        setSelectedId(detail.persona_id);
        baseline.current = { id: detail.persona_id, revision: detail.updated_at, config: next };
        if (!newerDraft) setConfig(next);
        toast.success(t('personality.createSuccess'));
        setIsNewMode(false);
        await loadList();
      } else {
        const result = await personasApi.update(selected.id, {
          expected_updated_at: saved!.revision,
          name: submitted.name,
          config_json: JSON.stringify(submitted),
        });
        const detail = requirePersonaSnapshot(result.data, selected.id);
        if (!isCurrent() || view.current !== selected) return;
        beginRequest('detail');
        const next = mergeConfig(detail.config as Partial<PersonalityConfig>);
        baseline.current = { id: selected.id, revision: detail.updated_at, config: next };
        if (configRef.current === submitted) setConfig(next);
        setConflict(false);
        toast.success(t('personality.saveSuccess'));
        await loadList();
      }
    } catch (error) {
      if (!isCurrent() || view.current !== selected) return;
      if (typeof error === 'object' && error !== null && 'status' in error && (error.status === 409 || error.status === 428)) {
        setConflict(true);
      } else handleError(error, 'Save personality');
    } finally {
      savePending.current = false;
      if (isCurrent()) setSaving(false);
    }
  }, [config, isNewMode, loadList, loading, t, beginRequest, setConfig, setSelectedId]);

  const generate = useCallback(async () => {
    if (!prompt.trim()) {
      toast.warning(t('personality.generatePromptRequired'));
      return;
    }

    setGenerating(true);
    generationPending.current = true;
    const isCurrent = beginRequest('generation');
    const draftAtStart = configRef.current;
    setGenerationStages(buildPendingGenerationStages());
    try {
      const response = await personasApi.generateWithProgress({
        description: prompt,
        target_language: getGenerationTargetLanguage(i18n.resolvedLanguage || i18n.language),
        current_config: config,
      }, (snapshot) => {
        if (isCurrent()) setGenerationStages(snapshot.stages?.length ? snapshot.stages : buildPendingGenerationStages());
      });
      if (!isCurrent() || configRef.current !== draftAtStart) return;
      const data = (response.data || {}) as Partial<PersonalityConfig>;
      setConfig(mergeConfig(data));
      setPrompt('');
      toast.success(t('personality.generateSuccess'));
    } catch (error) {
      if (isCurrent()) handleError(error, 'Generate personality');
    } finally {
      if (isCurrent()) {
        generationPending.current = false;
        setGenerating(false);
      }
    }
  }, [config, i18n.language, i18n.resolvedLanguage, prompt, t, beginRequest, setConfig]);

  const switchPersonality = useCallback(async () => {
    if (selectedId === currentId) {
      return;
    }

    setSwitching(true);
    try {
      const retentionPhrase = t('personality.switchPromptFallback');
      const currentInfo = list.find((item) => item.id === currentId);
      setSwitchPrompt({
        phrase: retentionPhrase,
        fromName: currentInfo?.displayName || '',
        toName: selectedInfo?.displayName || '',
        targetId: selectedId,
      });
    } finally {
      setSwitching(false);
    }
  }, [currentId, selectedId, selectedInfo?.displayName, list, t]);

  const confirmSwitchPersonality = useCallback(async () => {
    if (!switchPrompt) {
      return;
    }

    setSwitching(true);
    const isCurrent = beginRequest('switch');
    try {
      await personasApi.setActive(switchPrompt.targetId);
      if (!isCurrent()) return;
      beginRequest('active');
      setCurrentId(switchPrompt.targetId);
      setSwitchPrompt(null);
      toast.success(t('personality.switchSuccess', { name: switchPrompt.toName }));
    } catch (error) {
      if (isCurrent()) handleError(error, 'Switch personality');
    } finally {
      if (isCurrent()) setSwitching(false);
    }
  }, [switchPrompt, t, beginRequest]);

  const cancelSwitchPersonality = useCallback(() => {
    setSwitchPrompt(null);
  }, []);

  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const deleteTarget = useRef<{ id: string; revision: number } | null>(null);

  const requestDeletePersonality = useCallback(() => {
    if (!selectedId || selectedId === currentId || !baseline.current || savePending.current) return;
    deleteTarget.current = { id: selectedId, revision: baseline.current.revision };
    setDeleteConfirmOpen(true);
  }, [selectedId, currentId]);

  const confirmDeletePersonality = useCallback(async () => {
    setDeleteConfirmOpen(false);
    const target = deleteTarget.current;
    deleteTarget.current = null;
    if (!target) return;
    const selected = view.current;
    const isCurrent = beginRequest('delete');
    try {
      await personasApi.delete(target.id, target.revision);
      if (!isCurrent()) return;
      await loadList();
      const activeId = await loadCurrent();
      if (isCurrent() && view.current === selected && selected.id === target.id) {
        setSelectedId(activeId);
        await loadOne(activeId);
      }
    } catch (error) {
      if (!isCurrent() || view.current !== selected) return;
      if (typeof error === 'object' && error !== null && 'status' in error && (error.status === 409 || error.status === 428)) setConflict(true);
      else handleError(error, 'Delete personality');
    }
  }, [loadList, loadCurrent, loadOne, beginRequest, setSelectedId]);

  const cancelDeletePersonality = useCallback(() => {
    setDeleteConfirmOpen(false);
  }, []);

  const deletePersonality = confirmDeletePersonality;

  const reload = useCallback(async () => {
    await loadOne(selectedId);
  }, [loadOne, selectedId]);

  const generationStageKey = getGenerationStageKey(generationStages);
  const generationProgress = getGenerationProgress(generationStages, generating);

  // ============================================================================
  // Computed Values
  // ============================================================================

  return {
    // State
    config,
    list,
    currentId,
    selectedId,
    isNewMode,
    loading,
    saving,
    conflict,
    generating,
    generationProgress,
    generationStageKey,
    switching,
    selectedInfo,
    switchPrompt,

    // Form state
    prompt,
    setPrompt,

    // Actions
    patch,
    selectPersonality,
    startNewPersonality,
    cancelNewPersonality,
    save,
    generate,
    switchPersonality,
    confirmSwitchPersonality,
    cancelSwitchPersonality,
    deletePersonality,
    deleteConfirmOpen,
    requestDeletePersonality,
    confirmDeletePersonality,
    cancelDeletePersonality,
    reload,
  };
}

// ============================================================================
// Export Utilities
// ============================================================================

export {
  CONFIDENCE_OPTIONS,
  parseLines,
  toLines,
  getInitials,
  normalizeTrigger,
  mergeConfig,
};
