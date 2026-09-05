import React, { useEffect, useMemo, useState } from 'react';
import { Activity, AlertCircle, Radio } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import {
  pluginsApi,
  type PluginChannelStatusData,
  type PluginContribution,
  type PluginPackageState,
} from '@/api/modules/plugins';
import { PluginConnectionsPanel } from '@/components/plugins/PluginConnectionsPanel';
import { SettingsEmptyState } from '@/components/settings/SettingsSectionPrimitives';
import { Badge } from '@/components/ui/badge';

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

const formatStatusTime = (value: unknown): string => {
  const millis = Number(value || 0);
  if (!Number.isFinite(millis) || millis <= 0) {
    return '';
  }
  return new Date(millis).toLocaleString();
};

const ChannelStatusPanel: React.FC<{ connectionId: string; enabled: boolean }> = ({ connectionId, enabled }) => {
  const { t } = useTranslation('app');
  const [status, setStatus] = useState<PluginChannelStatusData | null>(null);
  const [available, setAvailable] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const loadStatus = async () => {
      if (!enabled) {
        setStatus(null);
        setAvailable(false);
        return;
      }
      try {
        const payload = await pluginsApi.getSettingsResource(connectionId, 'channel_status');
        if (cancelled) {
          return;
        }
        setStatus((payload.data || {}) as PluginChannelStatusData);
        setAvailable(true);
      } catch {
        if (!cancelled) {
          setStatus(null);
          setAvailable(false);
        }
      }
    };

    void loadStatus();
    const timer = window.setInterval(() => void loadStatus(), 5000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [enabled, connectionId]);

  if (!available || !status) {
    return null;
  }

  const state = String(status.state || (status.running ? 'running' : 'stopped'));
  const healthy = state === 'running' && !status.last_error;
  const items = [
    [t('settings.channelStatus.account'), status.account_id || ''],
    [t('settings.channelStatus.lastPoll'), formatStatusTime(status.last_poll_at_ms)],
    [t('settings.channelStatus.lastInbound'), formatStatusTime(status.last_inbound_at_ms)],
    [t('settings.channelStatus.lastOutbound'), formatStatusTime(status.last_outbound_at_ms)],
  ].filter(([, value]) => Boolean(value));

  return (
    <div className="space-y-3 border-y border-[hsl(var(--settings-subnav-border)/0.6)] py-4">
      <div className="flex flex-wrap items-center gap-2">
        {healthy ? <Activity className="h-4 w-4 text-emerald-600" /> : <AlertCircle className="h-4 w-4 text-amber-600" />}
        <span className="text-sm font-medium text-foreground">{t('settings.channelStatus.title')}</span>
        <Badge variant={healthy ? 'default' : 'secondary'} className="rounded-md">
          {t(`settings.channelStatus.states.${state}`, { defaultValue: state })}
        </Badge>
      </div>
      {items.length > 0 ? (
        <div className="grid gap-2 text-xs text-muted-foreground sm:grid-cols-2">
          {items.map(([label, value]) => (
            <div key={label} className="min-w-0">
              <span className="font-medium text-foreground/80">{label}: </span>
              <span className="break-words">{value}</span>
            </div>
          ))}
        </div>
      ) : null}
      {status.last_error ? <p className="text-xs text-destructive">{status.last_error}</p> : null}
    </div>
  );
};

interface ChannelsSectionProps {
  plugins: PluginPackageState[];
  selectedContributionId: string | null;
  onSelectContribution: (id: string | null) => void;
  onRefreshPlugins: () => Promise<void>;
  onBrowseMarketplace?: () => void;
}

export const ChannelsSection: React.FC<ChannelsSectionProps> = ({
  plugins,
  selectedContributionId,
  onSelectContribution,
  onRefreshPlugins,
  onBrowseMarketplace,
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
        {channelEntries.length === 0 ? (
          <SettingsEmptyState
            testId="settings-empty-state-channels"
            icon={Radio}
            title={t('settings.channelsConfig.emptyTitle')}
            description={t('settings.channelsConfig.emptyDescription')}
            actionLabel={t('settings.channelsConfig.emptyAction')}
            onAction={onBrowseMarketplace}
          />
        ) : (
          <div className="space-y-6">
            <p className="text-sm leading-6 text-muted-foreground">
              {t('settings.channelsDesc')}
            </p>
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
        <h3 className="text-sm font-semibold">{plugin.manifest.name}</h3>
        <p className="max-w-3xl text-sm leading-6 text-muted-foreground">
          {contribution.description || contribution.contribution_id}
        </p>
      </header>

      <PluginConnectionsPanel
        pluginId={plugin.manifest.plugin_id}
        fields={plugin.manifest.settings_fields}
        actions={plugin.manifest.settings_actions}
        blocks={plugin.manifest.settings_ui_blocks}
        canEnable={plugin.trusted}
        onChanged={() => void onRefreshPlugins()}
        renderConnection={(connection) => <ChannelStatusPanel key={connection.connection_id}
          connectionId={connection.connection_id} enabled={connection.enabled} />}
      />
    </div>
  );
};

export default ChannelsSection;
