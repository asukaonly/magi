import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { SettingsGroup } from './SettingsSectionPrimitives';
import { Button } from '@/components/ui/button';
import { useAudioIO } from '@/hooks/useAudioIO';
import { audioError, type AudioIOError } from '@/lib/audio/format';

export function AudioDeviceTest() {
  const { t } = useTranslation('app');
  const { recorder, player, recording, playback } = useAudioIO('local-device-test');
  const [error, setError] = useState<AudioIOError | null>(null);
  const capturing = ['requesting', 'recording', 'stopping'].includes(recording.phase);
  const playing = ['starting', 'waiting', 'playing', 'paused'].includes(playback.phase);
  const failure = error ?? recording.error ?? playback.error;

  const play = async () => {
    if (!recording.audio || ['starting', 'waiting', 'playing', 'paused'].includes(player.getSnapshot().phase)) return;
    setError(null);
    try {
      const session = await player.begin();
      if (session === null) return;
      await player.enqueue(session, 0, recording.audio);
      player.finish(session);
    } catch (reason) {
      setError(audioError(reason, 'playback_failed'));
    }
  };

  return <SettingsGroup title={t('settings.audio.title')} description={t('settings.audio.description')}>
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" disabled={capturing} onClick={() => { setError(null); player.stop(); void recorder.start(); }}>
          {t('settings.audio.record')}
        </Button>
        {recording.phase === 'recording' && <Button variant="outline" onClick={() => { void recorder.stop(); }}>
          {t('settings.audio.finishRecording')}
        </Button>}
        {capturing && <Button variant="ghost" onClick={recorder.cancel}>{t('settings.audio.cancel')}</Button>}
        <Button variant="outline" disabled={!recording.audio || capturing || playing} onClick={() => { void play(); }}>
          {t('settings.audio.play')}
        </Button>
        {playing && <>
          <Button variant="outline" disabled={playback.phase === 'starting'} onClick={() => { void player.setPaused(playback.phase !== 'paused'); }}>
            {playback.phase === 'paused' ? t('settings.audio.resume') : t('settings.audio.pause')}
          </Button>
          <Button variant="ghost" onClick={player.stop}>{t('settings.audio.stop')}</Button>
        </>}
      </div>
      <p role="status" className="text-xs text-muted-foreground">
        {playing || playback.phase === 'completed'
          ? t(`settings.audio.playback.${playback.phase}`)
          : t(`settings.audio.capture.${recording.phase}`, { seconds: recording.seconds.toFixed(1) })}
      </p>
      {failure && <p role="alert" className="text-sm text-destructive">{t(`settings.audio.errors.${failure.code}`)}</p>}
    </div>
  </SettingsGroup>;
}
