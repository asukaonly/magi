/**
 * Settings page state management hook.
 *
 * Manages all configuration, plugins, tools, and timeline state with
 * a saved/draft pattern for dirty tracking and save/discard operations.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { type SystemConfig } from '@/api/modules/config';
import { type ControlSettingsDTO } from '@/api/modules/control';
import { type PluginPackageState, type PluginRegistryEntry } from '@/api/modules/plugins';
import { type ToolConfig } from '@/api/modules/tools';
import { type SensorSourceStatusItem } from '@/api/modules/sensors';
import { useThemeStore, type ThemeMode } from '@/stores/theme';
import type {
  MemoryToggleFieldId,
  SettingsPageHandle,
  ToolDraftMap,
} from '@/types/settings';
import { serialize } from '@/utils/settings-helpers';
import { getTimelineCapabilityId } from '@/utils/timeline-capabilities';
import { useSettingsConfig } from './useSettingsConfig';
import { useSettingsNavigation } from './useSettingsNavigation';
import { useSettingsPersistence, type EmbeddingPreflightPrompt } from './useSettingsPersistence';
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
  handleLanguageDraftChange: (value: string) => void;

  updateMemoryToggle: (field: MemoryToggleFieldId, checked: boolean) => void;

  // Plugins
  plugins: PluginPackageState[];
  pluginsLoading: boolean;
  pluginRegistryEntries: PluginRegistryEntry[];
  pluginRegistryFingerprint: string | null;
  pluginRegistryLoading: boolean;
  pluginProcessingIds: Record<string, string>;
  handlePluginAction: (pluginId: string, action: 'reload') => Promise<void>;
  loadPlugins: (options?: { silent?: boolean }) => Promise<void>;
  loadPluginRegistry: (options?: { silent?: boolean; force?: boolean }) => Promise<void>;
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
  embeddingPreflightPrompt: EmbeddingPreflightPrompt | null;
  confirmEmbeddingPreflight: () => void;
  cancelEmbeddingPreflight: () => void;

  // Ref handle getter
  getHandle: () => SettingsPageHandle;
}

// ============================================================================
// Hook Implementation
// ============================================================================

export function useSettings(): UseSettingsReturn {
  const themeMode = useThemeStore((state) => state.mode);
  const setThemeMode = useThemeStore((state) => state.setMode);

  // ========================================
  // State Declarations
  // ========================================

  // Theme state (saved/draft)
  const [savedThemeMode, setSavedThemeMode] = useState<ThemeMode>(themeMode);
  const [draftThemeMode, setDraftThemeMode] = useState<ThemeMode>(themeMode);

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
    handleLanguageDraftChange,
    updateMemoryToggle,
  } = useSettingsConfig({
    themeMode,
    setSavedThemeMode,
    setDraftThemeMode,
  });
  const initialLoadStartedRef = useRef(false);

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
    pluginRegistryEntries,
    pluginRegistryFingerprint,
    pluginRegistryLoading,
    pluginProcessingIds,
    handlePluginAction,
    loadPlugins,
    loadPluginRegistry,
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

  const {
    saving,
    handleSaveChanges,
    handleDiscardChanges,
    embeddingPreflightPrompt,
    confirmEmbeddingPreflight,
    cancelEmbeddingPreflight,
  } = useSettingsPersistence({
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
  });

  // ========================================
  // Effects
  // ========================================

  // Initial data load
  useEffect(() => {
    if (initialLoadStartedRef.current) {
      return;
    }
    initialLoadStartedRef.current = true;
    void Promise.all([
      fetchConfig(),
      loadControlSettings(),
      fetchTimelineStatuses(),
      loadPlugins(),
      loadPluginRegistry({ silent: true }),
      loadTools(),
    ]);
  }, [fetchConfig, loadControlSettings, fetchTimelineStatuses, loadPlugins, loadPluginRegistry, loadTools]);

  // Reset timeline selection when statuses change
  useEffect(() => {
    if (
      timelineSelection
      && !timelineStatuses.some((source) =>
        source.source_name === timelineSelection || getTimelineCapabilityId(source) === timelineSelection
      )
    ) {
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
    const toolsDirty = serialize(savedToolDrafts) !== serialize(draftToolDrafts);
    const themeDirty = savedThemeMode !== draftThemeMode;
    return configDirty || controlDirty || toolsDirty || themeDirty;
  }, [savedConfig, draftConfig, savedControlSettings, draftControlSettings, savedToolDrafts, draftToolDrafts, savedThemeMode, draftThemeMode]);

  // ========================================
  // Event Handlers
  // ========================================

  const handleThemePreviewChange = useCallback((mode: ThemeMode) => {
    setDraftThemeMode(mode);
    setThemeMode(mode, { persist: false });
  }, [setThemeMode]);

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
    handleLanguageDraftChange,

    // Memory
    updateMemoryToggle,

    // Plugins
    plugins,
    pluginsLoading,
    pluginRegistryEntries,
    pluginRegistryFingerprint,
    pluginRegistryLoading,
    pluginProcessingIds,
    handlePluginAction,
    loadPlugins,
    loadPluginRegistry,
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
    embeddingPreflightPrompt,
    confirmEmbeddingPreflight,
    cancelEmbeddingPreflight,

    // Ref handle
    getHandle,
  };
}
