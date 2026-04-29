import { type Dispatch, type SetStateAction, useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import { configApi, type SystemConfig } from '@/api/modules/config';
import { type ControlSettingsDTO, updateControlSettings } from '@/api/modules/control';
import { pluginsApi, type PluginPackageState } from '@/api/modules/plugins';
import { toolsApi, type ToolConfig } from '@/api/modules/tools';
import { syncAutoStartPreference, syncCloseToTrayPreference, syncStartMinimizedPreference } from '@/runtime/desktop';
import type { ThemeMode, ThemeState } from '@/stores/theme';
import type { PluginDraftMap, ToolDraftMap } from '@/types/settings';
import {
  diffFlatMaps,
  persistLanguageSelection,
  previewLanguageSelection,
  serialize,
} from '@/utils/settings-helpers';

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
  setThemeMode: ThemeState['setMode'];
  fetchTimelineStatuses: () => Promise<void>;
  loadPlugins: (options?: { silent?: boolean }) => Promise<void>;
  loadTools: (options?: { silent?: boolean }) => Promise<void>;
}

interface UseSettingsPersistenceReturn {
  saving: boolean;
  handleSaveChanges: () => Promise<void>;
  handleDiscardChanges: () => Promise<void>;
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
  setThemeMode,
  fetchTimelineStatuses,
  loadPlugins,
  loadTools,
}: UseSettingsPersistenceParams): UseSettingsPersistenceReturn {
  const { t } = useTranslation('app');
  const [saving, setSaving] = useState(false);

  const handleSaveChanges = useCallback(async () => {
    setSaving(true);
    try {
      const configDirty = serialize(savedConfig) !== serialize(draftConfig);
      const controlDirty = serialize(savedControlSettings) !== serialize(draftControlSettings);
      const pluginsDirty = serialize(savedPluginDrafts) !== serialize(draftPluginDrafts);
      const toolsDirty = serialize(savedToolDrafts) !== serialize(draftToolDrafts);
      const themeDirty = savedThemeMode !== draftThemeMode;
      let persistedConfig = structuredClone(draftConfig);

      if (configDirty) {
        const response = await configApi.update(draftConfig);
        persistedConfig = structuredClone(response.data || draftConfig);
        await syncCloseToTrayPreference(persistedConfig.preferences.close_to_tray_enabled);
        await syncAutoStartPreference(persistedConfig.preferences.auto_start_enabled);
        await syncStartMinimizedPreference(persistedConfig.preferences.start_minimized);
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
          await toolsApi.updateToolConfig(tool.name, {
            updates,
            enabled: enabledChanged ? draftSnapshot.enabled : undefined,
          });
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
          await pluginsApi.updateSettings(pluginId, updates);
        }
      }

      if (themeDirty) {
        setThemeMode(draftThemeMode, { persist: true });
        setSavedThemeMode(draftThemeMode);
      }
      persistLanguageSelection(persistedConfig.preferences.language);

      await Promise.all([
        fetchTimelineStatuses(),
        loadPlugins({ silent: true }),
        loadTools({ silent: true }),
      ]);

      setSavedPluginDrafts(structuredClone(draftPluginDrafts));
      setSavedToolDrafts(structuredClone(draftToolDrafts));
      toast.success(t('settings.saveSuccess'));
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'unknown';
      toast.error(t('settings.saveFailed', { message }));
    } finally {
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
    draftPluginDrafts,
    savedToolDrafts,
    setSavedToolDrafts,
    draftToolDrafts,
    savedThemeMode,
    setSavedThemeMode,
    draftThemeMode,
    tools,
    plugins,
    setThemeMode,
    fetchTimelineStatuses,
    loadPlugins,
    loadTools,
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
  };
}

export type { UseSettingsPersistenceReturn };