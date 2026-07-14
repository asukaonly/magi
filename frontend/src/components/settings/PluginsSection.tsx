import React, { useMemo } from 'react';
import { Blocks, CheckCircle2, RefreshCw, ShieldCheck, ShieldX, TriangleAlert } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import {
  type ExtensionFieldSpec,
  type PluginContribution,
  type PluginPackageState,
} from '@/api/modules/plugins';
import { PluginIcon } from '@/components/plugins/PluginIcon';
import PluginSettingsFields from '@/components/settings/PluginSettingsFields';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import {
  buildInstalledPluginDisplayItems,
  getInstalledItemDescription,
  getInstalledItemMemberNames,
  getInstalledItemName,
  type InstalledPluginDisplayItem,
} from '@/utils/plugin-display-groups';

type TFunction = (key: string) => string;

const pluginPillClass =
  'rounded-md border-transparent bg-[hsl(var(--settings-shell)/0.72)] px-2.5 py-1 text-xs font-semibold text-[hsl(var(--settings-nav-foreground))] shadow-[inset_0_0_0_1px_hsl(var(--settings-subnav-border)/0.34)]';

const activePillClass =
  'rounded-md border-transparent bg-primary px-2.5 py-1 text-xs font-semibold text-primary-foreground shadow-[0_8px_18px_hsl(var(--primary)/0.12)]';

const softAccentPillClass =
  'rounded-md border-transparent bg-[hsl(var(--primary)/0.12)] px-2.5 py-1 text-xs font-semibold text-primary shadow-[inset_0_0_0_1px_hsl(var(--primary)/0.2)]';

const collectSurfaceFields = (
  plugin: PluginPackageState,
  surface: ExtensionFieldSpec['surface']
): ExtensionFieldSpec[] =>
  plugin.contributions
    .flatMap((contribution) => contribution.fields)
    .filter((field) => field.surface === surface);

const collectContributionEntries = (
  item: InstalledPluginDisplayItem,
): Array<{ plugin: PluginPackageState; contribution: PluginContribution }> =>
  item.plugins.flatMap((plugin) =>
    plugin.contributions.map((contribution) => ({ plugin, contribution }))
  );

/**
 * Helper function to get plugin-specific translation with fallback.
 */
const getPluginTranslation = (
  t: TFunction,
  pluginId: string,
  key: string,
  fallback: string
): string => {
  const translationKey = `settings.plugins.${pluginId}.${key}`;
  const translated = t(translationKey);
  return translated === translationKey ? fallback : translated;
};

interface PluginsSectionProps {
  plugins: PluginPackageState[];
  loading?: boolean;
  drafts: Record<string, Record<string, any>>;
  dirty?: boolean;
  onFieldChange: (pluginId: string, key: string, value: any) => void;
  onRescan: () => Promise<void>;
  onPluginAction: (pluginId: string, action: 'enable' | 'disable' | 'reload') => Promise<void>;
  processingIds: Record<string, string>;
}

