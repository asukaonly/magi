/**
 * Settings page state management hook.
 *
 * Manages all configuration, plugins, tools, and timeline state with
 * a saved/draft pattern for dirty tracking and save/discard operations.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';

import { configApi, DEFAULT_SYSTEM_CONFIG, SystemConfig, type LanguageCode } from '@/api/modules/config';
import { pluginsApi, type PluginPackageState } from '@/api/modules/plugins';
import { toolsApi, type ToolConfig } from '@/api/modules/tools';
import { sensorsApi, type SensorSourceStatusItem } from '@/api/modules/sensors';
import { useThemeStore, type ThemeMode } from '@/stores/theme';
import { syncCloseToTrayPreference } from '@/runtime/desktop';
import type {
  MemoryToggleFieldId,
  PluginDraftMap,
  SettingsPageHandle,
  ToolDraftMap,
} from '@/types/settings';
import {
  buildPluginDraftSnapshotFromPackages,
  buildPluginDraftSnapshotFromSensors,
  buildToolDraftSnapshot,
  diffFlatMaps,
  mergeDraftMaps,
  persistLanguageSelection,
  previewLanguageSelection,
  serialize,
} from '@/utils/settings-helpers';

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
  isWideSection: boolean;
  usesInnerPaneScroll: boolean;

  // Config state (saved/draft)
  draftConfig: SystemConfig;
  patchDraftConfig: (updater: (draft: SystemConfig) => void) => void;
  syncNormalizedLlmConfig: (nextLlmConfig: SystemConfig['llm']) => void;

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

  // Config state (saved/draft)
  const [savedConfig, setSavedConfig] = useState<SystemConfig>(DEFAULT_SYSTEM_CONFIG);
  const [draftConfig, setDraftConfig] = useState<SystemConfig>(DEFAULT_SYSTEM_CONFIG);

  // Theme state (saved/draft)
  const [savedThemeMode, setSavedThemeMode] = useState<ThemeMode>(themeMode);
  const [draftThemeMode, setDraftThemeMode] = useState<ThemeMode>(themeMode);

  // Loading states
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // Navigation state
  const [activeSection, setActiveSection] = useState('preferences');
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({
    llm: false,
    memory: false,
    timeline: false,
  });

  // Timeline state
  const [timelineStatuses, setTimelineStatuses] = useState<SensorSourceStatusItem[]>([]);
  const [timelineStatusesLoading, setTimelineStatusesLoading] = useState(false);
  const [timelineSelection, setTimelineSelection] = useState<string | null>(null);

  // Plugins state
  const [plugins, setPlugins] = useState<PluginPackageState[]>([]);
  const [pluginsLoading, setPluginsLoading] = useState(false);
  const [pluginProcessingIds, setPluginProcessingIds] = useState<Record<string, string>>({});
  const [savedPluginDrafts, setSavedPluginDrafts] = useState<PluginDraftMap>({});
  const [draftPluginDrafts, setDraftPluginDrafts] = useState<PluginDraftMap>({});

  // Tools state
  const [tools, setTools] = useState<ToolConfig[]>([]);
  const [toolsLoading, setToolsLoading] = useState(false);
  const [toolsError, setToolsError] = useState<string | null>(null);
  const [savedToolDrafts, setSavedToolDrafts] = useState<ToolDraftMap>({});
  const [draftToolDrafts, setDraftToolDrafts] = useState<ToolDraftMap>({});
  const [reloadingActionPlugins, setReloadingActionPlugins] = useState<Record<string, boolean>>({});

  // ========================================
  // Dirty Tracking
  // ========================================

  // ========================================
  // Navigation Helpers
  // ========================================

  const isWideSection = useMemo(
    () =>
      activeSection === 'llmProviders'
      || activeSection === 'llmModels'
      || activeSection === 'timeline'
      || activeSection === 'personality'
      || activeSection === 'statisticsLlm'
      || activeSection === 'statisticsRuntime',
    [activeSection]
  );

  const usesInnerPaneScroll = useMemo(
    () => activeSection === 'llmProviders',
    [activeSection]
  );

  const getGroupExpanded = useCallback(
    (groupId: string) => expandedGroups[groupId] ?? false,
    [expandedGroups]
  );

  const setGroupExpanded = useCallback((groupId: string, expanded: boolean) => {
    setExpandedGroups((prev) => ({ ...prev, [groupId]: expanded }));
  }, []);

  const handleNavItemClick = useCallback(
    (itemId: string, isGroup: boolean, firstChildId?: string) => {
      if (isGroup) {
        const isExpanded = getGroupExpanded(itemId);
        if (isExpanded) {
          setGroupExpanded(itemId, false);
          return;
        }
        setGroupExpanded(itemId, true);
        setActiveSection(firstChildId || itemId);
        return;
      }
      setActiveSection(itemId);
      if (itemId === 'timeline') {
        setTimelineSelection(null);
      }
    },
    [getGroupExpanded, setGroupExpanded]
  );

  // ========================================
  // Config Mutation Helpers
  // ========================================

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

  // ========================================
  // Data Loading Functions
  // ========================================

  const fetchTimelineStatuses = useCallback(async () => {
    setTimelineStatusesLoading(true);
    try {
      const response = await sensorsApi.getStatus();
      const nextStatuses = response.sources || [];
      const nextSnapshot = buildPluginDraftSnapshotFromSensors(nextStatuses);
      setTimelineStatuses(nextStatuses);
      setSavedPluginDrafts((prev) => mergeDraftMaps(prev, nextSnapshot, { preserveExisting: false }));
      setDraftPluginDrafts((prev) => mergeDraftMaps(prev, nextSnapshot, { preserveExisting: true }));
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'unknown';
      toast.error(t('settings.timeline.errors.statusLoadFailed', { message }));
      setTimelineStatuses([]);
    } finally {
      setTimelineStatusesLoading(false);
    }
  }, [t]);

  const loadPlugins = useCallback(async ({ silent = false }: { silent?: boolean } = {}) => {
    if (!silent) {
      setPluginsLoading(true);
    }
    try {
      const response = await pluginsApi.list();
      const nextPlugins = response.plugins || [];
      const nextSnapshot = buildPluginDraftSnapshotFromPackages(nextPlugins);
      setPlugins(nextPlugins);
      setSavedPluginDrafts((prev) => mergeDraftMaps(prev, nextSnapshot, { preserveExisting: false }));
      setDraftPluginDrafts((prev) => mergeDraftMaps(prev, nextSnapshot, { preserveExisting: true }));
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'unknown';
      toast.error(t('settings.extensions.errors.loadFailed', { message }));
    } finally {
      if (!silent) {
        setPluginsLoading(false);
      }
    }
  }, [t]);

  const loadTools = useCallback(async ({ silent = false }: { silent?: boolean } = {}) => {
    if (!silent) {
      setToolsLoading(true);
      setToolsError(null);
    }
    try {
      const response = await toolsApi.listWithConfig();
      const nextTools = response.tools || [];
      const nextDrafts = buildToolDraftSnapshot(nextTools);
      setTools(nextTools);
      setSavedToolDrafts(nextDrafts);
      setDraftToolDrafts((prev) => {
        if (Object.keys(prev).length === 0) {
          return nextDrafts;
        }
        const merged = structuredClone(prev);
        for (const [toolName, snapshot] of Object.entries(nextDrafts)) {
          merged[toolName] = {
            enabled: merged[toolName]?.enabled ?? snapshot.enabled,
            values: {
              ...snapshot.values,
              ...(merged[toolName]?.values || {}),
            },
          };
        }
        return merged;
      });
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : t('settings.errorUnknown');
      setToolsError(t('settings.loadToolsFailed', { message }));
      toast.error(t('settings.loadToolsFailed', { message }));
    } finally {
      if (!silent) {
        setToolsLoading(false);
      }
    }
  }, [t]);

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
  }, [t, themeMode]);

  // ========================================
  // Effects
  // ========================================

  // Initial data load
  useEffect(() => {
    void Promise.all([
      fetchConfig(),
      fetchTimelineStatuses(),
      loadPlugins(),
      loadTools(),
    ]);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

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
    const pluginsDirty = serialize(savedPluginDrafts) !== serialize(draftPluginDrafts);
    const toolsDirty = serialize(savedToolDrafts) !== serialize(draftToolDrafts);
    const themeDirty = savedThemeMode !== draftThemeMode;
    return configDirty || pluginsDirty || toolsDirty || themeDirty;
  }, [savedConfig, draftConfig, savedPluginDrafts, draftPluginDrafts, savedToolDrafts, draftToolDrafts, savedThemeMode, draftThemeMode]);

  // ========================================
  // Event Handlers
  // ========================================

  const handleThemePreviewChange = useCallback((mode: ThemeMode) => {
    setDraftThemeMode(mode);
    setThemeMode(mode, { persist: false });
  }, [setThemeMode]);

  const handleLanguagePreviewChange = useCallback((value: string) => {
    const nextLanguage = value as LanguageCode;
    patchDraftConfig((draft) => {
      draft.preferences.language = nextLanguage;
    });
    void previewLanguageSelection(nextLanguage);
  }, [patchDraftConfig]);

  const handlePluginDraftChange = useCallback((pluginId: string, key: string, value: unknown) => {
    setDraftPluginDrafts((prev) => ({
      ...prev,
      [pluginId]: {
        ...(prev[pluginId] || {}),
        [key]: value,
      },
    }));
  }, []);

  const handlePluginDraftChanges = useCallback((pluginId: string, updates: Record<string, unknown>) => {
    setDraftPluginDrafts((prev) => ({
      ...prev,
      [pluginId]: {
        ...(prev[pluginId] || {}),
        ...updates,
      },
    }));
  }, []);

  const handleToolDraftChange = useCallback((toolName: string, path: string, value: unknown) => {
    setDraftToolDrafts((prev) => ({
      ...prev,
      [toolName]: {
        enabled: prev[toolName]?.enabled ?? tools.find((tool) => tool.name === toolName)?.enabled ?? true,
        values: {
          ...(prev[toolName]?.values || {}),
          [path]: value,
        },
      },
    }));
  }, [tools]);

  const handleToolEnabledChange = useCallback((toolName: string, enabled: boolean) => {
    setDraftToolDrafts((prev) => ({
      ...prev,
      [toolName]: {
        enabled,
        values: {
          ...(prev[toolName]?.values || tools.find((tool) => tool.name === toolName)?.current_values || {}),
        },
      },
    }));
  }, [tools]);

  const handlePluginAction = useCallback(async (pluginId: string, action: 'enable' | 'disable' | 'reload') => {
    setPluginProcessingIds((prev) => ({ ...prev, [pluginId]: action }));
    try {
      const next =
        action === 'enable'
          ? await pluginsApi.enable(pluginId)
          : action === 'disable'
            ? await pluginsApi.disable(pluginId)
            : await pluginsApi.reload(pluginId);
      const nextSnapshot = buildPluginDraftSnapshotFromPackages([next]);
      setPlugins((prev) => prev.map((item) => (item.manifest.plugin_id === next.manifest.plugin_id ? next : item)));
      setSavedPluginDrafts((prev) => mergeDraftMaps(prev, nextSnapshot, { preserveExisting: false }));
      setDraftPluginDrafts((prev) => mergeDraftMaps(prev, nextSnapshot, { preserveExisting: false }));
      toast.success(t(`settings.extensions.feedback.${action}Success`, { name: next.manifest.name }));
      await fetchTimelineStatuses();
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'unknown';
      toast.error(t('settings.extensions.errors.actionFailed', { message }));
    } finally {
      setPluginProcessingIds((prev) => {
        const next = { ...prev };
        delete next[pluginId];
        return next;
      });
    }
  }, [t, fetchTimelineStatuses]);

  const handleReloadActionPlugin = useCallback(async (pluginId: string) => {
    setReloadingActionPlugins((prev) => ({ ...prev, [pluginId]: true }));
    try {
      const next = await pluginsApi.reload(pluginId);
      const nextSnapshot = buildPluginDraftSnapshotFromPackages([next]);
      setPlugins((prev) => prev.map((item) => (item.manifest.plugin_id === next.manifest.plugin_id ? next : item)));
      setSavedPluginDrafts((prev) => mergeDraftMaps(prev, nextSnapshot, { preserveExisting: false }));
      setDraftPluginDrafts((prev) => mergeDraftMaps(prev, nextSnapshot, { preserveExisting: false }));
      toast.success(t('settings.actionsConfig.feedback.reloadSuccess', { name: next.manifest.name }));
      await fetchTimelineStatuses();
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'unknown';
      toast.error(t('settings.actionsConfig.errors.reloadFailed', { message }));
    } finally {
      setReloadingActionPlugins((prev) => ({ ...prev, [pluginId]: false }));
    }
  }, [t, fetchTimelineStatuses]);

  const handleSaveChanges = useCallback(async () => {
    setSaving(true);
    try {
      const configDirty = serialize(savedConfig) !== serialize(draftConfig);
      const pluginsDirty = serialize(savedPluginDrafts) !== serialize(draftPluginDrafts);
      const toolsDirty = serialize(savedToolDrafts) !== serialize(draftToolDrafts);
      const themeDirty = savedThemeMode !== draftThemeMode;
      let persistedConfig = structuredClone(draftConfig);

      if (configDirty) {
        const response = await configApi.update(draftConfig);
        persistedConfig = structuredClone(response.data || draftConfig);
        await syncCloseToTrayPreference(persistedConfig.preferences.close_to_tray_enabled);
        setSavedConfig(structuredClone(persistedConfig));
        setDraftConfig(structuredClone(persistedConfig));
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
    t, savedConfig, draftConfig, savedPluginDrafts, draftPluginDrafts,
    savedToolDrafts, draftToolDrafts, savedThemeMode, draftThemeMode,
    tools, plugins, setThemeMode, fetchTimelineStatuses, loadPlugins, loadTools,
  ]);

  const handleDiscardChanges = useCallback(async () => {
    setDraftConfig(structuredClone(savedConfig));
    setDraftPluginDrafts(structuredClone(savedPluginDrafts));
    setDraftToolDrafts(structuredClone(savedToolDrafts));
    setDraftThemeMode(savedThemeMode);
    setThemeMode(savedThemeMode, { persist: true });
    await previewLanguageSelection(savedConfig.preferences.language);
  }, [savedConfig, savedPluginDrafts, savedToolDrafts, savedThemeMode, setThemeMode]);

  // ========================================
  // Memory Toggle Handler
  // ========================================

  const updateMemoryToggle = useCallback((field: MemoryToggleFieldId, checked: boolean) => {
    patchDraftConfig((draft) => {
      if (field === 'l1' && !checked) {
        draft.memory.l1.enabled = false;
        draft.memory.l2.enabled = false;
        draft.memory.l3.enabled = false;
        draft.memory.l4.enabled = false;
        draft.memory.l1.t1_importance_enabled = false;
        draft.memory.l2.llm_extraction_enabled = false;
        draft.memory.l2.vectors_enabled = false;
        draft.memory.l3.llm_summary_enabled = false;
        draft.memory.l4.skill_extraction_enabled = false;
        return;
      }

      if (field === 'l2' && !checked) {
        draft.memory.l2.enabled = false;
        draft.memory.l2.llm_extraction_enabled = false;
        draft.memory.l2.vectors_enabled = false;
        return;
      }

      if (field === 'l3' && !checked) {
        draft.memory.l3.enabled = false;
        draft.memory.l3.llm_summary_enabled = false;
        return;
      }

      if (field === 'l4' && !checked) {
        draft.memory.l4.enabled = false;
        draft.memory.l4.skill_extraction_enabled = false;
        return;
      }

      draft.memory[field].enabled = checked;
    });
  }, [patchDraftConfig]);

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
    isWideSection,
    usesInnerPaneScroll,

    // Config state
    draftConfig,
    patchDraftConfig,
    syncNormalizedLlmConfig,

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

    // Dirty tracking
    dirty,

    // Actions
    handleSaveChanges,
    handleDiscardChanges,

    // Ref handle
    getHandle,
  };
}
