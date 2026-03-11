import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Blocks, CheckCircle2, PlugZap, RefreshCw, ShieldCheck, ShieldX, TriangleAlert } from 'lucide-react';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';

import {
  buildPluginFieldValueMap,
  pluginsApi,
  type ExtensionFieldSpec,
  type PluginPackageState,
} from '@/api/modules/plugins';
import PluginSettingsFields from '@/components/settings/PluginSettingsFields';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

const collectSurfaceFields = (
  plugin: PluginPackageState,
  surface: ExtensionFieldSpec['surface']
): ExtensionFieldSpec[] =>
  plugin.contributions
    .flatMap((contribution) => contribution.fields)
    .filter((field) => field.surface === surface);

export const ExtensionsSection: React.FC = () => {
  const { t } = useTranslation('app');
  const [plugins, setPlugins] = useState<PluginPackageState[]>([]);
  const [loading, setLoading] = useState(true);
  const [processingIds, setProcessingIds] = useState<Record<string, string>>({});
  const [drafts, setDrafts] = useState<Record<string, Record<string, any>>>({});
  const saveTimersRef = useRef<Record<string, number>>({});
  const pendingUpdatesRef = useRef<Record<string, Record<string, any>>>({});

  const loadPlugins = async (loader: () => Promise<{ plugins: PluginPackageState[] }>) => {
    setLoading(true);
    try {
      const response = await loader();
      setPlugins(response.plugins || []);
      setDrafts(
        Object.fromEntries(
          (response.plugins || []).map((plugin) => [
            plugin.manifest.plugin_id,
            buildPluginFieldValueMap(collectSurfaceFields(plugin, 'extensions'), plugin.current_settings),
          ])
        )
      );
    } catch (error: any) {
      toast.error(t('settings.extensions.errors.loadFailed', { message: error?.message || 'unknown' }));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadPlugins(pluginsApi.list);
  }, []);

  const pluginCount = useMemo(() => plugins.length, [plugins]);

  const updatePlugin = (plugin: PluginPackageState) => {
    setPlugins((prev) => prev.map((item) => (item.manifest.plugin_id === plugin.manifest.plugin_id ? plugin : item)));
    setDrafts((prev) => ({
      ...prev,
      [plugin.manifest.plugin_id]: buildPluginFieldValueMap(
        collectSurfaceFields(plugin, 'extensions'),
        plugin.current_settings
      ),
    }));
  };

  const handlePluginAction = async (
    pluginId: string,
    action: 'enable' | 'disable' | 'reload'
  ) => {
    setProcessingIds((prev) => ({ ...prev, [pluginId]: action }));
    try {
      const next =
        action === 'enable'
          ? await pluginsApi.enable(pluginId)
          : action === 'disable'
            ? await pluginsApi.disable(pluginId)
            : await pluginsApi.reload(pluginId);
      updatePlugin(next);
      toast.success(t(`settings.extensions.feedback.${action}Success`, { name: next.manifest.name }));
    } catch (error: any) {
      toast.error(t('settings.extensions.errors.actionFailed', { message: error?.message || 'unknown' }));
    } finally {
      setProcessingIds((prev) => {
        const next = { ...prev };
        delete next[pluginId];
        return next;
      });
    }
  };

  const handleRescan = async () => {
    await loadPlugins(pluginsApi.rescan);
    toast.success(t('settings.extensions.feedback.rescanSuccess'));
  };

  const queueFieldSave = (plugin: PluginPackageState, key: string, value: any) => {
    const pluginId = plugin.manifest.plugin_id;
    setDrafts((prev) => ({
      ...prev,
      [pluginId]: {
        ...(prev[pluginId] || {}),
        [key]: value,
      },
    }));
    pendingUpdatesRef.current[pluginId] = {
      ...(pendingUpdatesRef.current[pluginId] || {}),
      [key]: value,
    };

    if (saveTimersRef.current[pluginId]) {
      window.clearTimeout(saveTimersRef.current[pluginId]);
    }

    saveTimersRef.current[pluginId] = window.setTimeout(async () => {
      try {
        const updates = pendingUpdatesRef.current[pluginId] || {};
        pendingUpdatesRef.current[pluginId] = {};
        const next = await pluginsApi.updateSettings(pluginId, updates);
        updatePlugin(next);
        toast.success(t('settings.extensions.feedback.settingsSaved', { name: next.manifest.name }));
      } catch (error: any) {
        toast.error(t('settings.extensions.errors.settingsSaveFailed', { message: error?.message || 'unknown' }));
      }
    }, 400);
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">{t('settings.tabs.extensions')}</h2>
          <p className="text-sm text-muted-foreground">{t('settings.extensionsDesc')}</p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="secondary" className="rounded-full px-3 py-1">
            {t('settings.extensions.summary', { count: pluginCount })}
          </Badge>
          <Button type="button" variant="outline" size="sm" onClick={() => void handleRescan()}>
            <RefreshCw className="mr-2 h-4 w-4" />
            {t('settings.extensions.actions.rescan')}
          </Button>
        </div>
      </div>

      <div className="grid gap-4">
        {plugins.map((plugin) => {
          const extensionFields = collectSurfaceFields(plugin, 'extensions');
          const operation = processingIds[plugin.manifest.plugin_id];
          return (
            <Card key={plugin.manifest.plugin_id} className="border-border/50 bg-card/80 shadow-sm">
              <CardHeader>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="space-y-2">
                    <CardTitle className="flex items-center gap-2">
                      <PlugZap className="h-4 w-4 text-primary" />
                      {plugin.manifest.name}
                    </CardTitle>
                    <CardDescription>{plugin.manifest.description || t('settings.extensions.emptyDescription')}</CardDescription>
                    <div className="flex flex-wrap gap-2">
                      <Badge variant={plugin.enabled ? 'default' : 'secondary'}>
                        {plugin.enabled ? t('settings.extensions.status.enabled') : t('settings.extensions.status.disabled')}
                      </Badge>
                      <Badge variant={plugin.healthy ? 'secondary' : 'destructive'}>
                        {plugin.healthy ? t('settings.extensions.status.healthy') : t('settings.extensions.status.unhealthy')}
                      </Badge>
                      <Badge variant="outline">
                        {plugin.manifest.source} · v{plugin.manifest.version}
                      </Badge>
                      {plugin.trusted ? (
                        <Badge variant="secondary">
                          <ShieldCheck className="mr-1 h-3 w-3" />
                          {t('settings.extensions.status.trusted')}
                        </Badge>
                      ) : (
                        <Badge variant="outline">
                          <ShieldX className="mr-1 h-3 w-3" />
                          {t('settings.extensions.status.untrusted')}
                        </Badge>
                      )}
                    </div>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    <Button
                      type="button"
                      variant={plugin.enabled ? 'outline' : 'default'}
                      size="sm"
                      disabled={operation === 'enable' || operation === 'disable'}
                      onClick={() => void handlePluginAction(plugin.manifest.plugin_id, plugin.enabled ? 'disable' : 'enable')}
                    >
                      {plugin.enabled
                        ? t('settings.extensions.actions.disable')
                        : t('settings.extensions.actions.enable')}
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={operation === 'reload'}
                      onClick={() => void handlePluginAction(plugin.manifest.plugin_id, 'reload')}
                    >
                      <RefreshCw className={operation === 'reload' ? 'mr-2 h-4 w-4 animate-spin' : 'mr-2 h-4 w-4'} />
                      {t('settings.extensions.actions.reload')}
                    </Button>
                  </div>
                </div>
              </CardHeader>

              <CardContent className="space-y-4">
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {plugin.contributions.map((contribution) => (
                    <div
                      key={contribution.contribution_id}
                      className="rounded-2xl border border-border/50 bg-background/70 p-4"
                    >
                      <div className="flex items-center gap-2">
                        <Blocks className="h-4 w-4 text-primary" />
                        <p className="text-sm font-medium text-foreground">{contribution.display_name}</p>
                      </div>
                      <p className="mt-2 text-xs text-muted-foreground">{contribution.description || contribution.contribution_id}</p>
                      <div className="mt-3 flex flex-wrap gap-2">
                        <Badge variant="outline">{contribution.contribution_type}</Badge>
                        <Badge variant="secondary">{contribution.surface}</Badge>
                      </div>
                    </div>
                  ))}
                </div>

                {plugin.last_error ? (
                  <div className="rounded-2xl border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive">
                    <div className="flex items-center gap-2 font-medium">
                      <TriangleAlert className="h-4 w-4" />
                      {t('settings.extensions.status.lastError')}
                    </div>
                    <p className="mt-2">{plugin.last_error}</p>
                  </div>
                ) : null}

                {extensionFields.length > 0 ? (
                  <PluginSettingsFields
                    fields={extensionFields}
                    values={drafts[plugin.manifest.plugin_id] || {}}
                    onChange={(key, value) => queueFieldSave(plugin, key, value)}
                    disabled={!plugin.enabled}
                  />
                ) : (
                  <div className="rounded-2xl border border-dashed border-border/50 bg-background/60 px-4 py-3 text-sm text-muted-foreground">
                    <div className="flex items-center gap-2">
                      <CheckCircle2 className="h-4 w-4 text-primary" />
                      {t('settings.extensions.emptySettings')}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          );
        })}

        {!loading && plugins.length === 0 ? (
          <Card className="border-dashed border-border/60 bg-card/60">
            <CardContent className="py-8 text-center text-sm text-muted-foreground">
              {t('settings.extensions.emptyState')}
            </CardContent>
          </Card>
        ) : null}
      </div>
    </div>
  );
};

export default ExtensionsSection;
