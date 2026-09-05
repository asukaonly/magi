import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import { pluginsApi, type PluginPackageState, type PluginRegistryEntry } from '@/api/modules/plugins';
import { sensorsApi, type SensorSourceStatusItem } from '@/api/modules/sensors';

interface UseSettingsPluginsTimelineReturn {
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
  const [pluginRegistryFingerprint, setPluginRegistryFingerprint] = useState<string | null>(null);
  const [pluginRegistryLoading, setPluginRegistryLoading] = useState(false);
  const [pluginProcessingIds, setPluginProcessingIds] = useState<Record<string, string>>({});

  const fetchTimelineStatuses = useCallback(async () => {
    setTimelineStatusesLoading(true);
    try {
      const response = await sensorsApi.getStatus();
      const nextStatuses = response.sources || [];
      setTimelineStatuses(nextStatuses);
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
      setPlugins(nextPlugins);
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
      setPluginRegistryFingerprint(response.install_fingerprint);
    } catch {
      setPluginRegistryEntries([]);
      setPluginRegistryFingerprint(null);
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

  const handlePluginAction = useCallback(async (pluginId: string, action: 'reload') => {
    setPluginProcessingIds((prev) => ({ ...prev, [pluginId]: action }));
    try {
      const next = await pluginsApi.reload(pluginId);
      setPlugins((prev) => prev.map((item) => (item.manifest.plugin_id === next.manifest.plugin_id ? next : item)));
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

  return {
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
  };
}

export type { UseSettingsPluginsTimelineReturn };
