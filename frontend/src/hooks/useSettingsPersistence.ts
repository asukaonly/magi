import { type Dispatch, type SetStateAction, useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import { configApi, type SystemConfig } from '@/api/modules/config';
import { requireConfiguration } from '@/api/config-contract';
import { type ControlSettingsDTO, updateControlSettings } from '@/api/modules/control';
import { pluginsApi, type PluginPackageState } from '@/api/modules/plugins';
import { toolsApi, type ToolConfig } from '@/api/modules/tools';
import type { SensorSourceStatusItem } from '@/api/modules/sensors';
import { syncAutoStartPreference, syncCloseToTrayPreference, syncSkipQuitConfirmationPreference, syncStartMinimizedPreference } from '@/runtime/desktop';
import { syncDesktopNotificationPreferences } from '@/runtime/desktop-notifications';
import type { ThemeMode, ThemeState } from '@/stores/theme';
import type { PluginDraftMap, ToolDraftMap } from '@/types/settings';
import {
  diffFlatMaps,
  persistLanguageSelection,
  previewLanguageSelection,
  serialize,
} from '@/utils/settings-helpers';
import { validateLLMCustomProviderReadiness, type LLMValidationIssue } from '@/components/config-forms/llm-form-state';
import { validateMemoryL0Config, isEmbeddingIdleTimeoutValid } from '@/utils/memory-settings-validation';
import { isExtensionFieldVisible, validateDynamicConfigValue } from '@/components/config-forms/dynamic-config-specs';

interface UseSettingsPersistenceParams {
  savedConfig: SystemConfig;
  setSavedConfig: Dispatch<SetStateAction<SystemConfig>>;
  draftConfig: SystemConfig;
  setDraftConfig: Dispatch<SetStateAction<SystemConfig>>;
  savedControlSettings: ControlSettingsDTO | null;
  setSavedControlSettings: Dispatch<SetStateAction<ControlSettingsDTO | null>>;
  draftControlSettings: ControlSettingsDTO | null;
  setDraftControlSettings: Dispatch<SetStateAction<ControlSettingsDTO | null>>;
  savedPluginDrafts: PluginDraftMap;
  setSavedPluginDrafts: Dispatch<SetStateAction<PluginDraftMap>>;
  draftPluginDrafts: PluginDraftMap;
  setDraftPluginDrafts: Dispatch<SetStateAction<PluginDraftMap>>;
  savedToolDrafts: ToolDraftMap;
  setSavedToolDrafts: Dispatch<SetStateAction<ToolDraftMap>>;
  draftToolDrafts: ToolDraftMap;
  setDraftToolDrafts: Dispatch<SetStateAction<ToolDraftMap>>;
  savedThemeMode: ThemeMode;
  setSavedThemeMode: Dispatch<SetStateAction<ThemeMode>>;
  draftThemeMode: ThemeMode;
  setDraftThemeMode: Dispatch<SetStateAction<ThemeMode>>;
  tools: ToolConfig[];
  plugins: PluginPackageState[];
  timelineStatuses: SensorSourceStatusItem[];
  setThemeMode: ThemeState['setMode'];
  fetchTimelineStatuses: () => Promise<void>;
  loadPlugins: (options?: { silent?: boolean }) => Promise<void>;
  loadTools: (options?: { silent?: boolean }) => Promise<void>;
}

interface UseSettingsPersistenceReturn {
  saving: boolean;
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
  savedPluginDrafts,
  setSavedPluginDrafts,
  draftPluginDrafts,
  setDraftPluginDrafts,
  savedToolDrafts,
  setSavedToolDrafts,
  draftToolDrafts,
  setDraftToolDrafts,
  savedThemeMode,
  setSavedThemeMode,
  draftThemeMode,
  setDraftThemeMode,
  tools,
  plugins,
  timelineStatuses,
  setThemeMode,
  fetchTimelineStatuses,
  loadPlugins,
  loadTools,
}: UseSettingsPersistenceParams): UseSettingsPersistenceReturn {
  const { t } = useTranslation('app');
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
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
    for (const plugin of plugins) {
      const id = plugin.manifest.plugin_id;
      const saved = savedPluginDrafts[id] ?? {};
      const draft = draftPluginDrafts[id] ?? saved;
      const updates = diffFlatMaps(saved, draft);
      const fields = [
        ...plugin.contributions.flatMap(contribution => contribution.fields),
        ...timelineStatuses.filter(source => source.plugin_id === id).flatMap(source => source.fields),
      ];
      for (const field of fields) {
        if (!(field.key in updates) || !isExtensionFieldVisible(field, draft)) continue;
        const issue = validateDynamicConfigValue(field, updates[field.key]);
        if (issue) {
          toast.warning(t('settings.dynamicValidation.fieldInvalid', { field: field.label_translated || field.label, reason: t(`settings.dynamicValidation.${issue}`) }));
          return;
        }
      }
    }

    savingRef.current = true;
    setSaving(true);
    try {
      const configDirty = serialize(savedConfig) !== serialize(draftConfig);
      const languageChanged = savedConfig.preferences.language !== draftConfig.preferences.language;
      const controlDirty = serialize(savedControlSettings) !== serialize(draftControlSettings);
      const pluginsDirty = serialize(savedPluginDrafts) !== serialize(draftPluginDrafts);
      const toolsDirty = serialize(savedToolDrafts) !== serialize(draftToolDrafts);
      const themeDirty = savedThemeMode !== draftThemeMode;
      let persistedConfig = structuredClone(draftConfig);

      if (configDirty) {
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
        const response = await configApi.update(draftConfig);
        persistedConfig = structuredClone(requireConfiguration(response));
        await syncCloseToTrayPreference(persistedConfig.preferences.close_to_tray_enabled);
        await syncAutoStartPreference(persistedConfig.preferences.auto_start_enabled);
        await syncStartMinimizedPreference(persistedConfig.preferences.start_minimized);
        await syncSkipQuitConfirmationPreference(persistedConfig.preferences.skip_quit_confirmation);
        syncDesktopNotificationPreferences(persistedConfig.preferences);
        setSavedConfig(structuredClone(persistedConfig));
        setDraftConfig(structuredClone(persistedConfig));
      }

      if (controlDirty && draftControlSettings) {
        const persistedControlSettings = await updateControlSettings(draftControlSettings);
        setSavedControlSettings(structuredClone(persistedControlSettings));
        setDraftControlSettings(structuredClone(persistedControlSettings));
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
          setDraftToolDrafts(current => ({ ...current, [tool.name]: structuredClone(canonical) }));
        }
      }

      if (pluginsDirty) {
        for (const plugin of plugins) {
          const pluginId = plugin.manifest.plugin_id;
          const savedValues = savedPluginDrafts[pluginId] || {};
          const draftValues = draftPluginDrafts[pluginId] || {};
          const updates = diffFlatMaps(savedValues, draftValues);
          if (Object.keys(updates).length === 0) {
            continue;
          }
          const persistedPlugin = await pluginsApi.updateSettings(pluginId, updates);
          if (persistedPlugin.manifest.plugin_id !== pluginId) throw new Error('Plugin configuration identity mismatch');
          setSavedPluginDrafts(current => ({ ...current, [pluginId]: structuredClone(persistedPlugin.current_settings) }));
          setDraftPluginDrafts(current => ({ ...current, [pluginId]: structuredClone(persistedPlugin.current_settings) }));
        }
      }

      if (themeDirty) {
        setThemeMode(draftThemeMode, { persist: true });
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

      toast.success(t('settings.saveSuccess'));
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'unknown';
      toast.error(t('settings.saveFailed', { message }));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }, [
    t,
    savedConfig,
    setSavedConfig,
    draftConfig,
    setDraftConfig,
    savedControlSettings,
    setSavedControlSettings,
    draftControlSettings,
    setDraftControlSettings,
    savedPluginDrafts,
    setSavedPluginDrafts,
    setDraftPluginDrafts,
    draftPluginDrafts,
    savedToolDrafts,
    setSavedToolDrafts,
    setDraftToolDrafts,
    draftToolDrafts,
    savedThemeMode,
    setSavedThemeMode,
    draftThemeMode,
    tools,
    plugins,
    timelineStatuses,
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
    setDraftPluginDrafts(structuredClone(savedPluginDrafts));
    setDraftToolDrafts(structuredClone(savedToolDrafts));
    setDraftThemeMode(savedThemeMode);
    setThemeMode(savedThemeMode, { persist: true });
    await previewLanguageSelection(savedConfig.preferences.language);
  }, [
    savedConfig,
    setDraftConfig,
    savedControlSettings,
    setDraftControlSettings,
    savedPluginDrafts,
    setDraftPluginDrafts,
    savedToolDrafts,
    setDraftToolDrafts,
    savedThemeMode,
    setDraftThemeMode,
    setThemeMode,
  ]);

  return {
    saving,
    handleSaveChanges,
    handleDiscardChanges,
    embeddingPreflightPrompt,
    confirmEmbeddingPreflight,
    cancelEmbeddingPreflight,
  };
}

export type { UseSettingsPersistenceReturn };
