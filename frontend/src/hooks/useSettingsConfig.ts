import { useCenterRefresh } from '@/hooks/useCenterRefresh';
import { type Dispatch, type SetStateAction, useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import { configApi, DEFAULT_SYSTEM_CONFIG, type LanguageCode, type SystemConfig } from '@/api/modules/config';
import { requireConfiguration } from '@/api/config-contract';
import { getErrorMessage } from '@/utils/error-handler';
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
  configError: string | null;
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
  fetchConfig: (options?: { silent?: boolean; discardDraft?: boolean }) => Promise<void>;
  loadControlSettings: (options?: { silent?: boolean; discardDraft?: boolean }) => Promise<void>;
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
  const [savedConfig, setSavedConfigState] = useState<SystemConfig>(DEFAULT_SYSTEM_CONFIG);
  const savedConfigRef = useRef(savedConfig);
  const setSavedConfig: Dispatch<SetStateAction<SystemConfig>> = useCallback((update) => {
    const next = typeof update === 'function' ? update(savedConfigRef.current) : update;
    savedConfigRef.current = next;
    setSavedConfigState(next);
  }, []);
  const [draftConfig, setDraftConfig] = useState<SystemConfig>(DEFAULT_SYSTEM_CONFIG);
  const [configError, setConfigError] = useState<string | null>(null);
  const [savedControlSettings, setSavedControlSettingsState] = useState<ControlSettingsDTO | null>(null);
  const savedControlRef = useRef(savedControlSettings);
  const setSavedControlSettings: Dispatch<SetStateAction<ControlSettingsDTO | null>> = useCallback((update) => {
    const next = typeof update === 'function' ? update(savedControlRef.current) : update;
    savedControlRef.current = next;
    setSavedControlSettingsState(next);
  }, []);
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
  }, [draftConfig.llm, savedConfig.llm, setSavedConfig]);

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

  const currentDrafts = useRef({ savedConfig, draftConfig, savedControlSettings, draftControlSettings });
  currentDrafts.current = { savedConfig, draftConfig, savedControlSettings, draftControlSettings };
  const configRequestId = useRef(0);
  const controlRequestId = useRef(0);
  useEffect(() => () => { configRequestId.current += 1; controlRequestId.current += 1; }, []);

  const fetchConfig = useCallback(async ({ silent = false, discardDraft = false }: { silent?: boolean; discardDraft?: boolean } = {}) => {
    const requestId = ++configRequestId.current;
    const savedAtStart = savedConfigRef.current;
    const draftAtStart = serialize(currentDrafts.current.draftConfig);
    if (!silent) { setLoading(true); setConfigError(null); }
    try {
      const response = await configApi.get();
      const nextConfig = requireConfiguration(response);
      if (requestId !== configRequestId.current) return;
      if (savedConfigRef.current !== savedAtStart) return;
      const current = currentDrafts.current;
      if (discardDraft && serialize(current.draftConfig) !== draftAtStart) return;
      if (silent && !discardDraft && serialize(current.savedConfig) !== serialize(current.draftConfig)) return;
      setSavedConfig(nextConfig);
      setDraftConfig(structuredClone(nextConfig));
      if (!silent) { setSavedThemeMode(themeMode); setDraftThemeMode(themeMode); }
    } catch (error: unknown) {
      if (requestId !== configRequestId.current) return;
      const message = getErrorMessage(error) || t('settings.errorUnknown');
      if (!silent) setConfigError(t('settings.loadFailed', { message }));
    } finally {
      if (requestId === configRequestId.current) setLoading(false);
    }
  }, [setDraftThemeMode, setSavedThemeMode, t, themeMode, setSavedConfig]);

  const loadControlSettings = useCallback(async ({ silent = false, discardDraft = false }: { silent?: boolean; discardDraft?: boolean } = {}) => {
    const requestId = ++controlRequestId.current;
    const savedAtStart = savedControlRef.current;
    const draftAtStart = serialize(currentDrafts.current.draftControlSettings);
    try {
      const nextSettings = await getControlSettings();
      if (requestId !== controlRequestId.current) return;
      if (savedControlRef.current !== savedAtStart) return;
      const current = currentDrafts.current;
      if (discardDraft && serialize(current.draftControlSettings) !== draftAtStart) return;
      if (silent && !discardDraft && serialize(current.savedControlSettings) !== serialize(current.draftControlSettings)) return;
      setSavedControlSettings(nextSettings);
      setDraftControlSettings(structuredClone(nextSettings));
    } catch (error: unknown) {
      if (requestId !== controlRequestId.current) return;
      const message = error instanceof Error ? error.message : 'unknown';
      if (!silent) toast.error(t('settings.loadFailed', { message }));
    }
  }, [t, setSavedControlSettings]);

  useCenterRefresh(async () => {
    await Promise.all([fetchConfig({ silent: true }), loadControlSettings({ silent: true })]);
  }, !loading);

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
    configError,
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
