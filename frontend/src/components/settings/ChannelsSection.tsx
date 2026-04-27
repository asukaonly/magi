import React, { useCallback, useMemo, useState } from 'react';
import { CheckCircle2, Loader2, RefreshCw, XCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { configApi } from '@/api/modules/config';
import {
  type PluginContribution,
  type PluginPackageState,
} from '@/api/modules/plugins';
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

interface ChannelsSectionProps {
  plugins: PluginPackageState[];
  drafts: Record<string, Record<string, any>>;
  dirty?: boolean;
  selectedContributionId: string | null;
  onSelectContribution: (id: string | null) => void;
  onFieldChange: (pluginId: string, key: string, value: any) => void;
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

  // Telegram test connection state
  const [testState, setTestState] = useState<{
    loading: boolean;
    result?: { success: boolean; message: string };
  }>({ loading: false });

  const isTelegram = selectedEntry?.contribution.contribution_id?.toLowerCase().includes('telegram') ?? false;

  const handleTestConnection = useCallback(async () => {
    if (!selectedEntry) return;
    const pluginDrafts = drafts[selectedEntry.plugin.manifest.plugin_id] || {};
    const botToken = pluginDrafts.bot_token ?? '';
    const proxy = pluginDrafts.proxy ?? '';
    setTestState({ loading: true });
    try {
      const res = await configApi.testTelegramConnection({ bot_token: botToken, proxy });
      setTestState({ loading: false, result: { success: res.success, message: res.message } });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setTestState({ loading: false, result: { success: false, message: msg } });
    }
  }, [selectedEntry, drafts]);

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
          values={drafts[plugin.manifest.plugin_id] || {}}
          onChange={(key, value) => onFieldChange(plugin.manifest.plugin_id, key, value)}
          disabled={!plugin.enabled}
          pluginId={plugin.manifest.plugin_id}
        />
      ) : (
        <div className="border-b border-dashed border-[hsl(var(--settings-subnav-border)/0.72)] py-3 text-sm text-muted-foreground">
          {t('settings.actionsConfig.emptySettings')}
        </div>
      )}

      {isTelegram ? (
        <div className="flex items-center gap-3">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!(drafts[plugin.manifest.plugin_id]?.bot_token) || testState.loading}
            onClick={() => void handleTestConnection()}
            className="text-xs"
          >
            {testState.loading && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
            {t('settings.channels.testConnection')}
          </Button>
          {testState.result ? (
            <span className={`flex items-center gap-1 text-xs ${testState.result.success ? 'text-green-600' : 'text-destructive'}`}>
              {testState.result.success
                ? <CheckCircle2 className="h-3.5 w-3.5" />
                : <XCircle className="h-3.5 w-3.5" />}
              {testState.result.message}
            </span>
          ) : null}
        </div>
      ) : null}

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
