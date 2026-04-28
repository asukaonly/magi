/**
 * Settings page state management hook.
 *
 * Manages all configuration, plugins, tools, and timeline state with
 * a saved/draft pattern for dirty tracking and save/discard operations.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';

import { configApi, type SystemConfig } from '@/api/modules/config';
import { type ControlSettingsDTO, updateControlSettings } from '@/api/modules/control';
import { pluginsApi, type PluginPackageState } from '@/api/modules/plugins';
import { toolsApi, type ToolConfig } from '@/api/modules/tools';
import { type SensorSourceStatusItem } from '@/api/modules/sensors';
import { useThemeStore, type ThemeMode } from '@/stores/theme';
import { syncCloseToTrayPreference, syncAutoStartPreference, syncStartMinimizedPreference } from '@/runtime/desktop';
import type {
  MemoryToggleFieldId,
  PluginDraftMap,
  SettingsPageHandle,
  ToolDraftMap,
} from '@/types/settings';
import {
  diffFlatMaps,
  persistLanguageSelection,
  previewLanguageSelection,
  serialize,
} from '@/utils/settings-helpers';
import { useSettingsConfig } from './useSettingsConfig';
import { useSettingsNavigation } from './useSettingsNavigation';
import { useSettingsPluginsTimeline } from './useSettingsPluginsTimeline';
import { useSettingsTools } from './useSettingsTools';

// ============================================================================
// Hook Return Type
// ============================================================================

export interface UseSettingsReturn {
  // Loading states
  loading: boolean;
  saving: boolean;

  // Navigation
  activeSection: string;
  setActiveSection: (section: string) => void;
  expandedGroups: Record<string, boolean>;
  getGroupExpanded: (groupId: string) => boolean;
  setGroupExpanded: (groupId: string, expanded: boolean) => void;
  handleNavItemClick: (itemId: string, isGroup: boolean, firstChildId?: string) => void;

  // Section helpers
  usesInnerPaneScroll: boolean;

  // Config state (saved/draft)
  draftConfig: SystemConfig;
  patchDraftConfig: (updater: (draft: SystemConfig) => void) => void;
  syncNormalizedLlmConfig: (nextLlmConfig: SystemConfig['llm']) => void;
  draftControlSettings: ControlSettingsDTO | null;
  patchDraftControlSettings: (updater: (draft: ControlSettingsDTO) => void) => void;

  // Theme state (saved/draft)
  draftThemeMode: ThemeMode;
  handleThemePreviewChange: (mode: ThemeMode) => void;

  // Language
  handleLanguagePreviewChange: (value: string) => void;

  updateMemoryToggle: (field: MemoryToggleFieldId, checked: boolean) => void;

  // Plugins
  plugins: PluginPackageState[];
  pluginsLoading: boolean;
  pluginProcessingIds: Record<string, string>;
  reloadingActionPlugins: Record<string, boolean>;
  draftPluginDrafts: PluginDraftMap;
  handlePluginDraftChange: (pluginId: string, key: string, value: unknown) => void;
  handlePluginDraftChanges: (pluginId: string, updates: Record<string, unknown>) => void;
  handlePluginAction: (pluginId: string, action: 'enable' | 'disable' | 'reload') => Promise<void>;
  handleReloadActionPlugin: (pluginId: string) => Promise<void>;
  loadPlugins: (options?: { silent?: boolean }) => Promise<void>;
  loadPluginsAndSensors: () => Promise<void>;

  // Tools
  tools: ToolConfig[];
  toolsLoading: boolean;
  toolsError: string | null;
  draftToolDrafts: ToolDraftMap;
  handleToolDraftChange: (toolName: string, path: string, value: unknown) => void;
  handleToolEnabledChange: (toolName: string, enabled: boolean) => void;

  // Timeline
  timelineStatuses: SensorSourceStatusItem[];
  timelineStatusesLoading: boolean;
  timelineSelection: string | null;
  setTimelineSelection: React.Dispatch<React.SetStateAction<string | null>>;
  fetchTimelineStatuses: () => Promise<void>;

  // Contribution sub-nav selections
  channelsSelection: string | null;
  setChannelsSelection: React.Dispatch<React.SetStateAction<string | null>>;

  // Dirty tracking
  dirty: boolean;

  // Actions
  handleSaveChanges: () => Promise<void>;
  handleDiscardChanges: () => Promise<void>;

  // Ref handle getter
  getHandle: () => SettingsPageHandle;
}

// ============================================================================
// Hook Implementation
// ============================================================================

export function useSettings(): UseSettingsReturn {
  const { t } = useTranslation('app');
  const themeMode = useThemeStore((state) => state.mode);
  const setThemeMode = useThemeStore((state) => state.setMode);

  // ========================================
  // State Declarations
  // ========================================

  // Theme state (saved/draft)
  const [savedThemeMode, setSavedThemeMode] = useState<ThemeMode>(themeMode);
  const [draftThemeMode, setDraftThemeMode] = useState<ThemeMode>(themeMode);

  // Loading states
  const [saving, setSaving] = useState(false);

  const {
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
    handleLanguagePreviewChange,
    updateMemoryToggle,
  } = useSettingsConfig({
    themeMode,
    setSavedThemeMode,
    setDraftThemeMode,
  });

  const {
    activeSection,
    setActiveSection,
    expandedGroups,
    getGroupExpanded,
    setGroupExpanded,
    handleNavItemClick,
    usesInnerPaneScroll,
    timelineSelection,
    setTimelineSelection,
    channelsSelection,
    setChannelsSelection,
  } = useSettingsNavigation();
  const {
    plugins,
    pluginsLoading,
    pluginProcessingIds,
    reloadingActionPlugins,
    savedPluginDrafts,
    setSavedPluginDrafts,
    draftPluginDrafts,
    setDraftPluginDrafts,
    handlePluginDraftChange,
    handlePluginDraftChanges,
    handlePluginAction,
    handleReloadActionPlugin,
    loadPlugins,
    loadPluginsAndSensors,
    timelineStatuses,
    timelineStatusesLoading,
    fetchTimelineStatuses,
  } = useSettingsPluginsTimeline();
  const {
    tools,
    toolsLoading,
    toolsError,
    savedToolDrafts,
    setSavedToolDrafts,
    draftToolDrafts,
    setDraftToolDrafts,
    loadTools,
    handleToolDraftChange,
    handleToolEnabledChange,
  } = useSettingsTools();

  // ========================================
  // Effects
  // ========================================

  // Initial data load
  useEffect(() => {
    void Promise.all([
      fetchConfig(),
      loadControlSettings(),
      fetchTimelineStatuses(),
      loadPlugins(),
      loadTools(),
    ]);
  }, [fetchConfig, loadControlSettings, fetchTimelineStatuses, loadPlugins, loadTools]);

  // Reset timeline selection when statuses change
  useEffect(() => {
    if (timelineSelection && !timelineStatuses.some((source) => source.source_name === timelineSelection)) {
      setTimelineSelection(null);
    }
  }, [timelineSelection, timelineStatuses]);

  // Timeline polling when section is active
  useEffect(() => {
    if (activeSection !== 'timeline') {
      return;
    }
    const timer = window.setInterval(() => {
      void fetchTimelineStatuses();
    }, 4000);
    return () => window.clearInterval(timer);
  }, [activeSection, fetchTimelineStatuses]);

  // ========================================
  // Dirty Tracking
  // ========================================

  const dirty = useMemo(() => {
    const configDirty = serialize(savedConfig) !== serialize(draftConfig);
    const controlDirty = serialize(savedControlSettings) !== serialize(draftControlSettings);
    const pluginsDirty = serialize(savedPluginDrafts) !== serialize(draftPluginDrafts);
    const toolsDirty = serialize(savedToolDrafts) !== serialize(draftToolDrafts);
    const themeDirty = savedThemeMode !== draftThemeMode;
    return configDirty || controlDirty || pluginsDirty || toolsDirty || themeDirty;
  }, [savedConfig, draftConfig, savedControlSettings, draftControlSettings, savedPluginDrafts, draftPluginDrafts, savedToolDrafts, draftToolDrafts, savedThemeMode, draftThemeMode]);

  // ========================================
  // Event Handlers
  // ========================================

  const handleThemePreviewChange = useCallback((mode: ThemeMode) => {
    setDraftThemeMode(mode);
    setThemeMode(mode, { persist: false });
  }, [setThemeMode]);

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
    t, savedConfig, draftConfig, savedControlSettings, draftControlSettings, savedPluginDrafts, draftPluginDrafts,
    savedToolDrafts, draftToolDrafts, savedThemeMode, draftThemeMode,
    tools, plugins, setThemeMode, fetchTimelineStatuses, loadPlugins, loadTools,
  ]);

  const handleDiscardChanges = useCallback(async () => {
    setDraftConfig(structuredClone(savedConfig));
    setDraftControlSettings(savedControlSettings ? structuredClone(savedControlSettings) : null);
    setDraftPluginDrafts(structuredClone(savedPluginDrafts));
    setDraftToolDrafts(structuredClone(savedToolDrafts));
    setDraftThemeMode(savedThemeMode);
    setThemeMode(savedThemeMode, { persist: true });
    await previewLanguageSelection(savedConfig.preferences.language);
  }, [savedConfig, savedControlSettings, savedPluginDrafts, savedToolDrafts, savedThemeMode, setThemeMode]);

  // ========================================
  // Ref Handle
  // ========================================

  const handleRef = useRef<{
    hasUnsavedChanges: () => boolean;
    discardChanges: () => Promise<void>;
  }>({
    hasUnsavedChanges: () => dirty,
    discardChanges: handleDiscardChanges,
  });

  // Update ref when dependencies change
  handleRef.current.hasUnsavedChanges = () => dirty;
  handleRef.current.discardChanges = handleDiscardChanges;

  const getHandle = useCallback((): SettingsPageHandle => handleRef.current, []);

  // ========================================
  // Return
  // ========================================

  return {
    // Loading states
    loading,
    saving,

    // Navigation
    activeSection,
    setActiveSection,
    expandedGroups,
    getGroupExpanded,
    setGroupExpanded,
    handleNavItemClick,

    // Section helpers
    usesInnerPaneScroll,

    // Config state
    draftConfig,
    patchDraftConfig,
    syncNormalizedLlmConfig,
    draftControlSettings,
    patchDraftControlSettings,

    // Theme state
    draftThemeMode,
    handleThemePreviewChange,

    // Language
    handleLanguagePreviewChange,

    // Memory
    updateMemoryToggle,

    // Plugins
    plugins,
    pluginsLoading,
    pluginProcessingIds,
    reloadingActionPlugins,
    draftPluginDrafts,
    handlePluginDraftChange,
    handlePluginDraftChanges,
    handlePluginAction,
    handleReloadActionPlugin,
    loadPlugins,
    loadPluginsAndSensors,

    // Tools
    tools,
    toolsLoading,
    toolsError,
    draftToolDrafts,
    handleToolDraftChange,
    handleToolEnabledChange,

    // Timeline
    timelineStatuses,
    timelineStatusesLoading,
    timelineSelection,
    setTimelineSelection,
    fetchTimelineStatuses,

    // Contribution sub-nav selections
    channelsSelection,
    setChannelsSelection,

    // Dirty tracking
    dirty,

    // Actions
    handleSaveChanges,
    handleDiscardChanges,

    // Ref handle
    getHandle,
  };
}
