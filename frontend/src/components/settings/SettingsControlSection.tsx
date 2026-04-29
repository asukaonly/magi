import { useTranslation } from 'react-i18next';

import type { ControlSettingsDTO } from '@/api/modules/control';
import { ControlSettingsPanel } from '@/components/control';
import { SettingsGroup, SettingsSectionShell } from '@/components/settings/SettingsSectionPrimitives';

interface SettingsControlSectionProps {
  draftControlSettings: ControlSettingsDTO | null;
  patchDraftControlSettings: (updater: (draft: ControlSettingsDTO) => void) => void;
}

export function SettingsControlSection({
  draftControlSettings,
  patchDraftControlSettings,
}: SettingsControlSectionProps) {
  const { t } = useTranslation('app');

  return (
    <SettingsSectionShell>
      <SettingsGroup
        title={t('settings.control.title')}
        description={t('settings.control.description')}
      >
        {draftControlSettings ? (
          <ControlSettingsPanel
            value={draftControlSettings}
            onChange={(next) => patchDraftControlSettings((draft) => {
              draft.permission_mode = next.permission_mode;
              draft.plan_approval_required = next.plan_approval_required;
            })}
          />
        ) : null}
      </SettingsGroup>
    </SettingsSectionShell>
  );
}