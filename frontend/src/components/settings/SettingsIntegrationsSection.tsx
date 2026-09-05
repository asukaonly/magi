import type { Dispatch, SetStateAction } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import type { PluginPackageState } from '@/api/modules/plugins';
import ChannelsSection from '@/components/settings/ChannelsSection';
import PluginsSection from '@/components/settings/PluginsSection';
import { PluginMarketplace } from '@/components/settings/PluginMarketplace';

type SettingsIntegrationsSectionId = 'pluginsInstalled' | 'pluginsMarketplace' | 'channels';

interface SettingsIntegrationsSectionProps {
  section: SettingsIntegrationsSectionId;
  plugins: PluginPackageState[];
  pluginsLoading: boolean;
  dirty: boolean;
  pluginProcessingIds: Record<string, string>;
  channelsSelection: string | null;
  setChannelsSelection: Dispatch<SetStateAction<string | null>>;
  handlePluginAction: (pluginId: string, action: 'reload') => Promise<void>;
  loadPlugins: (options?: { silent?: boolean }) => Promise<void>;
  loadPluginsAndSources: () => Promise<void>;
  onBrowseMarketplace?: () => void;
}

export function SettingsIntegrationsSection({
  section,
  plugins,
  pluginsLoading,
  dirty,
  pluginProcessingIds,
  channelsSelection,
  setChannelsSelection,
  handlePluginAction,
  loadPlugins,
  loadPluginsAndSources,
  onBrowseMarketplace,
}: SettingsIntegrationsSectionProps) {
  const { t } = useTranslation('app');

  switch (section) {
    case 'pluginsInstalled':
      return (
        <PluginsSection
          plugins={plugins}
          loading={pluginsLoading}
          dirty={dirty}
          onRescan={async () => {
            await loadPlugins();
            toast.success(t('settings.pluginPackages.feedback.rescanSuccess'));
          }}
          onPluginAction={handlePluginAction}
          processingIds={pluginProcessingIds}
        />
      );

    case 'pluginsMarketplace':
      return (
        <PluginMarketplace
          installedPlugins={plugins}
          onInstallComplete={loadPluginsAndSources}
        />
      );

    case 'channels':
      return (
        <ChannelsSection
          plugins={plugins}
          selectedContributionId={channelsSelection}
          onSelectContribution={setChannelsSelection}
          onRefreshPlugins={() => loadPlugins({ silent: true })}
          onBrowseMarketplace={onBrowseMarketplace}
        />
      );
  }
}

export type { SettingsIntegrationsSectionId };
