import { useTranslation } from 'react-i18next';

import type { SystemConfig } from '@/api/modules/config';
import { LabeledSelectField } from '@/components/settings';
import { DesktopUpdateSection } from '@/components/settings/DesktopUpdateSection';
import { SettingsGroup, SettingsSectionShell } from '@/components/settings/SettingsSectionPrimitives';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { cn } from '@/lib/utils';
import { requestDesktopNotificationPermission } from '@/runtime/desktop-notifications';
import { THEME_MODE_OPTIONS, type ThemeMode } from '@/stores/theme';

interface SettingsPreferencesSectionProps {
  draftConfig: SystemConfig;
  draftThemeMode: ThemeMode;
  patchDraftConfig: (updater: (draft: SystemConfig) => void) => void;
  onThemePreviewChange: (mode: ThemeMode) => void;
  onLanguageDraftChange: (value: string) => void;
}

const settingsSwitchClassName =
  'transition-colors duration-200 data-[state=unchecked]:bg-[hsl(var(--settings-secondary)/0.76)] data-[state=checked]:bg-primary hover:data-[state=unchecked]:bg-[hsl(var(--settings-secondary)/0.94)] hover:data-[state=checked]:bg-primary/90 focus-visible:ring-ring/30';

const settingsInputClassName =
  'h-11 rounded-lg border-transparent bg-[hsl(var(--settings-shell-elevated)/0.78)] px-4 text-[15px] text-foreground shadow-[inset_0_0_0_1px_hsl(var(--settings-subnav-border)/0.28)] transition-[background-color,box-shadow,color] duration-200 hover:bg-[hsl(var(--settings-shell-elevated)/0.96)] hover:shadow-[inset_0_0_0_1px_hsl(var(--settings-subnav-border)/0.44)] focus-visible:ring-2 focus-visible:ring-ring/25 focus-visible:ring-offset-0';

function PreferenceToggleRow({
  label,
  description,
  checked,
  onCheckedChange,
}: {
  label: string;
  description?: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
}) {
  return (
    <div className="flex min-h-10 items-center justify-between gap-6 rounded-lg px-1 py-1.5 transition-colors duration-200 hover:bg-[hsl(var(--settings-shell-elevated)/0.34)]">
      <div className="min-w-0">
        <div className="text-sm font-medium leading-6 text-foreground/85">{label}</div>
        {description ? (
          <div className="max-w-2xl text-xs leading-5 text-muted-foreground">
            {description}
          </div>
        ) : null}
      </div>
      <Switch
        aria-label={label}
        checked={checked}
        onCheckedChange={onCheckedChange}
        className={settingsSwitchClassName}
      />
    </div>
  );
}

