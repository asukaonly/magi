import React, { useMemo } from 'react';
import { Mail, RefreshCw, ShieldAlert, Sparkles } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import {
  type PluginContribution,
  type PluginPackageState,
} from '@/api/modules/plugins';
import PluginSettingsFields from '@/components/settings/PluginSettingsFields';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

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
  onFieldChange: (pluginId: string, key: string, value: any) => void;
  onReloadPlugin: (pluginId: string) => Promise<void>;
  reloading: Record<string, boolean>;
}

export const ActionsSection: React.FC<ActionsSectionProps> = ({
  plugins,
  drafts,
  dirty = false,
  onFieldChange,
  onReloadPlugin,
  reloading,
}) => {
  const { t } = useTranslation('app');
  const actionEntries = useMemo(() => listActionEntries(plugins), [plugins]);

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-lg font-semibold">{t('settings.tabs.actions')}</h2>
        <p className="text-sm leading-6 text-muted-foreground">{t('settings.actionsDesc')}</p>
      </div>

      <div className="grid gap-4">
        {actionEntries.map(({ plugin, contribution }) => (
          <section
            key={contribution.contribution_id}
            className="space-y-5 border-t border-[hsl(var(--settings-subnav-border)/0.72)] pt-6"
          >
            <div className="space-y-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                    <Mail className="h-4 w-4 text-primary" />
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
                </div>
              </div>

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

        {actionEntries.length === 0 ? (
          <div className="border-t border-[hsl(var(--settings-subnav-border)/0.72)] pt-6">
            <div className="border-b border-dashed border-[hsl(var(--settings-subnav-border)/0.72)] py-8 text-center text-sm text-muted-foreground">
              {t('settings.actionsConfig.emptyState')}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
};

export default ActionsSection;
