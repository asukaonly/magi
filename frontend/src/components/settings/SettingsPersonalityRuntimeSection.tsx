import { useTranslation } from 'react-i18next';

import type { SystemConfig } from '@/api/modules/config';
import { SettingsGroup, SettingsSectionShell } from '@/components/settings/SettingsSectionPrimitives';
import { Switch } from '@/components/ui/switch';

interface SettingsPersonalityRuntimeSectionProps {
  draftConfig: SystemConfig;
  patchDraftConfig: (updater: (draft: SystemConfig) => void) => void;
}

export function SettingsPersonalityRuntimeSection({
  draftConfig,
  patchDraftConfig,
}: SettingsPersonalityRuntimeSectionProps) {
  const { t } = useTranslation('app');

  const handleStateMemoryToggle = (checked: boolean) => {
    patchDraftConfig((draft) => {
      draft.personalitySettings.state_memory_enabled = checked;
      if (!checked) {
        draft.personalitySettings.state_transition_enabled = false;
        draft.personalitySettings.deep_persona_enabled = false;
      }
    });
  };

  const handleStateTransitionToggle = (checked: boolean) => {
    patchDraftConfig((draft) => {
      if (checked) {
        draft.personalitySettings.state_memory_enabled = true;
      }
      draft.personalitySettings.state_transition_enabled = checked;
    });
  };

  const handleDeepPersonaToggle = (checked: boolean) => {
    patchDraftConfig((draft) => {
      if (checked) {
        draft.personalitySettings.state_memory_enabled = true;
      }
      draft.personalitySettings.deep_persona_enabled = checked;
    });
  };

  return (
    <SettingsSectionShell>
      <SettingsGroup
        title={t('settings.personalitySettings.runtimeTitle')}
        description={t('settings.personalitySettings.runtimeDesc')}
      >
        <div className="rounded-[1.25rem] border border-[hsl(var(--settings-subnav-border)/0.62)] bg-[hsl(var(--settings-shell-elevated)/0.42)] px-4 py-3 text-[13px] leading-6 text-[hsl(var(--foreground)/0.72)]">
          {t('settings.personalitySettings.requestNotice')}
        </div>

        <div className="space-y-3">
          <div className="flex items-start justify-between gap-4 border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3">
            <div className="space-y-1">
              <div className="text-sm font-medium text-foreground">{t('settings.personalitySettings.stateMemoryLabel')}</div>
              <div className="text-xs leading-6 text-muted-foreground">{t('settings.personalitySettings.stateMemoryDesc')}</div>
            </div>
            <Switch
              aria-label={t('settings.personalitySettings.stateMemoryLabel')}
              checked={draftConfig.personalitySettings.state_memory_enabled}
              onCheckedChange={handleStateMemoryToggle}
            />
          </div>

          <div className="flex items-start justify-between gap-4 border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3">
            <div className="space-y-1">
              <div className="text-sm font-medium text-foreground">{t('settings.personalitySettings.stateTransitionLabel')}</div>
              <div className="text-xs leading-6 text-muted-foreground">{t('settings.personalitySettings.stateTransitionDesc')}</div>
            </div>
            <Switch
              aria-label={t('settings.personalitySettings.stateTransitionLabel')}
              checked={draftConfig.personalitySettings.state_transition_enabled}
              onCheckedChange={handleStateTransitionToggle}
            />
          </div>

          <div className="flex items-start justify-between gap-4 py-3">
            <div className="space-y-1">
              <div className="text-sm font-medium text-foreground">{t('settings.personalitySettings.deepPersonaLabel')}</div>
              <div className="text-xs leading-6 text-muted-foreground">{t('settings.personalitySettings.deepPersonaDesc')}</div>
            </div>
            <Switch
              aria-label={t('settings.personalitySettings.deepPersonaLabel')}
              checked={draftConfig.personalitySettings.deep_persona_enabled}
              onCheckedChange={handleDeepPersonaToggle}
            />
          </div>
        </div>
      </SettingsGroup>
    </SettingsSectionShell>
  );
}