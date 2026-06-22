import React, { useEffect, useMemo, useState } from 'react';
import { Activity, AlertCircle, Radio, RefreshCw } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import {
  pluginsApi,
  type PluginChannelStatusData,
  type PluginContribution,
  type PluginPackageState,
  type PluginSettingsActionSpec,
} from '@/api/modules/plugins';
import PluginSettingsActions from '@/components/settings/PluginSettingsActions';
import PluginSettingsFields from '@/components/settings/PluginSettingsFields';
import { SettingsEmptyState } from '@/components/settings/SettingsSectionPrimitives';
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

const formatStatusTime = (value: unknown): string => {
  const millis = Number(value || 0);
  if (!Number.isFinite(millis) || millis <= 0) {
    return '';
  }
  return new Date(millis).toLocaleString();
};

const ChannelStatusPanel: React.FC<{ pluginId: string; enabled: boolean }> = ({ pluginId, enabled }) => {
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
        const payload = await pluginsApi.getSettingsResource(pluginId, 'channel_status');
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
  }, [enabled, pluginId]);

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
  drafts: Record<string, Record<string, any>>;
  dirty?: boolean;
  selectedContributionId: string | null;
  onSelectContribution: (id: string | null) => void;
  onFieldChange: (pluginId: string, key: string, value: any) => void;
  onSettingsActionUpdates: (pluginId: string, updates: Record<string, unknown>) => void;
  onRefreshPlugins: () => Promise<void>;
  onBrowseMarketplace?: () => void;
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
  onBrowseMarketplace,
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

      <ChannelStatusPanel pluginId={plugin.manifest.plugin_id} enabled={plugin.enabled} />

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
