import React, { useMemo } from 'react';
import { Blocks, CheckCircle2, PlugZap, RefreshCw, ShieldCheck, ShieldX, TriangleAlert } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import {
  type ExtensionFieldSpec,
  type PluginPackageState,
} from '@/api/modules/plugins';
import PluginSettingsFields from '@/components/settings/PluginSettingsFields';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

type TFunction = (key: string) => string;

const collectSurfaceFields = (
  plugin: PluginPackageState,
  surface: ExtensionFieldSpec['surface']
): ExtensionFieldSpec[] =>
  plugin.contributions
    .flatMap((contribution) => contribution.fields)
    .filter((field) => field.surface === surface);

/**
 * Helper function to get plugin-specific translation with fallback
 */
const getPluginTranslation = (
  t: TFunction,
  pluginId: string,
  key: string,
  fallback: string
): string => {
  const translationKey = `settings.plugins.${pluginId}.${key}`;
  const translated = t(translationKey);
  // If translation doesn't exist, i18next returns the key itself
  return translated === translationKey ? fallback : translated;
};

interface ExtensionsSectionProps {
  plugins: PluginPackageState[];
  loading?: boolean;
  drafts: Record<string, Record<string, any>>;
  dirty?: boolean;
  onFieldChange: (pluginId: string, key: string, value: any) => void;
  onRescan: () => Promise<void>;
  onPluginAction: (pluginId: string, action: 'enable' | 'disable' | 'reload') => Promise<void>;
  processingIds: Record<string, string>;
}

export const ExtensionsSection: React.FC<ExtensionsSectionProps> = ({
  plugins,
  loading = false,
  drafts,
  dirty = false,
  onFieldChange,
  onRescan,
  onPluginAction,
  processingIds,
}) => {
  const { t } = useTranslation('app');
  const pluginCount = useMemo(() => plugins.length, [plugins]);

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
          <Button type="button" variant="outline" size="sm" onClick={() => void onRescan()} disabled={dirty}>
            <RefreshCw className="mr-2 h-4 w-4" />
            {t('settings.extensions.actions.rescan')}
          </Button>
        </div>
      </div>

      {loading ? (
        <Card className="border-dashed border-border/60 bg-card/60">
          <CardContent className="py-8 text-center text-sm text-muted-foreground">
            {t('settings.extensions.loading')}
          </CardContent>
        </Card>
      ) : (
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
                        {getPluginTranslation(t, plugin.manifest.plugin_id, 'name', plugin.manifest.name)}
                      </CardTitle>
                      <CardDescription>
                        {getPluginTranslation(t, plugin.manifest.plugin_id, 'description', plugin.manifest.description || t('settings.extensions.emptyDescription'))}
                      </CardDescription>
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
                        disabled={dirty || operation === 'enable' || operation === 'disable'}
                        onClick={() => void onPluginAction(plugin.manifest.plugin_id, plugin.enabled ? 'disable' : 'enable')}
                      >
                        {plugin.enabled
                          ? t('settings.extensions.actions.disable')
                          : t('settings.extensions.actions.enable')}
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={dirty || operation === 'reload'}
                        onClick={() => void onPluginAction(plugin.manifest.plugin_id, 'reload')}
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
                          <p className="text-sm font-medium text-foreground">
                            {getPluginTranslation(
                              t,
                              plugin.manifest.plugin_id,
                              `contributions.${contribution.contribution_id}.display_name`,
                              contribution.display_name
                            )}
                          </p>
                        </div>
                        <p className="mt-2 text-xs text-muted-foreground">
                          {getPluginTranslation(
                            t,
                            plugin.manifest.plugin_id,
                            `contributions.${contribution.contribution_id}.description`,
                            contribution.description || contribution.contribution_id
                          )}
                        </p>
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
                      onChange={(key, value) => onFieldChange(plugin.manifest.plugin_id, key, value)}
                      disabled={!plugin.enabled}
                      pluginId={plugin.manifest.plugin_id}
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
        </div>
      )}
    </div>
  );
};

export default ExtensionsSection;
