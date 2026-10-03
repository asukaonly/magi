import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { SystemConfig } from '@/api/modules/config';
import { setAutomaticSpeech, useAutomaticSpeech } from '@/hooks/useAutomaticSpeech';
import { Button } from '@/components/ui/button';
import { AudioDeviceTest } from './AudioDeviceTest';
import { SettingsGroup, SettingsSectionShell, SettingsSwitchRow } from './SettingsSectionPrimitives';

interface Props {
  draftConfig: SystemConfig;
  patchDraftConfig: (update: (draft: SystemConfig) => void) => void;
  onConfigureModel: (section: 'asr' | 'tts') => void;
}

export function SettingsVoiceSection({ draftConfig, patchDraftConfig, onConfigureModel }: Props) {
  const { t } = useTranslation('app');
  const automatic = useAutomaticSpeech();
  const [preferenceError, setPreferenceError] = useState(false);
  return <SettingsSectionShell>
    <SettingsGroup title={t('asr.title')}>
      <SettingsSwitchRow title={t('asr.enabled')} description={t('asr.description')} ariaLabel={t('asr.enabled')}
        checked={draftConfig.speech.asr.enabled}
        onCheckedChange={(enabled) => patchDraftConfig(draft => { draft.speech.asr.enabled = enabled; })} />
      <p className="text-sm leading-6 text-muted-foreground">{t('voiceSettings.inputHint')}</p>
      <Button variant="outline" onClick={() => onConfigureModel('asr')}>{t('voiceSettings.configureRecognition')}</Button>
    </SettingsGroup>
    <SettingsGroup title={t('tts.title')} description={t('voiceSettings.playbackHint')}>
      <SettingsSwitchRow title={t('tts.automatic')} description={t('tts.automaticDescription')}
        ariaLabel={t('tts.automatic')} checked={automatic} onCheckedChange={(enabled) => {
          try { setAutomaticSpeech(enabled); setPreferenceError(false); }
          catch { setPreferenceError(true); }
        }} />
      {preferenceError && <p role="alert" className="text-sm text-destructive">{t('tts.preferenceSaveFailed')}</p>}
      <Button variant="outline" onClick={() => onConfigureModel('tts')}>{t('voiceSettings.configureSynthesis')}</Button>
    </SettingsGroup>
    <AudioDeviceTest />
  </SettingsSectionShell>;
}
