import { CenterAccessPanel } from '@/components/connections/CenterAccessPanel';
import { ConnectionPicker } from '@/components/connections/ConnectionPicker';
import { BackgroundDeliveryPanel } from '@/components/connections/BackgroundDeliveryPanel';
import { useTranslation } from 'react-i18next';
import { SettingsGroup, SettingsSectionShell } from '@/components/settings/SettingsSectionPrimitives';
import { ClientResetAction } from '@/components/connections/ClientResetAction';

export function SettingsConnectionsSection({
  hasUnsavedSettings,
}: {
  hasUnsavedSettings: boolean;
}) {
  const { t } = useTranslation('app');
  return (
    <SettingsSectionShell className="space-y-8">
      <ConnectionPicker hasUnsavedSettings={hasUnsavedSettings} />
      <BackgroundDeliveryPanel />
      <CenterAccessPanel />
      <SettingsGroup title={t('clientReset.title')} description={t('clientReset.description')}>
        <ClientResetAction />
      </SettingsGroup>
    </SettingsSectionShell>
  );
}
