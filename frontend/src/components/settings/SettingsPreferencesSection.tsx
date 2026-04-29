import { useTranslation } from 'react-i18next';

import type { SystemConfig } from '@/api/modules/config';
import { LabeledSelectField } from '@/components/settings';
import { DesktopUpdateSection } from '@/components/settings/DesktopUpdateSection';
import { SettingsGroup, SettingsSectionShell } from '@/components/settings/SettingsSectionPrimitives';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import type { ThemeMode } from '@/stores/theme';

interface SettingsPreferencesSectionProps {
  draftConfig: SystemConfig;
  draftThemeMode: ThemeMode;
  patchDraftConfig: (updater: (draft: SystemConfig) => void) => void;
  onThemePreviewChange: (mode: ThemeMode) => void;
  onLanguagePreviewChange: (value: string) => void;
}

export function SettingsPreferencesSection({
  draftConfig,
  draftThemeMode,
  patchDraftConfig,
  onThemePreviewChange,
  onLanguagePreviewChange,
}: SettingsPreferencesSectionProps) {
  const { t } = useTranslation('app');

  return (
    <SettingsSectionShell>
      <SettingsGroup title={t('settings.fields.language')}>
        <LabeledSelectField
          label=""
          ariaLabel={t('settings.fields.language')}
          value={draftConfig.preferences.language}
          options={[
            { label: t('language.zhHans', { ns: 'onboarding' }), value: 'zh' },
            { label: t('language.en', { ns: 'onboarding' }), value: 'en' },
          ]}
          onChange={onLanguagePreviewChange}
        />
      </SettingsGroup>

      <SettingsGroup
        title={t('settings.fields.theme')}
        description={t('settings.themeDesc')}
      >
        <LabeledSelectField
          label=""
          ariaLabel={t('settings.fields.theme')}
          value={draftThemeMode}
          options={[
            { label: t('settings.theme.light'), value: 'light' },
            { label: t('settings.theme.dark'), value: 'dark' },
            { label: t('settings.theme.system'), value: 'system' },
          ]}
          onChange={(value) => onThemePreviewChange(value as ThemeMode)}
        />
      </SettingsGroup>

      <SettingsGroup title={t('settings.fields.windowSettings')}>
        <div className="flex items-center justify-between gap-4">
          <span className="text-sm">{t('settings.closeToTrayLabel')}</span>
          <Switch
            aria-label={t('settings.closeToTrayLabel')}
            checked={draftConfig.preferences.close_to_tray_enabled}
            onCheckedChange={(checked) => patchDraftConfig((draft) => {
              draft.preferences.close_to_tray_enabled = checked;
            })}
          />
        </div>
      </SettingsGroup>

      <SettingsGroup title={t('settings.startupSettings')}>
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-4">
            <span className="text-sm">{t('settings.autoStartLabel')}</span>
            <Switch
              aria-label={t('settings.autoStartLabel')}
              checked={draftConfig.preferences.auto_start_enabled}
              onCheckedChange={(checked) => patchDraftConfig((draft) => {
                draft.preferences.auto_start_enabled = checked;
              })}
            />
          </div>
          <div className="flex items-center justify-between gap-4">
            <span className="text-sm">{t('settings.startMinimizedLabel')}</span>
            <Switch
              aria-label={t('settings.startMinimizedLabel')}
              checked={draftConfig.preferences.start_minimized}
              onCheckedChange={(checked) => patchDraftConfig((draft) => {
                draft.preferences.start_minimized = checked;
              })}
            />
          </div>
        </div>
      </SettingsGroup>

      <SettingsGroup title={t('settings.fields.networkProxy')}>
        <div className="space-y-4">
          <LabeledSelectField
            label=""
            ariaLabel={t('settings.fields.networkProxy')}
            value={draftConfig.network.enabled ? draftConfig.network.proxy_type : 'off'}
            options={[
              { label: t('settings.proxyOff'), value: 'off' },
              { label: 'HTTP', value: 'http' },
              { label: 'SOCKS5', value: 'socks5' },
            ]}
            onChange={(value) => patchDraftConfig((draft) => {
              if (value === 'off') {
                draft.network.enabled = false;
              } else {
                draft.network.enabled = true;
                draft.network.proxy_type = value as 'http' | 'socks5';
              }
            })}
          />
          {draftConfig.network.enabled && (
            <div className="grid grid-cols-[1fr_auto] gap-3">
              <label className="space-y-1.5">
                <span className="text-xs text-muted-foreground">{t('settings.fields.proxyHost')}</span>
                <Input
                  aria-label={t('settings.fields.proxyHost')}
                  value={draftConfig.network.host}
                  placeholder="127.0.0.1"
                  onChange={(e) => patchDraftConfig((draft) => {
                    draft.network.host = e.target.value;
                  })}
                />
              </label>
              <label className="space-y-1.5 w-28">
                <span className="text-xs text-muted-foreground">{t('settings.fields.proxyPort')}</span>
                <Input
                  type="number"
                  aria-label={t('settings.fields.proxyPort')}
                  value={draftConfig.network.port}
                  min={1}
                  max={65535}
                  placeholder="7890"
                  onChange={(e) => patchDraftConfig((draft) => {
                    const port = parseInt(e.target.value, 10);
                    if (!Number.isNaN(port) && port >= 1 && port <= 65535) {
                      draft.network.port = port;
                    }
                  })}
                />
              </label>
            </div>
          )}
        </div>
      </SettingsGroup>

      <DesktopUpdateSection />
    </SettingsSectionShell>
  );
}