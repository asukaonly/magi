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
  personalityApi,
  DEFAULT_PERSONALITY_CONFIG,
  type PersonalityConfig,
  type PersonalityDiff,
  type StateTransitionProtocolItem,
} from '@/api';
import { handleError } from '@/utils/error-handler';

// ============================================================================
// Types
// ============================================================================

export interface PersonalityInfo {
  name: string;
  displayName: string;
  subtitle?: string;
}

export interface UsePersonalityOptions {
  initialPersonalityName?: string;
}

export interface UsePersonalityReturn {
  // State
  config: PersonalityConfig;
  list: PersonalityInfo[];
  currentName: string;
  selectedName: string;
  isNewMode: boolean;
  loading: boolean;
  saving: boolean;
  generating: boolean;
  switching: boolean;
  diffs: PersonalityDiff[];
  selectedInfo: PersonalityInfo | undefined;
  diffPreview: PersonalityDiff[];

  // Form state
  prompt: string;
  setPrompt: (value: string) => void;
  targetLanguage: string;
  setTargetLanguage: (value: string) => void;

  // Actions
  patch: (fn: (draft: PersonalityConfig) => void) => void;
  selectPersonality: (name: string) => void;
  startNewPersonality: () => void;
  cancelNewPersonality: () => void;
  save: () => Promise<void>;
  generate: () => Promise<void>;
  switchPersonality: () => Promise<void>;
  deletePersonality: () => Promise<void>;
  reload: () => Promise<void>;
}

// ============================================================================
// Constants
// ============================================================================

const CONFIDENCE_OPTIONS = ['Extremely High', 'High', 'Medium', 'Low'] as const;

// ============================================================================
// Helper Functions
// ============================================================================

const normalizeTransition = (
  item: Partial<StateTransitionProtocolItem>
): StateTransitionProtocolItem => ({
  trigger_type: item.trigger_type || '',
  trigger_condition: item.trigger_condition || '',
  target_state_name: item.target_state_name || '',
  behavior_shift: item.behavior_shift || '',
});

