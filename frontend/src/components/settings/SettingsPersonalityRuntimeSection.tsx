import { useTranslation } from 'react-i18next';

import type { SystemConfig } from '@/api/modules/config';
import { SettingsGroup, SettingsSectionShell } from '@/components/settings/SettingsSectionPrimitives';
import { Switch } from '@/components/ui/switch';
import { Input } from '@/components/ui/input';
import { Link } from 'react-router';
import { useChatShellStore } from '@/stores/chat-shell';

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
      <SettingsGroup title={t('personality.thoughts.settingsTitle')}>
        <div className="flex items-start justify-between gap-4 py-3">
          <div className="space-y-1"><p className="text-sm font-medium">{t('personality.thoughts.enable')}</p>
            <p className="text-xs leading-6 text-muted-foreground">{t('personality.thoughts.enableDescription')}</p></div>
          <Switch aria-label={t('personality.thoughts.enable')} checked={draftConfig.personalitySettings.background_reflection_enabled}
            onCheckedChange={(checked) => patchDraftConfig((draft) => {
              draft.personalitySettings.background_reflection_enabled = checked;
              if (checked) draft.personalitySettings.state_memory_enabled = true;
            })} />
        </div>
        <div className="flex items-start justify-between gap-4 py-3">
          <div className="space-y-1"><p className="text-sm font-medium">{t('personality.thoughts.share')}</p>
            <p className="text-xs leading-6 text-muted-foreground">{t('personality.thoughts.shareDescription')}</p></div>
          <Switch aria-label={t('personality.thoughts.share')} checked={draftConfig.personalitySettings.proactive_sharing_enabled}
            onCheckedChange={(checked) => patchDraftConfig((draft) => { draft.personalitySettings.proactive_sharing_enabled = checked; })} />
        </div>
        <div className="flex gap-4 text-sm"><Link className="underline" to="/memory/sources">{t('personality.thoughts.sources')}</Link>
          <button type="button" className="underline" onClick={() => useChatShellStore.getState().setSettingsNavigationIntent({ section: 'statisticsLlm' })}>{t('personality.thoughts.usage')}</button></div>
        <details className="pt-3 text-sm"><summary className="cursor-pointer">{t('personality.thoughts.limits')}</summary>
          <label className="mt-3 flex items-center justify-between gap-4">{t('personality.thoughts.dailyLimit')}
            <Input className="w-24" type="number" min={1} max={12} value={draftConfig.personalitySettings.reflection_daily_limit}
              onChange={(event) => { const value = Number(event.target.value); if (Number.isInteger(value) && value >= 1 && value <= 12) patchDraftConfig((draft) => { draft.personalitySettings.reflection_daily_limit = value; }); }} /></label>
          <p className="mt-2 text-xs text-muted-foreground">{t('personality.thoughts.localLimit')}</p>
        </details>
      </SettingsGroup>
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
