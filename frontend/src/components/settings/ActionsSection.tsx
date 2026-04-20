import React, { useMemo } from 'react';
import { RefreshCw, ShieldAlert, Sparkles } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import {
  type PluginContribution,
  type PluginPackageState,
} from '@/api/modules/plugins';
import PluginSettingsFields from '@/components/settings/PluginSettingsFields';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';

type ActionContributionEntry = {
  plugin: PluginPackageState;
  contribution: PluginContribution;
};

const listActionEntries = (plugins: PluginPackageState[]): ActionContributionEntry[] =>
  plugins.flatMap((plugin) =>
    plugin.contributions
      .filter((contribution) => contribution.contribution_type === 'action' || contribution.surface === 'actions')
      .map((contribution) => ({ plugin, contribution }))
  );

interface ActionsSectionProps {
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

export const ActionsSection: React.FC<ActionsSectionProps> = ({
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
  const actionEntries = useMemo(() => listActionEntries(plugins), [plugins]);

  const selectedEntry = useMemo(
    () => actionEntries.find((e) => e.contribution.contribution_id === selectedContributionId) ?? null,
    [actionEntries, selectedContributionId]
  );

  // Overview mode
  if (!selectedEntry) {
    return (
      <div className="space-y-6">
        <p className="text-sm leading-6 text-muted-foreground">
          {t('settings.actionsDesc')}
        </p>

        {actionEntries.length === 0 ? (
          <div className="border-b border-dashed border-[hsl(var(--settings-subnav-border)/0.72)] py-8 text-center text-sm text-muted-foreground">
            {t('settings.actionsConfig.emptyState')}
          </div>
        ) : (
          <div>
            {actionEntries.map(({ plugin, contribution }) => (
              <button
                key={contribution.contribution_id}
                type="button"
                onClick={() => onSelectContribution(contribution.contribution_id)}
                className="grid w-full gap-3 border-b border-[hsl(var(--settings-subnav-border)/0.6)] px-0 py-4 text-left transition-colors last:border-b-0 hover:bg-transparent sm:grid-cols-[minmax(0,1.2fr)_auto_auto]"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-3">
                    <span className="truncate text-sm font-medium text-foreground">{contribution.display_name}</span>
                    {contribution.metadata.dangerous ? (
                      <ShieldAlert className="h-3.5 w-3.5 text-destructive" />
                    ) : null}
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
              {plugin.enabled ? t('settings.extensions.status.enabled') : t('settings.extensions.status.disabled')}
            </Badge>
            {contribution.metadata.tool_adapter_name ? (
              <Badge variant="secondary">
                <Sparkles className="mr-1 h-3 w-3" />
                {contribution.metadata.tool_adapter_name}
              </Badge>
            ) : null}
            {contribution.metadata.dangerous ? (
              <Badge variant="destructive">
                <ShieldAlert className="mr-1 h-3 w-3" />
                {t('settings.actionsConfig.status.dangerous')}
              </Badge>
            ) : null}
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

      {Array.isArray(contribution.metadata.required_permissions) && contribution.metadata.required_permissions.length > 0 ? (
        <div className="flex flex-wrap gap-2 border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3">
          {contribution.metadata.required_permissions.map((permission: string) => (
            <Badge key={permission} variant="outline">
              {permission}
            </Badge>
          ))}
        </div>
      ) : null}

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
  );
};

export default ActionsSection;
