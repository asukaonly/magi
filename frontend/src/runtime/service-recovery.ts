import { listen } from '@tauri-apps/api/event';
import { invoke } from '@tauri-apps/api/core';
import { z } from 'zod';
import { getRuntimeConfig, getRuntimeGeneration, isTauriRuntime, requestRuntimeReconnect } from './config';

const recoverySchema = z.object({
  profileId: z.string(),
  previousPid: z.number().int().positive(),
  localServicePid: z.number().int().positive(),
});

const snapshotSchema = z.object({
  generation: z.number().int().nonnegative().safe(),
  profileId: z.string().min(1),
  mode: z.enum(['local', 'remote']),
  recovering: z.boolean(),
}).nullable();

/** The bootstrap mount owns this listener, including asynchronous registration cleanup. */
export function observeLocalServiceRecovery(): () => void {
  if (!isTauriRuntime()) return () => undefined;
  let disposed = false;
  let unsubscribe: (() => void) | undefined;
  let pending = false;
  const inspect = async () => {
    if (disposed || pending) return;
    const runtime = getRuntimeConfig();
    if (runtime.mode !== 'local' || runtime.connectionGeneration === undefined) return;
    const owner = getRuntimeGeneration();
    pending = true;
    try {
      const snapshot = snapshotSchema.parse(await invoke<unknown>('read_connection_snapshot'));
      if (disposed || owner !== getRuntimeGeneration() || !snapshot || snapshot.recovering) return;
      if (snapshot.mode === 'local' && snapshot.profileId === runtime.profileId
        && snapshot.generation !== runtime.connectionGeneration) requestRuntimeReconnect();
    } catch {
      // A later poll retries native transport failures without replaying API calls.
    } finally { pending = false; }
  };
  const wake = () => { void inspect(); };
  const timer = window.setInterval(wake, 5_000);
  window.addEventListener('focus', wake);
  void listen<unknown>('magi-service-recovered', ({ payload }) => {
    if (disposed) return;
    const result = recoverySchema.safeParse(payload);
    if (!result.success) return;
    wake();
  }).then((cleanup) => {
    if (disposed) cleanup();
    else unsubscribe = cleanup;
    wake();
  }).catch((error: unknown) => {
    if (!disposed) console.error('Could not observe local service recovery', error);
  });
  return () => {
    disposed = true;
    window.clearInterval(timer);
    window.removeEventListener('focus', wake);
    unsubscribe?.();
  };
}
