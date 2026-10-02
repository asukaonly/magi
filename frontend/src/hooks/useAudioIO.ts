import { useEffect, useState, useSyncExternalStore } from 'react';
import { SegmentAudioPlayer } from '@/lib/audio/player';
import { WavRecorder } from '@/lib/audio/recorder';

/** Features must change scopeKey when their connection, conversation, or content epoch changes. */
export function useAudioIO(scopeKey: string) {
  const [recorder] = useState(() => new WavRecorder());
  const [player] = useState(() => new SegmentAudioPlayer());
  const recording = useSyncExternalStore(recorder.subscribe, recorder.getSnapshot);
  const playback = useSyncExternalStore(player.subscribe, player.getSnapshot);
  useEffect(() => () => { recorder.cancel(); player.stop(); }, [scopeKey, recorder, player]);
  return { recorder, player, recording, playback };
}
