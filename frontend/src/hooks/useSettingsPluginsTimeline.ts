import { type Dispatch, type SetStateAction, useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import { pluginsApi, type PluginPackageState, type PluginRegistryEntry } from '@/api/modules/plugins';
import { sensorsApi, type SensorSourceStatusItem } from '@/api/modules/sensors';
import type { PluginDraftMap } from '@/types/settings';
import {
  buildPluginDraftSnapshotFromPackages,
  buildPluginDraftSnapshotFromSensors,
  mergeDraftMaps,
} from '@/utils/settings-helpers';

interface UseSettingsPluginsTimelineReturn {
  plugins: PluginPackageState[];
  pluginsLoading: boolean;
  pluginRegistryEntries: PluginRegistryEntry[];
  pluginRegistryLoading: boolean;
  pluginProcessingIds: Record<string, string>;
  reloadingActionPlugins: Record<string, boolean>;
  savedPluginDrafts: PluginDraftMap;
  setSavedPluginDrafts: Dispatch<SetStateAction<PluginDraftMap>>;
  draftPluginDrafts: PluginDraftMap;
  setDraftPluginDrafts: Dispatch<SetStateAction<PluginDraftMap>>;
  handlePluginDraftChange: (pluginId: string, key: string, value: unknown) => void;
  handlePluginDraftChanges: (pluginId: string, updates: Record<string, unknown>) => void;
  applyPersistedPluginSettings: (pluginId: string, updates: Record<string, unknown>) => void;
  handlePluginAction: (pluginId: string, action: 'enable' | 'disable' | 'reload') => Promise<void>;
  handleReloadActionPlugin: (pluginId: string) => Promise<void>;
  loadPlugins: (options?: { silent?: boolean }) => Promise<void>;
  loadPluginRegistry: (options?: { silent?: boolean; force?: boolean }) => Promise<void>;
  loadPluginsAndSensors: () => Promise<void>;
  timelineStatuses: SensorSourceStatusItem[];
  timelineStatusesLoading: boolean;
  fetchTimelineStatuses: () => Promise<void>;
}

export function useSettingsPluginsTimeline(): UseSettingsPluginsTimelineReturn {
  const { t } = useTranslation('app');
  const [timelineStatuses, setTimelineStatuses] = useState<SensorSourceStatusItem[]>([]);
  const [timelineStatusesLoading, setTimelineStatusesLoading] = useState(false);
  const [plugins, setPlugins] = useState<PluginPackageState[]>([]);
  const [pluginsLoading, setPluginsLoading] = useState(false);
  const [pluginRegistryEntries, setPluginRegistryEntries] = useState<PluginRegistryEntry[]>([]);
  const [pluginRegistryLoading, setPluginRegistryLoading] = useState(false);
  const [pluginProcessingIds, setPluginProcessingIds] = useState<Record<string, string>>({});
  const [savedPluginDrafts, setSavedPluginDrafts] = useState<PluginDraftMap>({});
  const [draftPluginDrafts, setDraftPluginDrafts] = useState<PluginDraftMap>({});
  const [reloadingActionPlugins, setReloadingActionPlugins] = useState<Record<string, boolean>>({});

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
      toast.error(t('settings.pluginPackages.errors.loadFailed', { message }));
    } finally {
      if (!silent) {
        setPluginsLoading(false);
      }
    }
  }, [t]);

  const loadPluginRegistry = useCallback(async ({
    silent = false,
    force = false,
  }: { silent?: boolean; force?: boolean } = {}) => {
    if (!silent) {
      setPluginRegistryLoading(true);
    }
    try {
      const response = await pluginsApi.getRegistry({ force });
      setPluginRegistryEntries(response.plugins || []);
    } catch {
      setPluginRegistryEntries([]);
    } finally {
      if (!silent) {
        setPluginRegistryLoading(false);
      }
    }
  }, []);

  const loadPluginsAndSensors = useCallback(async () => {
    await loadPlugins();
    await fetchTimelineStatuses();
    await loadPluginRegistry({ silent: true });
  }, [loadPlugins, fetchTimelineStatuses, loadPluginRegistry]);


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

  const applyPersistedPluginSettings = useCallback((pluginId: string, updates: Record<string, unknown>) => {
    setSavedPluginDrafts((prev) => ({
      ...prev,
      [pluginId]: {
        ...(prev[pluginId] || {}),
        ...updates,
      },
    }));
    setDraftPluginDrafts((prev) => ({
      ...prev,
      [pluginId]: {
        ...(prev[pluginId] || {}),
        ...updates,
      },
    }));
    setPlugins((prev) =>
      prev.map((plugin) => {
        if (plugin.manifest.plugin_id !== pluginId) {
          return plugin;
        }
        return {
          ...plugin,
          current_settings: {
            ...plugin.current_settings,
            ...updates,
          },
        };
      })
    );
  }, []);

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
      toast.success(t(`settings.pluginPackages.feedback.${action}Success`, { name: next.manifest.name }));
      await fetchTimelineStatuses();
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'unknown';
      toast.error(t('settings.pluginPackages.errors.actionFailed', { message }));
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

  return {
    plugins,
    pluginsLoading,
    pluginRegistryEntries,
    pluginRegistryLoading,
    pluginProcessingIds,
    reloadingActionPlugins,
    savedPluginDrafts,
    setSavedPluginDrafts,
    draftPluginDrafts,
    setDraftPluginDrafts,
    handlePluginDraftChange,
    handlePluginDraftChanges,
    applyPersistedPluginSettings,
    handlePluginAction,
    handleReloadActionPlugin,
    loadPlugins,
    loadPluginRegistry,
    loadPluginsAndSensors,
    timelineStatuses,
    timelineStatusesLoading,
    fetchTimelineStatuses,
  };
}

export type { UseSettingsPluginsTimelineReturn };
