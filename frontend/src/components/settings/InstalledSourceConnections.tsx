import { useTranslation } from 'react-i18next';
import type { PluginPackageState } from '@/api/modules/plugins';
import { PluginConnectionsPanel } from '@/components/plugins/PluginConnectionsPanel';
import { PluginPackageTrust } from '@/components/plugins/PluginPackageTrust';
import { Badge } from '@/components/ui/badge';

export function InstalledSourceConnections({ plugins, onRefresh }: {
  plugins: PluginPackageState[];
  onRefresh: () => Promise<void>;
}) {
  const { t } = useTranslation('app');
  return <div className="space-y-6">
    {plugins.map((plugin) => <section key={plugin.manifest.plugin_id}
      data-testid={`source-connections-${plugin.manifest.plugin_id}`} className="space-y-4">
      <div className="space-y-2">
        <div className="flex items-center gap-3">
          <h3 className="text-lg font-semibold">{plugin.manifest.name}</h3>
          <Badge variant="secondary">{t('settings.marketplace.badge.installed')}</Badge>
        </div>
        <p className="text-sm text-muted-foreground">{plugin.manifest.description}</p>
        <p className="text-sm text-muted-foreground">{t('settings.timeline.workspace.connectionSetup')}</p>
      </div>
      {plugin.last_error ? <p role="alert" className="text-sm text-destructive">{plugin.last_error}</p> : null}
      <PluginPackageTrust plugin={plugin} onAuthorized={onRefresh} />
      <PluginConnectionsPanel pluginId={plugin.manifest.plugin_id}
        fields={plugin.manifest.settings_fields} actions={plugin.manifest.settings_actions}
        blocks={plugin.manifest.settings_ui_blocks} canEnable={plugin.trusted}
        onChanged={() => { void onRefresh(); }} />
    </section>)}
  </div>;
}