export function SettingsPreferencesSection({
  draftConfig,
  draftThemeMode,
  patchDraftConfig,
  onThemePreviewChange,
  onLanguageDraftChange,
}: SettingsPreferencesSectionProps) {
  const { t } = useTranslation('app');

  const handleDesktopNotificationsChange = (checked: boolean) => {
    patchDraftConfig((draft) => {
      draft.preferences.desktop_notifications_enabled = checked;
    });
    if (!checked) {
      return;
    }
    void requestDesktopNotificationPermission().then((granted) => {
      if (!granted) {
        patchDraftConfig((draft) => {
          draft.preferences.desktop_notifications_enabled = false;
        });
      }
    });
  };

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
          onChange={onLanguageDraftChange}
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
          options={THEME_MODE_OPTIONS.map((mode) => ({
            label: t(`settings.theme.${mode}`),
            value: mode,
          }))}
          onChange={(value) => onThemePreviewChange(value as ThemeMode)}
        />
      </SettingsGroup>

      <SettingsGroup title={t('settings.fields.windowSettings')}>
        <div className="space-y-1.5">
          <PreferenceToggleRow
            label={t('settings.closeToTrayLabel')}
            checked={draftConfig.preferences.close_to_tray_enabled}
            onCheckedChange={(checked) => patchDraftConfig((draft) => {
              draft.preferences.close_to_tray_enabled = checked;
            })}
          />
          <PreferenceToggleRow
            label={t('settings.skipQuitConfirmationLabel')}
            checked={draftConfig.preferences.skip_quit_confirmation}
            onCheckedChange={(checked) => patchDraftConfig((draft) => {
              draft.preferences.skip_quit_confirmation = checked;
            })}
          />
          <PreferenceToggleRow
            label={t('settings.desktopNotificationsLabel')}
            checked={draftConfig.preferences.desktop_notifications_enabled}
            onCheckedChange={handleDesktopNotificationsChange}
          />
          <PreferenceToggleRow
            label={t('settings.desktopNotificationPreviewsLabel')}
            checked={draftConfig.preferences.desktop_notification_previews_enabled}
            onCheckedChange={(checked) => patchDraftConfig((draft) => {
              draft.preferences.desktop_notification_previews_enabled = checked;
            })}
          />
        </div>
      </SettingsGroup>

      <SettingsGroup title={t('settings.startupSettings')}>
        <div className="space-y-1.5">
          <PreferenceToggleRow
            label={t('settings.autoStartLabel')}
            checked={draftConfig.preferences.auto_start_enabled}
            onCheckedChange={(checked) => patchDraftConfig((draft) => {
              draft.preferences.auto_start_enabled = checked;
            })}
          />
          <PreferenceToggleRow
            label={t('settings.startMinimizedLabel')}
            checked={draftConfig.preferences.start_minimized}
            onCheckedChange={(checked) => patchDraftConfig((draft) => {
              draft.preferences.start_minimized = checked;
            })}
          />
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
            <div className="grid gap-4">
              <div className="grid grid-cols-[minmax(0,1fr)_8rem] gap-4">
                <label className="space-y-2.5">
                  <span className="text-xs font-medium leading-5 text-muted-foreground">{t('settings.fields.proxyHost')}</span>
                  <Input
                    aria-label={t('settings.fields.proxyHost')}
                    value={draftConfig.network.host}
                    placeholder="127.0.0.1"
                    className={settingsInputClassName}
                    onChange={(e) => patchDraftConfig((draft) => {
                      draft.network.host = e.target.value;
                    })}
                  />
                </label>
                <label className="space-y-2.5">
                  <span className="text-xs font-medium leading-5 text-muted-foreground">{t('settings.fields.proxyPort')}</span>
                  <Input
                    type="number"
                    aria-label={t('settings.fields.proxyPort')}
                    value={draftConfig.network.port}
                    min={1}
                    max={65535}
                    placeholder="7890"
                    className={cn(settingsInputClassName, 'tabular-nums')}
                    onChange={(e) => patchDraftConfig((draft) => {
                      const port = parseInt(e.target.value, 10);
                      if (!Number.isNaN(port) && port >= 1 && port <= 65535) {
                        draft.network.port = port;
                      }
                    })}
                  />
                </label>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="space-y-2.5">
                  <span className="text-xs font-medium leading-5 text-muted-foreground">{t('settings.fields.proxyUsername')}</span>
                  <Input
                    aria-label={t('settings.fields.proxyUsername')}
                    value={draftConfig.network.username ?? ''}
                    placeholder={t('settings.fields.proxyUsername')}
                    className={settingsInputClassName}
                    onChange={(e) => patchDraftConfig((draft) => {
                      draft.network.username = e.target.value;
                    })}
                  />
                </label>
                <label className="space-y-2.5">
                  <span className="text-xs font-medium leading-5 text-muted-foreground">{t('settings.fields.proxyPassword')}</span>
                  <Input
                    type="password"
                    aria-label={t('settings.fields.proxyPassword')}
                    value={draftConfig.network.password ?? ''}
                    placeholder={t('settings.fields.proxyPassword')}
                    autoComplete="off"
                    className={settingsInputClassName}
                    onChange={(e) => patchDraftConfig((draft) => {
                      draft.network.password = e.target.value;
                    })}
                  />
                </label>
              </div>
            </div>
          )}
          <PreferenceToggleRow
            label={t('settings.fakeIpCompatibility')}
            description={t('settings.fakeIpCompatibilityDesc')}
            checked={draftConfig.tools.builtIn.webFetch.allowRfc2544BenchmarkRange}
            onCheckedChange={(checked) => patchDraftConfig((draft) => {
              draft.tools.builtIn.webFetch.allowRfc2544BenchmarkRange = checked;
            })}
          />
        </div>
      </SettingsGroup>

      <DesktopUpdateSection networkConfig={draftConfig.network} />
    </SettingsSectionShell>
  );
}
