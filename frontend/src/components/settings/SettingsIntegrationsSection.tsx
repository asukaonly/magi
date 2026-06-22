import type { Dispatch, SetStateAction } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import type { PluginPackageState } from '@/api/modules/plugins';
import ChannelsSection from '@/components/settings/ChannelsSection';
import PluginsSection from '@/components/settings/PluginsSection';
import { PluginMarketplace } from '@/components/settings/PluginMarketplace';
import type { PluginDraftMap } from '@/types/settings';

type SettingsIntegrationsSectionId = 'pluginsInstalled' | 'pluginsMarketplace' | 'channels';

interface SettingsIntegrationsSectionProps {
  section: SettingsIntegrationsSectionId;
  plugins: PluginPackageState[];
  pluginsLoading: boolean;
  draftPluginDrafts: PluginDraftMap;
  dirty: boolean;
  pluginProcessingIds: Record<string, string>;
  reloadingActionPlugins: Record<string, boolean>;
  channelsSelection: string | null;
  setChannelsSelection: Dispatch<SetStateAction<string | null>>;
  handlePluginDraftChange: (pluginId: string, key: string, value: unknown) => void;
  applyPersistedPluginSettings: (pluginId: string, updates: Record<string, unknown>) => void;
  handlePluginAction: (pluginId: string, action: 'enable' | 'disable' | 'reload') => Promise<void>;
  handleReloadActionPlugin: (pluginId: string) => Promise<void>;
  loadPlugins: (options?: { silent?: boolean }) => Promise<void>;
  loadPluginsAndSensors: () => Promise<void>;
  onBrowseMarketplace?: () => void;
}

export function SettingsIntegrationsSection({
  section,
  plugins,
  pluginsLoading,
  draftPluginDrafts,
  dirty,
  pluginProcessingIds,
  reloadingActionPlugins,
  channelsSelection,
  setChannelsSelection,
  handlePluginDraftChange,
  applyPersistedPluginSettings,
  handlePluginAction,
  handleReloadActionPlugin,
  loadPlugins,
  loadPluginsAndSensors,
  onBrowseMarketplace,
}: SettingsIntegrationsSectionProps) {
  const { t } = useTranslation('app');

  switch (section) {
    case 'pluginsInstalled':
      return (
        <PluginsSection
          plugins={plugins}
          loading={pluginsLoading}
          drafts={draftPluginDrafts}
          dirty={dirty}
          onFieldChange={handlePluginDraftChange}
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
          onInstallComplete={loadPluginsAndSensors}
        />
      );

    case 'channels':
      return (
        <ChannelsSection
          plugins={plugins}
          drafts={draftPluginDrafts}
          dirty={dirty}
          selectedContributionId={channelsSelection}
          onSelectContribution={setChannelsSelection}
          onFieldChange={handlePluginDraftChange}
          onSettingsActionUpdates={applyPersistedPluginSettings}
          onRefreshPlugins={() => loadPlugins({ silent: true })}
          onBrowseMarketplace={onBrowseMarketplace}
          onReloadPlugin={handleReloadActionPlugin}
          onPluginAction={handlePluginAction}
          reloading={reloadingActionPlugins}
        />
      );
  }
}

export type { SettingsIntegrationsSectionId };