const mergeConfig = (incoming: Partial<PersonalityConfig>): PersonalityConfig => {
  const next = structuredClone(DEFAULT_PERSONALITY_CONFIG);
  next.persona_entity.basic_profile = {
    ...next.persona_entity.basic_profile,
    ...(incoming.persona_entity?.basic_profile || {}),
  };
  next.persona_entity.psychological_traits = {
    ...next.persona_entity.psychological_traits,
    ...(incoming.persona_entity?.psychological_traits || {}),
  };
  next.persona_entity.social_responses = {
    ...next.persona_entity.social_responses,
    ...(incoming.persona_entity?.social_responses || {}),
  };
  next.persona_entity.behavioral_strategies = {
    ...next.persona_entity.behavioral_strategies,
    ...(incoming.persona_entity?.behavioral_strategies || {}),
  };
  next.cached_phrases = {
    ...next.cached_phrases,
    ...(incoming.cached_phrases || {}),
  };
  next.appearance_prompt = incoming.appearance_prompt || next.appearance_prompt;
  const transitions = incoming.state_transition_protocol || next.state_transition_protocol;
  next.state_transition_protocol =
    transitions.length > 0 ? transitions.map(normalizeTransition) : [normalizeTransition({})];
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
  const { initialPersonalityName } = options;
  const { t } = useTranslation('app');

  // Loading states
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [switching, setSwitching] = useState(false);

  // Personality state
  const [currentName, setCurrentName] = useState('default');
  const [selectedName, setSelectedName] = useState(initialPersonalityName || 'default');
  const [isNewMode, setIsNewMode] = useState(false);
  const [config, setConfig] = useState<PersonalityConfig>(DEFAULT_PERSONALITY_CONFIG);
  const [list, setList] = useState<PersonalityInfo[]>([
    { name: 'default', displayName: 'default', subtitle: 'System Default' },
  ]);

  // Form state
  const [prompt, setPrompt] = useState('');
  const [targetLanguage, setTargetLanguage] = useState('Auto');

  // Diff state
  const [diffs, setDiffs] = useState<PersonalityDiff[]>([]);

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
  // Data Loading
  // ============================================================================

  const loadList = useCallback(async () => {
    try {
      const result = await personalityApi.list();
      const data = result.data as { personalities?: string[] } | undefined;
      const names = data?.personalities || ['default'];
      const items: PersonalityInfo[] = [];

      for (const name of names) {
        try {
          const detail = await personalityApi.get(name);
          const configData = detail.data as PersonalityConfig | undefined;
          const profile = configData?.persona_entity?.basic_profile;

          items.push({
            name,
            displayName: profile?.name || name,
            subtitle: profile?.occupation,
          });
        } catch {
          items.push({ name, displayName: name });
        }
      }

      setList(
        items.length ? items : [{ name: 'default', displayName: 'default' }]
      );
    } catch {
      setList([{ name: 'default', displayName: 'default' }]);
    }
  }, []);

  const loadCurrent = useCallback(async (): Promise<string> => {
    try {
      const result = await personalityApi.getCurrent();
      const data = result.data as { current?: string } | undefined;
      const current = data?.current || 'default';
      setCurrentName(current);
      setSelectedName(current);
      return current;
    } catch {
      setCurrentName('default');
      setSelectedName('default');
      return 'default';
    }
  }, []);

  const loadOne = useCallback(
    async (name: string) => {
      setLoading(true);
      try {
        const result = await personalityApi.get(name);
        const data = (result.data || {}) as Partial<PersonalityConfig>;
        setConfig(mergeConfig(data));
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
      const current = await loadCurrent();
      await loadList();
      await loadOne(current);
    };
    void init();
  }, [loadCurrent, loadList, loadOne]);

  // ============================================================================
  // Actions
  // ============================================================================

  const selectPersonality = useCallback(
    (name: string) => {
      if (isNewMode) {
        setIsNewMode(false);
      }
      setSelectedName(name);
      setDiffs([]);
      void loadOne(name);
    },
    [isNewMode, loadOne]
  );

  const startNewPersonality = useCallback(() => {
    setIsNewMode(true);
    setSelectedName('__new__');
    setDiffs([]);
    setConfig(structuredClone(DEFAULT_PERSONALITY_CONFIG));
  }, []);

  const cancelNewPersonality = useCallback(() => {
    setIsNewMode(false);
    setSelectedName(currentName);
    void loadOne(currentName);
  }, [currentName, loadOne]);

  const save = useCallback(async () => {
    // Validate name in create mode
    if (isNewMode) {
      const name = config.persona_entity.basic_profile.name?.trim();
      if (!name) {
        toast.warning(t('personality.nameRequired'));
        return;
      }
    }

    setSaving(true);
    try {
      if (isNewMode) {
        // Create mode: create new personality
        await personalityApi.updateWithAIName(config);
        toast.success(t('personality.createSuccess'));
        setIsNewMode(false);
        await loadList();
        await loadCurrent();
        // Select the newly created personality
        const newName = config.persona_entity.basic_profile.name;
        setSelectedName(newName);
        void loadOne(newName);
      } else if (
        currentName === 'default' ||
        currentName !== config.persona_entity.basic_profile.name
      ) {
        await personalityApi.updateWithAIName(config);
        toast.success(t('personality.saveSuccess'));
        await loadList();
        await loadCurrent();
      } else {
        await personalityApi.update(currentName, config);
        toast.success(t('personality.saveSuccess'));
        await loadList();
        await loadCurrent();
      }
    } catch (error) {
      handleError(error, 'Save personality');
    } finally {
      setSaving(false);
    }
  }, [config, currentName, isNewMode, loadCurrent, loadList, loadOne, t]);

  const generate = useCallback(async () => {
    if (!prompt.trim()) {
      toast.warning(t('personality.generatePromptRequired'));
      return;
    }

    setGenerating(true);
    try {
      const response = await personalityApi.generate({
        description: prompt,
        target_language: targetLanguage,
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
  }, [prompt, targetLanguage, t]);

  const switchPersonality = useCallback(async () => {
    if (selectedName === currentName) return;

    setSwitching(true);
    try {
      const response = await personalityApi.compare(currentName, selectedName);
      const data = response.data as { diffs?: PersonalityDiff[] } | undefined;
      const nextDiffs = data?.diffs || [];
      setDiffs(nextDiffs);

      const ok = window.confirm(
        t('personality.switchConfirm', { from: currentName, to: selectedName })
      );
      if (!ok) return;

      await personalityApi.setCurrent(selectedName);
      setCurrentName(selectedName);
      await loadOne(selectedName);
      toast.success(t('personality.switchSuccess', { name: selectedName }));
    } catch (error) {
      handleError(error, 'Switch personality');
    } finally {
      setSwitching(false);
    }
  }, [currentName, selectedName, loadOne, t]);

  const deletePersonality = useCallback(async () => {
    if (selectedName === 'default') return;
    if (!window.confirm(t('personality.deleteConfirm', { name: selectedName }))) return;

    try {
      await personalityApi.delete(selectedName);
      setDiffs([]);
      await loadList();
      const current = await loadCurrent();
      await loadOne(current);
    } catch (error) {
      handleError(error, 'Delete personality');
    }
  }, [selectedName, loadList, loadCurrent, loadOne, t]);

  const reload = useCallback(async () => {
    setDiffs([]);
    await loadOne(selectedName);
  }, [loadOne, selectedName]);

  // ============================================================================
  // Computed Values
  // ============================================================================

  const selectedInfo = useMemo(
    () => list.find((item) => item.name === selectedName),
    [list, selectedName]
  );

  const diffPreview = useMemo(() => diffs.slice(0, 8), [diffs]);

  // ============================================================================
  // Return
  // ============================================================================

  return {
    // State
    config,
    list,
    currentName,
    selectedName,
    isNewMode,
    loading,
    saving,
    generating,
    switching,
    diffs,
    selectedInfo,
    diffPreview,

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
    deletePersonality,
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
  normalizeTransition,
  mergeConfig,
};
