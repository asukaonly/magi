import type { PluginPackageState } from '@/api/modules/plugins';
import { PluginConnectionsPanel } from '@/components/plugins/PluginConnectionsPanel';
import { PluginPackageTrust } from '@/components/plugins/PluginPackageTrust';
import { PluginIcon } from '@/components/plugins/PluginIcon';
import { usePluginInstallPanelStore } from '@/stores/pluginInstallPanel';

export function InstalledSourceConnections({ plugins, onRefresh }: {
  plugins: PluginPackageState[];
  onRefresh: () => Promise<void>;
}) {
  const openPanel = usePluginInstallPanelStore(state => state.openPanel);
  return <div className="space-y-6">
    {plugins.map((plugin) => <section key={plugin.manifest.plugin_id}
      data-testid={`source-connections-${plugin.manifest.plugin_id}`} className="space-y-4">
      <div className="space-y-2">
        <div className="flex items-center gap-3">
          <PluginIcon iconId={plugin.manifest.icon} className="h-8 w-8" /><h3 className="text-lg font-semibold">{plugin.manifest.name}</h3>
        </div>
        <p className="text-sm text-muted-foreground">{plugin.manifest.description}</p>
      </div>
      {plugin.last_error ? <p role="alert" className="text-sm text-destructive">{plugin.last_error}</p> : null}
      <PluginPackageTrust plugin={plugin} onAuthorized={onRefresh} />
      <PluginConnectionsPanel pluginId={plugin.manifest.plugin_id} pluginName={plugin.manifest.name}
        onConnect={plugin.manifest.activation_flow ? () => openPanel(plugin.manifest.plugin_id, {
          pluginName: plugin.manifest.name, pluginIcon: plugin.manifest.icon, install: false,
          onDone: () => { void onRefresh(); },
        }) : undefined}
        fields={plugin.manifest.settings_fields} actions={plugin.manifest.settings_actions}
        blocks={plugin.manifest.settings_ui_blocks} canEnable={plugin.trusted}
        onChanged={() => { void onRefresh(); }} />
    </section>)}
  </div>;
}
