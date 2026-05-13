import { type Dispatch, type SetStateAction, useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import { configApi, DEFAULT_SYSTEM_CONFIG, type LanguageCode, type SystemConfig } from '@/api/modules/config';
import { type ControlSettingsDTO, getControlSettings } from '@/api/modules/control';
import type { ThemeMode } from '@/stores/theme';
import type { MemoryToggleFieldId } from '@/types/settings';
import {
  applyMemoryToggle,
  serialize,
} from '@/utils/settings-helpers';

interface UseSettingsConfigOptions {
  themeMode: ThemeMode;
  setSavedThemeMode: Dispatch<SetStateAction<ThemeMode>>;
  setDraftThemeMode: Dispatch<SetStateAction<ThemeMode>>;
}

interface UseSettingsConfigReturn {
  loading: boolean;
  savedConfig: SystemConfig;
  setSavedConfig: Dispatch<SetStateAction<SystemConfig>>;
  draftConfig: SystemConfig;
  setDraftConfig: Dispatch<SetStateAction<SystemConfig>>;
  savedControlSettings: ControlSettingsDTO | null;
  setSavedControlSettings: Dispatch<SetStateAction<ControlSettingsDTO | null>>;
  draftControlSettings: ControlSettingsDTO | null;
  setDraftControlSettings: Dispatch<SetStateAction<ControlSettingsDTO | null>>;
  patchDraftConfig: (updater: (draft: SystemConfig) => void) => void;
  syncNormalizedLlmConfig: (nextLlmConfig: SystemConfig['llm']) => void;
  patchDraftControlSettings: (updater: (draft: ControlSettingsDTO) => void) => void;
  fetchConfig: () => Promise<void>;
  loadControlSettings: () => Promise<void>;
  handleLanguageDraftChange: (value: string) => void;
  updateMemoryToggle: (field: MemoryToggleFieldId, checked: boolean) => void;
}

export function useSettingsConfig({
  themeMode,
  setSavedThemeMode,
  setDraftThemeMode,
}: UseSettingsConfigOptions): UseSettingsConfigReturn {
  const { t } = useTranslation('app');
  const [loading, setLoading] = useState(true);
  const [savedConfig, setSavedConfig] = useState<SystemConfig>(DEFAULT_SYSTEM_CONFIG);
  const [draftConfig, setDraftConfig] = useState<SystemConfig>(DEFAULT_SYSTEM_CONFIG);
  const [savedControlSettings, setSavedControlSettings] = useState<ControlSettingsDTO | null>(null);
  const [draftControlSettings, setDraftControlSettings] = useState<ControlSettingsDTO | null>(null);

  const patchDraftConfig = useCallback((updater: (draft: SystemConfig) => void) => {
    setDraftConfig((prev) => {
      const next = structuredClone(prev);
      updater(next);
      return next;
    });
  }, []);

  const syncNormalizedLlmConfig = useCallback((nextLlmConfig: SystemConfig['llm']) => {
    const nextSnapshot = structuredClone(nextLlmConfig);
    const draftWasPristine = serialize(savedConfig.llm) === serialize(draftConfig.llm);

    if (draftWasPristine) {
      setSavedConfig((prev) => {
        const next = structuredClone(prev);
        next.llm = structuredClone(nextSnapshot);
        return next;
      });
    }

    setDraftConfig((prev) => {
      const next = structuredClone(prev);
      next.llm = structuredClone(nextSnapshot);
      return next;
    });
  }, [draftConfig.llm, savedConfig.llm]);

  const patchDraftControlSettings = useCallback((updater: (draft: ControlSettingsDTO) => void) => {
    setDraftControlSettings((prev) => {
      if (!prev) {
        return prev;
      }
      const next = structuredClone(prev);
      updater(next);
      return next;
    });
  }, []);

  const fetchConfig = useCallback(async () => {
    setLoading(true);
    try {
      const response = await configApi.get();
      const nextConfig = response.data || DEFAULT_SYSTEM_CONFIG;
      setSavedConfig(nextConfig);
      setDraftConfig(structuredClone(nextConfig));
      setSavedThemeMode(themeMode);
      setDraftThemeMode(themeMode);
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'unknown';
      toast.error(t('settings.loadFailed', { message }));
    } finally {
      setLoading(false);
    }
  }, [setDraftThemeMode, setSavedThemeMode, t, themeMode]);

  const loadControlSettings = useCallback(async () => {
    try {
      const nextSettings = await getControlSettings();
      setSavedControlSettings(nextSettings);
      setDraftControlSettings(structuredClone(nextSettings));
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'unknown';
      toast.error(t('settings.loadFailed', { message }));
    }
  }, [t]);

  const handleLanguageDraftChange = useCallback((value: string) => {
    const nextLanguage = value as LanguageCode;
    patchDraftConfig((draft) => {
      draft.preferences.language = nextLanguage;
    });
  }, [patchDraftConfig]);

  const updateMemoryToggle = useCallback((field: MemoryToggleFieldId, checked: boolean) => {
    patchDraftConfig((draft) => {
      applyMemoryToggle(draft.memory, field, checked);
    });
  }, [patchDraftConfig]);

  return {
    loading,
    savedConfig,
    setSavedConfig,
    draftConfig,
    setDraftConfig,
    savedControlSettings,
    setSavedControlSettings,
    draftControlSettings,
    setDraftControlSettings,
    patchDraftConfig,
    syncNormalizedLlmConfig,
    patchDraftControlSettings,
    fetchConfig,
    loadControlSettings,
    handleLanguageDraftChange,
    updateMemoryToggle,
  };
}

export type { UseSettingsConfigReturn };