export const PluginsSection: React.FC<PluginsSectionProps> = ({
  plugins,
  loading = false,
  drafts,
  dirty = false,
  onFieldChange,
  onRescan,
  onPluginAction,
  processingIds,
}) => {
  const { t, i18n } = useTranslation('app');
  const language = i18n?.language ?? 'zh-CN';
  const displayItems = useMemo(() => buildInstalledPluginDisplayItems(plugins), [plugins]);
  const pluginCount = displayItems.length;

  const handleItemAction = async (
    item: InstalledPluginDisplayItem,
    action: 'enable' | 'disable' | 'reload',
  ) => {
    for (const plugin of item.plugins) {
      await onPluginAction(plugin.manifest.plugin_id, action);
    }
  };

  return (
    <div className="space-y-5 pt-1">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="rounded-md bg-[hsl(var(--settings-shell-elevated)/0.68)] px-3 py-1.5 text-xs font-semibold text-[hsl(var(--settings-nav-foreground))] shadow-[inset_0_0_0_1px_hsl(var(--settings-subnav-border)/0.34)]">
            {pluginCount === 1
              ? t('settings.pluginPackages.summaryOne', { count: pluginCount })
              : t('settings.pluginPackages.summary', { count: pluginCount })}
          </span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void onRescan()}
            disabled={dirty}
            className="h-9 bg-[hsl(var(--settings-shell-elevated)/0.72)] px-3.5 shadow-[inset_0_0_0_1px_hsl(var(--settings-subnav-border)/0.4)]"
          >
            <RefreshCw className="mr-2 h-4 w-4" />
            {t('settings.pluginPackages.actions.rescan')}
          </Button>
        </div>
      </div>

      {loading ? (
        <div className="border-t border-[hsl(var(--settings-subnav-border)/0.72)] pt-6">
          <div className="border-b border-dashed border-[hsl(var(--settings-subnav-border)/0.72)] py-8 text-center text-sm text-muted-foreground">
            {t('settings.pluginPackages.loading')}
          </div>
        </div>
      ) : (
        <div className="grid gap-3">
          {displayItems.map((item) => {
            const itemEnabled = item.plugins.some((plugin) => plugin.enabled);
            const allEnabled = item.plugins.every((plugin) => plugin.enabled);
            const itemHealthy = item.plugins.every((plugin) => plugin.healthy);
            const itemTrusted = item.plugins.every((plugin) => plugin.trusted);
            const operation = item.plugins
              .map((plugin) => processingIds[plugin.manifest.plugin_id])
              .find(Boolean);
            const contributionEntries = collectContributionEntries(item);
            const lastErrorPlugin = item.plugins.find((plugin) => plugin.last_error);
            const memberNames = getInstalledItemMemberNames(item, language);
            const itemName = item.group
              ? getInstalledItemName(item, language)
              : getPluginTranslation(t, item.primary.manifest.plugin_id, 'name', item.primary.manifest.name);
            const itemDescription = item.group
              ? getInstalledItemDescription(item, language)
              : getPluginTranslation(
                  t,
                  item.primary.manifest.plugin_id,
                  'description',
                  item.primary.manifest.description || t('settings.pluginPackages.emptyDescription')
                );

            return (
              <section
                key={item.id}
                className="space-y-4 rounded-lg bg-[hsl(var(--settings-shell-elevated)/0.5)] p-5 shadow-[inset_0_0_0_1px_hsl(var(--settings-subnav-border)/0.34),0_12px_30px_hsl(var(--foreground)/0.035)]"
                data-testid={`installed-plugin-${item.id}`}
              >
                <div className="space-y-4">
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div className="flex min-w-0 flex-1 gap-3">
                      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-[hsl(var(--settings-shell)/0.78)] shadow-[inset_0_0_0_1px_hsl(var(--settings-subnav-border)/0.38)]">
                        <PluginIcon
                          iconId={item.primary.manifest.icon}
                          className="h-5 w-5"
                        />
                      </div>
                      <div className="min-w-0 flex-1 space-y-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="text-[15px] font-semibold leading-6 text-foreground">
                            {itemName}
                          </h3>
                          <Badge variant={itemEnabled ? 'default' : 'secondary'} className={itemEnabled ? activePillClass : pluginPillClass}>
                            {itemEnabled ? t('settings.pluginPackages.status.enabled') : t('settings.pluginPackages.status.disabled')}
                          </Badge>
                          <Badge
                            variant={itemHealthy ? 'secondary' : 'destructive'}
                            className={itemHealthy ? pluginPillClass : 'rounded-md border-transparent px-2.5 py-1 text-xs font-semibold'}
                          >
                            {itemHealthy ? t('settings.pluginPackages.status.healthy') : t('settings.pluginPackages.status.unhealthy')}
                          </Badge>
                          {itemTrusted ? (
                            <Badge variant="secondary" className={cn(softAccentPillClass, 'gap-1')}>
                              <ShieldCheck className="h-3 w-3" />
                              {t('settings.pluginPackages.status.trusted')}
                            </Badge>
                          ) : (
                            <Badge variant="outline" className={cn(pluginPillClass, 'gap-1')}>
                              <ShieldX className="h-3 w-3" />
                              {t('settings.pluginPackages.status.untrusted')}
                            </Badge>
                          )}
                        </div>
                        <p className="max-w-4xl text-sm leading-6 text-muted-foreground">
                          {itemDescription}
                        </p>
                        <div className="flex flex-wrap gap-1.5">
                          <Badge variant="outline" className={pluginPillClass}>
                            {item.group
                              ? t('settings.pluginPackages.group.entryCount', { count: item.plugins.length })
                              : `${item.primary.manifest.source} · v${item.primary.manifest.version}`}
                          </Badge>
                          {memberNames.map((name) => (
                            <Badge key={name} variant="outline" className={pluginPillClass}>
                              {name}
                            </Badge>
                          ))}
                        </div>
                      </div>
                    </div>

                    <div className="flex shrink-0 flex-wrap gap-2">
                      <Button
                        type="button"
                        variant={allEnabled ? 'outline' : 'default'}
                        size="sm"
                        disabled={dirty || operation === 'enable' || operation === 'disable'}
                        onClick={() => void handleItemAction(item, allEnabled ? 'disable' : 'enable')}
                        className={cn('h-9 px-3.5', allEnabled && 'bg-[hsl(var(--settings-shell)/0.72)]')}
                      >
                        {allEnabled
                          ? t('settings.pluginPackages.actions.disable')
                          : t('settings.pluginPackages.actions.enable')}
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={dirty || operation === 'reload'}
                        onClick={() => void handleItemAction(item, 'reload')}
                        className="h-9 bg-[hsl(var(--settings-shell)/0.72)] px-3.5"
                      >
                        <RefreshCw className={operation === 'reload' ? 'mr-2 h-4 w-4 animate-spin' : 'mr-2 h-4 w-4'} />
                        {t('settings.pluginPackages.actions.reload')}
                      </Button>
                    </div>
                  </div>

                  <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                    {contributionEntries.map(({ plugin, contribution }) => (
                      <div
                        key={`${plugin.manifest.plugin_id}:${contribution.contribution_id}`}
                        className="rounded-lg bg-[hsl(var(--settings-shell)/0.58)] p-3.5 shadow-[inset_0_0_0_1px_hsl(var(--settings-subnav-border)/0.3)]"
                      >
                        <div className="flex items-center gap-2">
                          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-[hsl(var(--primary)/0.1)] text-primary">
                            <Blocks className="h-3.5 w-3.5" />
                          </span>
                          <p className="min-w-0 truncate text-sm font-semibold text-foreground">
                            {getPluginTranslation(
                              t,
                              plugin.manifest.plugin_id,
                              `contributions.${contribution.contribution_id}.display_name`,
                              contribution.display_name
                            )}
                          </p>
                        </div>
                        <p className="mt-2 line-clamp-3 text-xs leading-5 text-muted-foreground">
                          {getPluginTranslation(
                            t,
                            plugin.manifest.plugin_id,
                            `contributions.${contribution.contribution_id}.description`,
                            contribution.description || contribution.contribution_id
                          )}
                        </p>
                        <div className="mt-3 flex flex-wrap gap-2">
                          <Badge variant="outline" className={pluginPillClass}>{contribution.contribution_type}</Badge>
                          <Badge variant="secondary" className={pluginPillClass}>{contribution.surface}</Badge>
                        </div>
                      </div>
                    ))}
                  </div>

                  {lastErrorPlugin?.last_error ? (
                    <div className="rounded-lg bg-[hsl(var(--destructive)/0.08)] p-3.5 text-sm text-destructive shadow-[inset_0_0_0_1px_hsl(var(--destructive)/0.18)]">
                      <div className="flex items-center gap-2 font-medium">
                        <TriangleAlert className="h-4 w-4" />
                        {t('settings.pluginPackages.status.lastError')}
                      </div>
                      <p className="mt-2">{lastErrorPlugin.last_error}</p>
                    </div>
                  ) : null}

                  {item.plugins.some((plugin) => collectSurfaceFields(plugin, 'extensions').length > 0) ? (
                    <div className="space-y-4">
                      {item.plugins.map((plugin) => {
                        const pluginPackageFields = collectSurfaceFields(plugin, 'extensions');
                        if (pluginPackageFields.length === 0) return null;
                        return (
                          <PluginSettingsFields
                            key={plugin.manifest.plugin_id}
                            fields={pluginPackageFields}
                            values={drafts[plugin.manifest.plugin_id] || {}}
                            onChange={(key, value) => onFieldChange(plugin.manifest.plugin_id, key, value)}
                            disabled={!plugin.enabled}
                            pluginId={plugin.manifest.plugin_id}
                          />
                        );
                      })}
                    </div>
                  ) : (
                    <div className="rounded-lg bg-[hsl(var(--settings-shell)/0.5)] p-3 text-sm text-muted-foreground shadow-[inset_0_0_0_1px_hsl(var(--settings-subnav-border)/0.26)]">
                      <div className="flex items-center gap-2">
                        <CheckCircle2 className="h-4 w-4 text-primary" />
                        {t('settings.pluginPackages.emptySettings')}
                      </div>
                    </div>
                  )}
                </div>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default PluginsSection;
