import React, { useMemo } from 'react';
import { Radio, RefreshCw } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import {
  type PluginContribution,
  type PluginPackageState,
} from '@/api/modules/plugins';
import PluginSettingsFields from '@/components/settings/PluginSettingsFields';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

type ChannelContributionEntry = {
  plugin: PluginPackageState;
  contribution: PluginContribution;
};

const listChannelEntries = (plugins: PluginPackageState[]): ChannelContributionEntry[] =>
  plugins.flatMap((plugin) =>
    plugin.contributions
      .filter((c) => c.contribution_type === 'channel')
      .map((contribution) => ({ plugin, contribution }))
  );

interface ChannelsSectionProps {
  plugins: PluginPackageState[];
  drafts: Record<string, Record<string, any>>;
  dirty?: boolean;
  onFieldChange: (pluginId: string, key: string, value: any) => void;
  onReloadPlugin: (pluginId: string) => Promise<void>;
  reloading: Record<string, boolean>;
}

export const ChannelsSection: React.FC<ChannelsSectionProps> = ({
  plugins,
  drafts,
  dirty = false,
  onFieldChange,
  onReloadPlugin,
  reloading,
}) => {
  const { t } = useTranslation('app');
  const channelEntries = useMemo(() => listChannelEntries(plugins), [plugins]);

  return (
    <div className="space-y-8">
      <p className="text-sm leading-6 text-muted-foreground">
        {t('settings.channelsDesc')}
      </p>

      <div className="grid gap-4">
        {channelEntries.map(({ plugin, contribution }) => (
          <section
            key={contribution.contribution_id}
            className="space-y-5 pt-4"
          >
            <div className="space-y-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                    <Radio className="h-4 w-4 text-primary" />
                    {contribution.display_name}
                  </div>
                  <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
                    {contribution.description || contribution.contribution_id}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={plugin.enabled ? 'default' : 'secondary'}>
                    {plugin.enabled ? t('settings.extensions.status.enabled') : t('settings.extensions.status.disabled')}
                  </Badge>
                  <Badge variant="outline">{plugin.manifest.name}</Badge>
                </div>
              </div>

              {contribution.fields.length > 0 ? (
                <PluginSettingsFields
                  fields={contribution.fields}
                  values={drafts[plugin.manifest.plugin_id] || {}}
                  onChange={(key, value) => onFieldChange(plugin.manifest.plugin_id, key, value)}
                  disabled={!plugin.enabled}
                />
              ) : (
                <div className="border-b border-dashed border-[hsl(var(--settings-subnav-border)/0.72)] py-3 text-sm text-muted-foreground">
                  {t('settings.actionsConfig.emptySettings')}
                </div>
              )}

              <div className="flex justify-end">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={dirty || !!reloading[plugin.manifest.plugin_id]}
                  onClick={() => void onReloadPlugin(plugin.manifest.plugin_id)}
                >
                  <RefreshCw className={reloading[plugin.manifest.plugin_id] ? 'mr-2 h-4 w-4 animate-spin' : 'mr-2 h-4 w-4'} />
                  {t('settings.extensions.actions.reload')}
                </Button>
              </div>
            </div>
          </section>
        ))}

        {channelEntries.length === 0 ? (
          <div className="border-t border-[hsl(var(--settings-subnav-border)/0.72)] pt-6">
            <div className="border-b border-dashed border-[hsl(var(--settings-subnav-border)/0.72)] py-8 text-center text-sm text-muted-foreground">
              {t('settings.channelsConfig.emptyState')}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
};

export default ChannelsSection;
