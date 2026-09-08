import { useCenterRefresh } from '@/hooks/useCenterRefresh';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import { pluginsApi, type PluginPackageState, type PluginRegistryEntry } from '@/api/modules/plugins';
import { sourcesApi, type SourceStatusItem } from '@/api/modules/sources';

interface UseSettingsPluginsTimelineReturn {
  pluginsError: string | null;
  timelineStatusesError: string | null;
  pluginRegistryError: string | null;
  plugins: PluginPackageState[];
  pluginsLoading: boolean;
  pluginRegistryEntries: PluginRegistryEntry[];
  pluginRegistryFingerprint: string | null;
  pluginRegistryLoading: boolean;
  pluginProcessingIds: Record<string, string>;
  handlePluginAction: (pluginId: string, action: 'reload') => Promise<void>;
  loadPlugins: (options?: { silent?: boolean }) => Promise<void>;
  loadPluginRegistry: (options?: { silent?: boolean; force?: boolean }) => Promise<void>;
  loadPluginsAndSources: () => Promise<void>;
  timelineStatuses: SourceStatusItem[];
  timelineStatusesLoading: boolean;
  fetchTimelineStatuses: (options?: { silent?: boolean }) => Promise<void>;
}

export function useSettingsPluginsTimeline(): UseSettingsPluginsTimelineReturn {
  const { t } = useTranslation('app');
  const processingPluginIds = useRef(new Set<string>());
  const requestIds = useRef({ plugins: 0, sources: 0, registry: 0 });
  useEffect(() => () => {
    requestIds.current.plugins += 1;
    requestIds.current.sources += 1;
    requestIds.current.registry += 1;
  }, []);
  const [pluginsError, setPluginsError] = useState<string | null>(null);
  const [timelineStatusesError, setTimelineStatusesError] = useState<string | null>(null);
  const [pluginRegistryError, setPluginRegistryError] = useState<string | null>(null);
  const [timelineStatuses, setTimelineStatuses] = useState<SourceStatusItem[]>([]);
  const [timelineStatusesLoading, setTimelineStatusesLoading] = useState(false);
  const [plugins, setPlugins] = useState<PluginPackageState[]>([]);
  const [pluginsLoading, setPluginsLoading] = useState(false);
  const [pluginRegistryEntries, setPluginRegistryEntries] = useState<PluginRegistryEntry[]>([]);
  const [pluginRegistryFingerprint, setPluginRegistryFingerprint] = useState<string | null>(null);
  const [pluginRegistryLoading, setPluginRegistryLoading] = useState(false);
  const [pluginProcessingIds, setPluginProcessingIds] = useState<Record<string, string>>({});

  const fetchTimelineStatuses = useCallback(async ({ silent = false }: { silent?: boolean } = {}) => {
    const requestId = ++requestIds.current.sources;
    if (!silent) setTimelineStatusesLoading(true);
    try {
      const response = await sourcesApi.getStatus();
      if (requestId !== requestIds.current.sources) return;
      if (!Array.isArray(response.sources)) throw new Error('Invalid source status response');
      setTimelineStatusesError(null);
      const nextStatuses = response.sources;
      setTimelineStatuses(nextStatuses);
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'unknown';
      if (requestId !== requestIds.current.sources) return;
      const errorText = t('settings.timeline.errors.statusLoadFailed', { message });
      if (!silent) setTimelineStatusesError(errorText);
      if (!silent) toast.error(errorText);
    } finally {
      if (requestId === requestIds.current.sources) setTimelineStatusesLoading(false);
    }
  }, [t]);

  const loadPlugins = useCallback(async ({ silent = false }: { silent?: boolean } = {}) => {
    const requestId = ++requestIds.current.plugins;
    if (!silent) {
      setPluginsLoading(true);
    }
    try {
      const response = await pluginsApi.list();
      if (requestId !== requestIds.current.plugins) return;
      setPluginsError(null);
      const nextPlugins = response.plugins;
      setPlugins(nextPlugins);
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'unknown';
      if (requestId !== requestIds.current.plugins) return;
      const errorText = t('settings.pluginPackages.errors.loadFailed', { message });
      if (!silent) setPluginsError(errorText);
      if (!silent) toast.error(errorText);
    } finally {
      if (requestId === requestIds.current.plugins) {
        setPluginsLoading(false);
      }
    }
  }, [t]);

  const loadPluginRegistry = useCallback(async ({
    silent = false,
    force = false,
  }: { silent?: boolean; force?: boolean } = {}) => {
    const requestId = ++requestIds.current.registry;
    if (!silent) {
      setPluginRegistryLoading(true);
    }
    try {
      const response = await pluginsApi.getRegistry({ force });
      if (requestId !== requestIds.current.registry) return;
      setPluginRegistryError(null);
      setPluginRegistryEntries(response.plugins);
      setPluginRegistryFingerprint(response.install_fingerprint);
    } catch (error) {
      if (requestId !== requestIds.current.registry) return;
      const message = error instanceof Error ? error.message : 'unknown';
      if (!silent) setPluginRegistryError(t('settings.pluginPackages.errors.loadFailed', { message }));
    } finally {
      if (requestId === requestIds.current.registry) {
        setPluginRegistryLoading(false);
      }
    }
  }, [t]);

  const loadPluginsAndSources = useCallback(async () => {
    await loadPlugins();
    await fetchTimelineStatuses();
    await loadPluginRegistry({ silent: true });
  }, [loadPlugins, fetchTimelineStatuses, loadPluginRegistry]);

  const handlePluginAction = useCallback(async (pluginId: string, action: 'reload') => {
    if (processingPluginIds.current.has(pluginId)) return;
    processingPluginIds.current.add(pluginId);
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
      processingPluginIds.current.delete(pluginId);
      setPluginProcessingIds((prev) => {
        const next = { ...prev };
        delete next[pluginId];
        return next;
      });
    }
  }, [t, fetchTimelineStatuses]);

  useCenterRefresh(() => Promise.all([loadPlugins({ silent: true }), fetchTimelineStatuses({ silent: true }), loadPluginRegistry({ silent: true })]));

  return {
    pluginsError, timelineStatusesError, pluginRegistryError,
    plugins,
    pluginsLoading,
    pluginRegistryEntries,
    pluginRegistryFingerprint,
    pluginRegistryLoading,
    pluginProcessingIds,
    handlePluginAction,
    loadPlugins,
    loadPluginRegistry,
    loadPluginsAndSources,
    timelineStatuses,
    timelineStatusesLoading,
    fetchTimelineStatuses,
  };
}

export type { UseSettingsPluginsTimelineReturn };
