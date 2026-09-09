import { listen } from '@tauri-apps/api/event';
import { z } from 'zod';
import { getRuntimeConfig, isTauriRuntime, requestRuntimeReconnect } from './config';

const recoverySchema = z.object({
  profileId: z.string(),
  previousPid: z.number().int().positive(),
  localServicePid: z.number().int().positive(),
});

/** The bootstrap mount owns this listener, including asynchronous registration cleanup. */
export function observeLocalServiceRecovery(): () => void {
  if (!isTauriRuntime()) return () => undefined;
  let disposed = false;
  let unsubscribe: (() => void) | undefined;
  void listen<unknown>('magi-service-recovered', ({ payload }) => {
    if (disposed) return;
    const result = recoverySchema.safeParse(payload);
    if (!result.success) return;
    const runtime = getRuntimeConfig();
    if (runtime.mode === 'local' && runtime.profileId === result.data.profileId
      && runtime.localServicePid === result.data.previousPid) {
      requestRuntimeReconnect();
    }
  }).then((cleanup) => {
    if (disposed) cleanup();
    else unsubscribe = cleanup;
  }).catch((error: unknown) => {
    if (!disposed) console.error('Could not observe local service recovery', error);
  });
  return () => { disposed = true; unsubscribe?.(); };
}
