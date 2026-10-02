import { useEffect, useState, useSyncExternalStore } from 'react';
import { useAudioIO } from './useAudioIO';
import { TTSController } from '@/lib/audio/tts-controller';
import { subscribeRuntimeReset, subscribeRuntimeReconnect } from '@/runtime/config';
import { APP_EVENTS } from '@/constants/events';

export function useTTS(scopeKey: string) {
  const { player } = useAudioIO(scopeKey);
  const [controller] = useState(() => new TTSController(player));
  const state = useSyncExternalStore(controller.subscribe, controller.getSnapshot);
  useEffect(() => {
    const reset = subscribeRuntimeReset(controller.stop);
    const reconnect = subscribeRuntimeReconnect(controller.stop);
    const events = [APP_EVENTS.MEMORY_CLEAR_STARTED, APP_EVENTS.CENTER_MAINTENANCE, APP_EVENTS.CHAT_HISTORY_CLEARED, APP_EVENTS.CHAT_SESSION_DELETED];
    events.forEach((event) => window.addEventListener(event, controller.stop));
    window.addEventListener('pagehide', controller.stop);
    return () => {
      controller.stop(); reset(); reconnect();
      events.forEach((event) => window.removeEventListener(event, controller.stop));
      window.removeEventListener('pagehide', controller.stop);
    };
  }, [controller, scopeKey]);
  return { controller, state };
}
