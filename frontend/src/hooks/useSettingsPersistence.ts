import { getErrorMessage } from '@/utils/error-handler';
import { writeDevicePreferences } from '@/runtime/device-preferences';
import { type Dispatch, type SetStateAction, useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import { configApi, toCenterConfig, type SystemConfig } from '@/api/modules/config';
import { requireConfiguration } from '@/api/config-contract';
import { type ControlSettingsDTO, updateControlSettings } from '@/api/modules/control';
import { toolsApi, type ToolConfig } from '@/api/modules/tools';
import { syncAutoStartPreference, syncCloseToTrayPreference, syncSkipQuitConfirmationPreference, syncStartMinimizedPreference } from '@/runtime/desktop';
import { syncDesktopNotificationPreferences } from '@/runtime/desktop-notifications';
import type { ThemeMode, ThemeState } from '@/stores/theme';
import { useDesktopPreferencesStore } from '@/stores/desktop-preferences';
import type { ToolDraftMap } from '@/types/settings';
import {
  acceptSavedDraft,
  diffFlatMaps,
  persistLanguageSelection,
  previewLanguageSelection,
  serialize,
} from '@/utils/settings-helpers';
import { validateLLMCustomProviderReadiness, type LLMValidationIssue } from '@/components/config-forms/llm-form-state';
import { validateMemoryL0Config, isEmbeddingIdleTimeoutValid } from '@/utils/memory-settings-validation';
import { validateDynamicConfigValue } from '@/components/config-forms/dynamic-config-specs';

interface UseSettingsPersistenceParams {
  savedConfig: SystemConfig;
  setSavedConfig: Dispatch<SetStateAction<SystemConfig>>;
  draftConfig: SystemConfig;
  setDraftConfig: Dispatch<SetStateAction<SystemConfig>>;
  savedControlSettings: ControlSettingsDTO | null;
  setSavedControlSettings: Dispatch<SetStateAction<ControlSettingsDTO | null>>;
  draftControlSettings: ControlSettingsDTO | null;
  setDraftControlSettings: Dispatch<SetStateAction<ControlSettingsDTO | null>>;
  savedToolDrafts: ToolDraftMap;
  setSavedToolDrafts: Dispatch<SetStateAction<ToolDraftMap>>;
  draftToolDrafts: ToolDraftMap;
  setDraftToolDrafts: Dispatch<SetStateAction<ToolDraftMap>>;
  savedThemeMode: ThemeMode;
  setSavedThemeMode: Dispatch<SetStateAction<ThemeMode>>;
  draftThemeMode: ThemeMode;
  setDraftThemeMode: Dispatch<SetStateAction<ThemeMode>>;
  tools: ToolConfig[];
  setThemeMode: ThemeState['setMode'];
  fetchTimelineStatuses: () => Promise<void>;
  loadPlugins: (options?: { silent?: boolean }) => Promise<void>;
  loadTools: (options?: { silent?: boolean }) => Promise<void>;
}

interface UseSettingsPersistenceReturn {
  saving: boolean;
  configConflict: 'config' | 'control' | null;
  handleSaveChanges: () => Promise<void>;
  handleDiscardChanges: () => Promise<void>;
  embeddingPreflightPrompt: EmbeddingPreflightPrompt | null;
  confirmEmbeddingPreflight: () => void;
  cancelEmbeddingPreflight: () => void;
}

export interface EmbeddingPreflightPrompt {
  readyTotal: number;
  layers: string;
}

export function useSettingsPersistence({
  savedConfig,
  setSavedConfig,
  draftConfig,
  setDraftConfig,
  savedControlSettings,
  setSavedControlSettings,
  draftControlSettings,
  setDraftControlSettings,
  savedToolDrafts,
  setSavedToolDrafts,
  draftToolDrafts,
  setDraftToolDrafts,
  savedThemeMode,
  setSavedThemeMode,
  draftThemeMode,
  setDraftThemeMode,
  tools,
  setThemeMode,
  fetchTimelineStatuses,
  loadPlugins,
  loadTools,
}: UseSettingsPersistenceParams): UseSettingsPersistenceReturn {
  const { t } = useTranslation('app');
  const autoStartSyncFailed = useDesktopPreferencesStore(state => state.autoStartSyncFailed);
  const [saving, setSaving] = useState(false);
  const [configConflict, setConfigConflict] = useState<'config' | 'control' | null>(null);
  useEffect(() => { setConfigConflict(current => current === 'config' ? null : current); }, [savedConfig.revision]);
  useEffect(() => { setConfigConflict(current => current === 'control' ? null : current); }, [savedControlSettings?.revision]);
  const savingRef = useRef(false);
  const currentThemeRef = useRef(draftThemeMode);
  currentThemeRef.current = draftThemeMode;
  const [embeddingPreflightPrompt, setEmbeddingPreflightPrompt] = useState<EmbeddingPreflightPrompt | null>(null);
  const embeddingPreflightResolverRef = useRef<((confirmed: boolean) => void) | null>(null);

  useEffect(() => () => {
    embeddingPreflightResolverRef.current?.(false);
    embeddingPreflightResolverRef.current = null;
  }, []);

  const requestEmbeddingPreflightConfirmation = useCallback((prompt: EmbeddingPreflightPrompt) => {
    return new Promise<boolean>((resolve) => {
      embeddingPreflightResolverRef.current = resolve;
      setEmbeddingPreflightPrompt(prompt);
    });
  }, []);

  const resolveEmbeddingPreflightConfirmation = useCallback((confirmed: boolean) => {
    embeddingPreflightResolverRef.current?.(confirmed);
    embeddingPreflightResolverRef.current = null;
    setEmbeddingPreflightPrompt(null);
  }, []);

  const confirmEmbeddingPreflight = useCallback(() => {
    resolveEmbeddingPreflightConfirmation(true);
  }, [resolveEmbeddingPreflightConfirmation]);

  const cancelEmbeddingPreflight = useCallback(() => {
    resolveEmbeddingPreflightConfirmation(false);
  }, [resolveEmbeddingPreflightConfirmation]);

  const formatLlmValidationIssue = useCallback((issue: LLMValidationIssue): string => {
    const serviceLabel = t(`settings.llmValidation.services.${issue.serviceName}`);
    if (issue.code === 'customScenarioModelMissing' && issue.scenario && issue.model) {
      return t('settings.llmValidation.customScenarioModelMissing', {
        provider: issue.providerName,
        scenario: t(`settings.llmValidation.scenarios.${issue.scenario}`),
        model: issue.model,
        service: serviceLabel,
      });
    }
    return t('settings.llmValidation.customServiceModelRequired', {
      provider: issue.providerName,
      service: serviceLabel,
    });
  }, [t]);

  const handleSaveChanges = useCallback(async () => {
    if (savingRef.current) return;
    const llmValidationIssue = validateLLMCustomProviderReadiness(draftConfig.llm)[0];
    if (llmValidationIssue) {
      toast.warning(formatLlmValidationIssue(llmValidationIssue));
      return;
    }
    if (!isEmbeddingIdleTimeoutValid(draftConfig.memory.embedding.local.idle_timeout_seconds)) {
      toast.warning(t('settings.memory.validation.embeddingIdleTimeout'));
      return;
    }
    const memoryL0ValidationIssue = validateMemoryL0Config(draftConfig.memory.l0);
    if (memoryL0ValidationIssue) {
      toast.warning(t(`settings.memory.validation.${memoryL0ValidationIssue}`));
      return;
    }

    // Validate all changed dynamic fields before performing any persistence.
    for (const tool of tools) {
      const saved = savedToolDrafts[tool.name]?.values ?? tool.current_values;
      const draft = draftToolDrafts[tool.name]?.values ?? saved;
      const updates = diffFlatMaps(saved, draft);
      for (const spec of tool.config_specs) {
        const paths = spec.is_template
          ? tool.providers.map(provider => spec.path.replace('{provider}', provider.name))
          : [spec.path];
        for (const path of paths) {
          if (!(path in updates)) continue;
          const issue = validateDynamicConfigValue(spec, updates[path]);
          if (issue) {
            toast.warning(t('settings.dynamicValidation.fieldInvalid', { field: spec.description, reason: t(`settings.dynamicValidation.${issue}`) }));
            return;
          }
        }
      }
    }

    savingRef.current = true;
    setSaving(true);
    let configWritePending: 'config' | 'control' | null = null;
    try {
      const configDirty = serialize(savedConfig) !== serialize(draftConfig);
      const centerConfigDirty = serialize(toCenterConfig(savedConfig)) !== serialize(toCenterConfig(draftConfig));
      const languageChanged = savedConfig.preferences.language !== draftConfig.preferences.language;
      const controlDirty = serialize(savedControlSettings) !== serialize(draftControlSettings);
      const toolsDirty = serialize(savedToolDrafts) !== serialize(draftToolDrafts);
      const themeDirty = savedThemeMode !== draftThemeMode;
      let autoStartApplied = true;
      let persistedConfig = structuredClone(draftConfig);

      if (centerConfigDirty) {
        const preflight = await configApi.embeddingPreflight(draftConfig);
        const warningLayers = preflight.warnings.map((warning) =>
          t(`settings.memory.vector.layers.${warning.layer}`)
        );
        const uniqueWarningLayers = Array.from(new Set(warningLayers)).join(', ');
        if (preflight.severity === 'strong') {
          const confirmed = await requestEmbeddingPreflightConfirmation({
            readyTotal: preflight.ready_total,
            layers: uniqueWarningLayers,
          });
          if (!confirmed) {
            return;
          }
        } else if (preflight.severity === 'soft') {
          toast.warning(t('settings.memory.vector.preflightSoftWarning', {
            count: preflight.ready_total,
            layers: uniqueWarningLayers,
          }));
        }
        configWritePending = 'config';
        const response = await configApi.update({ ...draftConfig, revision: savedConfig.revision });
        persistedConfig = structuredClone(requireConfiguration(response));
        configWritePending = null;
      }

      if (configDirty) {
        writeDevicePreferences(draftConfig.preferences);
        persistedConfig.preferences.language = draftConfig.preferences.language;
        // The response contains current device values; apply the submitted snapshot.
        for (const key of [
          'close_to_tray_enabled', 'desktop_notifications_enabled',
          'desktop_notification_previews_enabled', 'auto_start_enabled',
          'start_minimized', 'skip_quit_confirmation',
        ] as const) persistedConfig.preferences[key] = draftConfig.preferences[key];
        setSavedConfig(structuredClone(persistedConfig));
        setDraftConfig(current => ({ ...acceptSavedDraft(current, draftConfig, persistedConfig), revision: persistedConfig.revision }));
        await syncCloseToTrayPreference(persistedConfig.preferences.close_to_tray_enabled);
        await syncStartMinimizedPreference(persistedConfig.preferences.start_minimized);
        await syncSkipQuitConfirmationPreference(persistedConfig.preferences.skip_quit_confirmation);
        syncDesktopNotificationPreferences(persistedConfig.preferences);
      }

      if (configDirty || autoStartSyncFailed) {
        try {
          await syncAutoStartPreference(persistedConfig.preferences.auto_start_enabled);
        } catch {
          autoStartApplied = false;
          toast.error(t('settings.autoStartSyncFailed'));
        }
      }

      if (controlDirty && draftControlSettings) {
        configWritePending = 'control';
        const persistedControlSettings = await updateControlSettings({ ...draftControlSettings, revision: savedControlSettings?.revision ?? '' });
        configWritePending = null;
        setSavedControlSettings(structuredClone(persistedControlSettings));
        setDraftControlSettings(current => current ? ({ ...acceptSavedDraft(current, draftControlSettings, persistedControlSettings), revision: persistedControlSettings.revision }) : current);
      }

      if (toolsDirty) {
        for (const tool of tools) {
          const savedSnapshot = savedToolDrafts[tool.name] ?? { enabled: tool.enabled, values: tool.current_values };
          const draftSnapshot = draftToolDrafts[tool.name] ?? savedSnapshot;
          const updates = diffFlatMaps(savedSnapshot.values || {}, draftSnapshot.values || {});
          const enabledChanged = savedSnapshot.enabled !== draftSnapshot.enabled;
          if (Object.keys(updates).length === 0 && !enabledChanged) {
            continue;
          }
          const persistedTool = await toolsApi.updateToolConfig(tool.name, {
            updates,
            enabled: enabledChanged ? draftSnapshot.enabled : undefined,
          });
          const canonical = { enabled: persistedTool.enabled, values: persistedTool.current_values };
          setSavedToolDrafts(current => ({ ...current, [tool.name]: structuredClone(canonical) }));
          setDraftToolDrafts(current => ({
            ...current,
            [tool.name]: acceptSavedDraft(current[tool.name] ?? draftSnapshot, draftSnapshot, canonical),
          }));
        }
      }

      if (themeDirty) {
        setThemeMode(draftThemeMode, { persist: true });
        if (currentThemeRef.current !== draftThemeMode) {
          setThemeMode(currentThemeRef.current, { persist: false });
        }
        setSavedThemeMode(draftThemeMode);
      }
      if (languageChanged) {
        persistLanguageSelection(persistedConfig.preferences.language);
        await previewLanguageSelection(persistedConfig.preferences.language);
      }

      await Promise.all([
        fetchTimelineStatuses(),
        loadPlugins({ silent: true }),
        loadTools({ silent: true }),
      ]);

      if (autoStartApplied) toast.success(t('settings.saveSuccess'));
    } catch (error: unknown) {
      const conflict = configWritePending && typeof error === 'object' && error !== null
        && 'status' in error && (error.status === 409 || error.status === 428);
      if (conflict && configWritePending) setConfigConflict(configWritePending);
      const message = conflict ? t('settings.centerConflict') : getErrorMessage(error) || 'unknown';
      toast.error(t('settings.saveFailed', { message }));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }, [
    autoStartSyncFailed,
    t,
    savedConfig,
    setSavedConfig,
    draftConfig,
    setDraftConfig,
    savedControlSettings,
    setSavedControlSettings,
    draftControlSettings,
    setDraftControlSettings,
    savedToolDrafts,
    setSavedToolDrafts,
    setDraftToolDrafts,
    draftToolDrafts,
    savedThemeMode,
    setSavedThemeMode,
    draftThemeMode,
    tools,
    setThemeMode,
    fetchTimelineStatuses,
    loadPlugins,
    loadTools,
    requestEmbeddingPreflightConfirmation,
    formatLlmValidationIssue,
  ]);

  const handleDiscardChanges = useCallback(async () => {
    setDraftConfig(structuredClone(savedConfig));
    setDraftControlSettings(savedControlSettings ? structuredClone(savedControlSettings) : null);
    setDraftToolDrafts(structuredClone(savedToolDrafts));
    setDraftThemeMode(savedThemeMode);
    setThemeMode(savedThemeMode, { persist: true });
    await previewLanguageSelection(savedConfig.preferences.language);
  }, [
    savedConfig,
    setDraftConfig,
    savedControlSettings,
    setDraftControlSettings,
    savedToolDrafts,
    setDraftToolDrafts,
    savedThemeMode,
    setDraftThemeMode,
    setThemeMode,
  ]);

  return {
    saving,
    configConflict,
    handleSaveChanges,
    handleDiscardChanges,
    embeddingPreflightPrompt,
    confirmEmbeddingPreflight,
    cancelEmbeddingPreflight,
  };
}

export type { UseSettingsPersistenceReturn };
