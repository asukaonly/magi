import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import type { SpeechSnapshot, TTSController } from '@/lib/audio/tts-controller';

export function TTSPlaybackControls({ controller, state }: { controller: TTSController; state: SpeechSnapshot }) {
  const { t } = useTranslation('app');
  const active = ['generating', 'playing', 'paused'].includes(state.phase);
  if (state.phase === 'idle') return null;
  const knownErrors = ['audio_expired', 'no_readable_text', 'text_too_long', 'runtime_missing', 'model_missing',
    'stale_message', 'playback_blocked', 'recording_active', 'provider_outcome_unknown'];
  const error = state.error && knownErrors.includes(state.error) ? state.error : 'synthesis_failed';
  return <div className="flex flex-wrap items-center gap-2 py-2 text-sm">
    <span role="status">{t(`tts.phase.${state.phase}`)}</span>
    {active && <>
      <Button size="sm" variant="outline" onClick={() => { void controller.pause(); }}>
        {state.phase === 'paused' ? t('tts.resume') : t('tts.pause')}
      </Button>
      <Button size="sm" variant="ghost" onClick={controller.stop}>{t('tts.stop')}</Button>
    </>}
    {state.error && <span role="alert" className="text-destructive">{t(`tts.errors.${error}`)}</span>}
    {state.cancellation === 'pending' && <span>{t('tts.cancelling')}</span>}
    {state.cancellation === 'unknown' && <span role="alert">{t('tts.cancelUnknown')}</span>}
  </div>;
}
