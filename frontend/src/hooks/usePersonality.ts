/**
 * usePersonality hook - Manages personality configuration state and operations.
 *
 * This hook encapsulates all personality-related business logic including:
 * - Loading and saving personality configurations
 * - Switching between personalities
 * - AI generation
 * - CRUD operations
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';
import {
  personasApi,
  DEFAULT_PERSONALITY_CONFIG,
  PERSONA_GENERATION_STAGE_IDS,
  type PersonalityConfig,
  type PersonaGenerationStage,
  type PersonaSummary,
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
  targetLanguage: string;
  setTargetLanguage: (value: string) => void;

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

// ============================================================================
// Hook Implementation
// ============================================================================

export function usePersonality(
  options: UsePersonalityOptions = {}
): UsePersonalityReturn {
  const { initialPersonalityId } = options;
  const { t, i18n } = useTranslation('app');

  // Loading states
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [generationStages, setGenerationStages] = useState<PersonaGenerationStage[]>(buildPendingGenerationStages);
  const [switching, setSwitching] = useState(false);

  // Personality state – identity is now UUID-based
  const [currentId, setCurrentId] = useState('');
  const [selectedId, setSelectedId] = useState(initialPersonalityId || '');
  const [isNewMode, setIsNewMode] = useState(false);
  const [config, setConfig] = useState<PersonalityConfig>(DEFAULT_PERSONALITY_CONFIG);
  const [list, setList] = useState<PersonalityInfo[]>([]);

  // Form state
  const [prompt, setPrompt] = useState('');
  const [targetLanguage, setTargetLanguage] = useState('Auto');
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
    setConfig((prev) => {
      const next = structuredClone(prev);
      fn(next);
      return next;
    });
  }, []);

  // ============================================================================
  // Data Loading (registry-backed)
  // ============================================================================

  const loadList = useCallback(async () => {
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
      setList(items);
    } catch {
      setList([]);
    }
  }, []);

  const loadCurrent = useCallback(async (): Promise<string> => {
    try {
      const result = await personasApi.getActive();
      const activeId = result.persona_id ?? '';
      setCurrentId(activeId);
      setSelectedId((prev) => prev || activeId);
      return activeId;
    } catch {
      setCurrentId('');
      return '';
    }
  }, []);

  const loadOne = useCallback(
    async (id: string) => {
      if (!id) return;
      setLoading(true);
      try {
        const result = await personasApi.get(id);
        const detail = result.data;
        if (detail?.config) {
          setConfig(mergeConfig(detail.config as Partial<PersonalityConfig>));
        }
      } catch {
        toast.error(t('personality.loadFailed'));
      } finally {
        setLoading(false);
      }
    },
    [t]
  );

  // Initial load
  useEffect(() => {
    const init = async () => {
      const activeId = await loadCurrent();
      await loadList();
      if (activeId) {
        await loadOne(activeId);
      }
    };
    void init();
  }, [loadCurrent, loadList, loadOne]);

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
    [isNewMode, loadOne]
  );

  const startNewPersonality = useCallback(() => {
    setIsNewMode(true);
    setSelectedId('__new__');
    setConfig(structuredClone(DEFAULT_PERSONALITY_CONFIG));
  }, []);

  const cancelNewPersonality = useCallback(() => {
    setIsNewMode(false);
    setSelectedId(currentId);
    void loadOne(currentId);
  }, [currentId, loadOne]);

  const selectedInfo = useMemo(
    () => list.find((item) => item.id === selectedId),
    [list, selectedId]
  );

  const save = useCallback(async () => {
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

    setSaving(true);
    try {
      if (isNewMode) {
        // Create via persona registry
        const configJson = JSON.stringify(config);
        const result = await personasApi.create({ config_json: configJson });
        const newId = result.data?.persona_id;
        toast.success(t('personality.createSuccess'));
        setIsNewMode(false);
        await loadList();
        if (newId) {
          setSelectedId(newId);
          await loadOne(newId);
        }
      } else {
        // Update existing persona in registry
        const configJson = JSON.stringify(config);
        await personasApi.update(selectedId, {
          name: config.name,
          config_json: configJson,
        });
        toast.success(t('personality.saveSuccess'));
        await loadList();
      }
    } catch (error) {
      handleError(error, 'Save personality');
    } finally {
      setSaving(false);
    }
  }, [config, selectedId, isNewMode, loadList, loadOne, t]);

  const generate = useCallback(async () => {
    if (!prompt.trim()) {
      toast.warning(t('personality.generatePromptRequired'));
      return;
    }

    setGenerating(true);
    setGenerationStages(buildPendingGenerationStages());
    try {
      const response = await personasApi.generateWithProgress({
        description: prompt,
        target_language: targetLanguage === 'Auto'
          ? getGenerationTargetLanguage(i18n.resolvedLanguage || i18n.language)
          : targetLanguage,
        current_config: config,
      }, (snapshot) => {
        setGenerationStages(snapshot.stages?.length ? snapshot.stages : buildPendingGenerationStages());
      });
      const data = (response.data || {}) as Partial<PersonalityConfig>;
      setConfig(mergeConfig(data));
      setPrompt('');
      toast.success(t('personality.generateSuccess'));
    } catch (error) {
      handleError(error, 'Generate personality');
    } finally {
      setGenerating(false);
    }
  }, [config, i18n.language, i18n.resolvedLanguage, prompt, t, targetLanguage]);

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
    try {
      await personasApi.setActive(switchPrompt.targetId);
      setCurrentId(switchPrompt.targetId);
      setSwitchPrompt(null);
      await loadOne(switchPrompt.targetId);
      toast.success(t('personality.switchSuccess', { name: switchPrompt.toName }));
    } catch (error) {
      handleError(error, 'Switch personality');
    } finally {
      setSwitching(false);
    }
  }, [loadOne, switchPrompt, t]);

  const cancelSwitchPersonality = useCallback(() => {
    setSwitchPrompt(null);
  }, []);

  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);

  const requestDeletePersonality = useCallback(() => {
    if (!selectedId || selectedId === currentId) return;
    setDeleteConfirmOpen(true);
  }, [selectedId, currentId]);

  const confirmDeletePersonality = useCallback(async () => {
    setDeleteConfirmOpen(false);
    if (!selectedId || selectedId === currentId) return;
    try {
      await personasApi.delete(selectedId);
      await loadList();
      const activeId = await loadCurrent();
      if (activeId) {
        await loadOne(activeId);
      }
    } catch (error) {
      handleError(error, 'Delete personality');
    }
  }, [selectedId, currentId, loadList, loadCurrent, loadOne]);

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
    generating,
    generationProgress,
    generationStageKey,
    switching,
    selectedInfo,
    switchPrompt,

    // Form state
    prompt,
    setPrompt,
    targetLanguage,
    setTargetLanguage,

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
