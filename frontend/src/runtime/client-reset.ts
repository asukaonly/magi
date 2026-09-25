import { invoke } from '@tauri-apps/api/core';
import { advanceBrowserContentGeneration } from '@/lib/browserContentGeneration';
import { clearAllCenterStorage } from './center-storage';
import { resetRuntimeInitialization } from './config';

type ResetPhase = 'checking' | 'idle' | 'resetting' | 'failed' | 'complete' | 'check_failed';
let phase: ResetPhase = 'checking';
let inspection: Promise<void> | undefined;
let cleanup: Promise<void> | undefined;
const listeners = new Set<() => void>();
const setPhase = (next: ResetPhase) => { phase = next; listeners.forEach((listener) => listener()); };
export const readClientResetPhase = (): ResetPhase => phase;
export function subscribeClientReset(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function inspectClientReset(): Promise<void> {
  if (inspection) return inspection;
  setPhase('checking');
  inspection = invoke<unknown>('client_reset_pending').then((pending) => {
    if (typeof pending !== 'boolean') throw new Error('Invalid client reset status');
    if (phase === 'checking') setPhase(pending ? 'resetting' : 'idle');
  }).catch(() => { if (phase === 'checking') setPhase('check_failed'); })
    .finally(() => { inspection = undefined; });
  return inspection;
}

/** The root boundary unmounts live views before performing any destructive cleanup. */
export function requestClientReset(): void {
  if (phase === 'resetting' || phase === 'complete') return;
  advanceBrowserContentGeneration();
  resetRuntimeInitialization();
  setPhase('resetting');
}

export function performClientReset(): Promise<void> {
  if (cleanup) return cleanup;
  if (phase !== 'resetting') return Promise.resolve();
  cleanup = (async () => {
    try {
      await invoke('reset_client_connections', { discardPending: true });
      clearAllCenterStorage();
      await invoke('complete_client_reset');
      setPhase('complete');
    } catch { setPhase('failed'); }
  })().finally(() => { cleanup = undefined; });
  return cleanup;
}

export function reopenClientWelcome(): void {
  window.location.replace(new URL('/', window.location.href).href);
}
