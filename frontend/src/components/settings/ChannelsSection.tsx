import React, { useMemo } from 'react';
import { RefreshCw } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import {
  type PluginContribution,
  type PluginPackageState,
  type PluginSettingsActionSpec,
} from '@/api/modules/plugins';
import PluginSettingsActions from '@/components/settings/PluginSettingsActions';
import PluginSettingsFields from '@/components/settings/PluginSettingsFields';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';

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

const getContributionSettingsActions = (contribution: PluginContribution): PluginSettingsActionSpec[] => {
  const actions = contribution.metadata?.settings_actions;
  return Array.isArray(actions) ? (actions as PluginSettingsActionSpec[]) : [];
};

interface ChannelsSectionProps {
  plugins: PluginPackageState[];
  drafts: Record<string, Record<string, any>>;
  dirty?: boolean;
  selectedContributionId: string | null;
  onSelectContribution: (id: string | null) => void;
  onFieldChange: (pluginId: string, key: string, value: any) => void;
  onSettingsActionUpdates: (pluginId: string, updates: Record<string, unknown>) => void;
  onRefreshPlugins: () => Promise<void>;
  onReloadPlugin: (pluginId: string) => Promise<void>;
  onPluginAction: (pluginId: string, action: 'enable' | 'disable' | 'reload') => Promise<void>;
  reloading: Record<string, boolean>;
}

export const ChannelsSection: React.FC<ChannelsSectionProps> = ({
  plugins,
  drafts,
  dirty = false,
  selectedContributionId,
  onSelectContribution,
  onFieldChange,
  onSettingsActionUpdates,
  onRefreshPlugins,
  onReloadPlugin,
  onPluginAction,
  reloading,
}) => {
  const { t } = useTranslation('app');
  const channelEntries = useMemo(() => listChannelEntries(plugins), [plugins]);

  const selectedEntry = useMemo(
    () => channelEntries.find((e) => e.contribution.contribution_id === selectedContributionId) ?? null,
    [channelEntries, selectedContributionId]
  );

  // Overview mode
  if (!selectedEntry) {
    return (
      <div className="space-y-6">
        <p className="text-sm leading-6 text-muted-foreground">
          {t('settings.channelsDesc')}
        </p>

        {channelEntries.length === 0 ? (
          <div className="border-b border-dashed border-[hsl(var(--settings-subnav-border)/0.72)] py-8 text-center text-sm text-muted-foreground">
            {t('settings.channelsConfig.emptyState')}
          </div>
        ) : (
          <div>
            {channelEntries.map(({ plugin, contribution }) => (
              <button
                key={contribution.contribution_id}
                type="button"
                onClick={() => onSelectContribution(contribution.contribution_id)}
                className="grid w-full gap-3 border-b border-[hsl(var(--settings-subnav-border)/0.6)] px-0 py-4 text-left transition-colors last:border-b-0 hover:bg-transparent sm:grid-cols-[minmax(0,1.2fr)_auto_auto]"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-3">
                    <span className="truncate text-sm font-medium text-foreground">{contribution.display_name}</span>
                  </div>
                  <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">
                    {contribution.description || contribution.contribution_id}
                  </p>
                </div>
                <div className="text-xs text-muted-foreground sm:text-right">
                  <Badge variant="outline">{plugin.manifest.name}</Badge>
                </div>
                <div className="sm:justify-self-end">
                  <Badge variant={plugin.enabled ? 'default' : 'secondary'} className="rounded-md">
                    {plugin.enabled ? 'ON' : 'OFF'}
                  </Badge>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    );
  }

  // Detail mode
  const { plugin, contribution } = selectedEntry;
  const settingsActions = getContributionSettingsActions(contribution);
  const pluginValues = drafts[plugin.manifest.plugin_id] || {};

  return (
    <div className="space-y-8">
      <header className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={plugin.enabled ? 'default' : 'secondary'} className="rounded-md">
              {plugin.enabled ? t('settings.pluginPackages.status.enabled') : t('settings.pluginPackages.status.disabled')}
            </Badge>
            <span className="text-xs uppercase tracking-[0.16em] text-muted-foreground">{plugin.manifest.plugin_id}</span>
          </div>
          <div className="flex items-center gap-3">
            <Switch
              checked={plugin.enabled}
              onCheckedChange={(checked) => void onPluginAction(plugin.manifest.plugin_id, checked ? 'enable' : 'disable')}
            />
          </div>
        </div>
        <p className="max-w-3xl text-sm leading-6 text-muted-foreground">
          {contribution.description || contribution.contribution_id}
        </p>
      </header>

      {contribution.fields.length > 0 ? (
        <PluginSettingsFields
          fields={contribution.fields}
          values={pluginValues}
          onChange={(key, value) => onFieldChange(plugin.manifest.plugin_id, key, value)}
          disabled={!plugin.enabled}
          pluginId={plugin.manifest.plugin_id}
        />
      ) : (
        <div className="border-b border-dashed border-[hsl(var(--settings-subnav-border)/0.72)] py-3 text-sm text-muted-foreground">
          {t('settings.actionsConfig.emptySettings')}
        </div>
      )}

      <PluginSettingsActions
        pluginId={plugin.manifest.plugin_id}
        actions={settingsActions}
        values={pluginValues}
        disabled={!plugin.enabled}
        onSettingsUpdates={onSettingsActionUpdates}
        onActionSettled={onRefreshPlugins}
      />

      <div className="flex justify-end">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={dirty || !!reloading[plugin.manifest.plugin_id]}
          onClick={() => void onReloadPlugin(plugin.manifest.plugin_id)}
        >
          <RefreshCw className={reloading[plugin.manifest.plugin_id] ? 'mr-2 h-4 w-4 animate-spin' : 'mr-2 h-4 w-4'} />
          {t('settings.pluginPackages.actions.reload')}
        </Button>
      </div>
    </div>
  );
};

export default ChannelsSection;
