import { CenterAccessPanel } from '@/components/connections/CenterAccessPanel';
import { ConnectionPicker } from '@/components/connections/ConnectionPicker';
import { BackgroundDeliveryPanel } from '@/components/connections/BackgroundDeliveryPanel';
import { SettingsSectionShell } from '@/components/settings/SettingsSectionPrimitives';

export function SettingsConnectionsSection({
  hasUnsavedSettings,
}: {
  hasUnsavedSettings: boolean;
}) {
  return (
    <SettingsSectionShell className="space-y-8">
      <ConnectionPicker hasUnsavedSettings={hasUnsavedSettings} />
      <BackgroundDeliveryPanel />
      <CenterAccessPanel />
    </SettingsSectionShell>
  );
}
