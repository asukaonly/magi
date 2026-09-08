import type { ClearMemoryResponse } from '@/api/modules/memory';
import { parseClearMemory } from '@/api/lifecycle-contract';
import { serverApi, type CenterMaintenance } from '@/api/modules/server';
import { configureApiClient } from '@/api/client';
import { dispatchAppEvent } from '@/constants/events';
import { clearDesktopLogHistory } from '@/runtime/desktop';
import { getRuntimeConfig, getRuntimeGeneration, assertRuntimeGeneration, setRuntimeDataEpoch } from '@/runtime/config';
import { centerLocalStorage, setCenterStorageScope } from '@/runtime/center-storage';
import { completeMemoryClear } from './chatRetryLifecycle';

const PENDING_KEY = 'maintenance.pending-clear';
let activeClear: Promise<ClearMemoryResponse> | null = null;

async function applyDataEpoch(status: CenterMaintenance): Promise<void> {
  const runtime = getRuntimeConfig();
  const owner = getRuntimeGeneration();
  if (!runtime.serverId) throw new Error('Center identity is missing');
  const epochChanged = status.data_epoch !== runtime.dataEpoch;
  setCenterStorageScope(runtime.serverId, status.data_epoch);
  if (epochChanged) centerLocalStorage().setItem('maintenance.device-cleanup', 'pending');
  if (epochChanged || centerLocalStorage().getItem('maintenance.device-cleanup')) {
    dispatchAppEvent.memoryClearStarted();
    const cleanup = completeMemoryClear({ announce: false });
    if (!cleanup.browserStateCleared) throw new Error('This device could not clear its cached content');
    setRuntimeDataEpoch(status.data_epoch);
    configureApiClient({ baseUrl: runtime.apiBaseUrl, sessionToken: runtime.sessionToken });
    const logs = await clearDesktopLogHistory();
    assertRuntimeGeneration(owner);
    if (logs && logs.failedEntries > 0) throw new Error('This device could not clear its diagnostic logs');
    centerLocalStorage().removeItem('maintenance.device-cleanup');
    dispatchAppEvent.memoryCleared();
  }
}

async function waitForClear(initial: CenterMaintenance, operationId: string): Promise<ClearMemoryResponse> {
  const owner = getRuntimeGeneration();
  let status = initial;
  const deadline = Date.now() + 15 * 60_000;
  while (Date.now() < deadline) {
    assertRuntimeGeneration(owner);
    if (status.operation_id !== operationId) status = await serverApi.clear(operationId);
    if (status.phase === 'failed') throw new Error(status.error ?? 'Center maintenance failed; retry the same operation');
    if (status.phase === 'completed') {
      const result = parseClearMemory(status.result);
      if (result.warnings.length > 0) throw new Error('Center clear is incomplete');
      await applyDataEpoch(status);
      centerLocalStorage().removeItem(PENDING_KEY);
      dispatchAppEvent.memoryClearRecoveryReleased();
      return result;
    }
    await new Promise<void>((resolve) => window.setTimeout(resolve, 750));
    status = await serverApi.maintenance();
  }
  throw new Error('Center maintenance is still running; reconnect to inspect its status');
}

function serializeClear(operation: () => Promise<ClearMemoryResponse>): Promise<ClearMemoryResponse> {
  if (activeClear) return activeClear;
  const running = operation().catch((error: unknown) => {
    dispatchAppEvent.memoryClearFailed(error instanceof Error ? error.message : 'Center maintenance remains pending');
    throw error;
  }).finally(() => { if (activeClear === running) activeClear = null; });
  activeClear = running;
  return running;
}

export function clearAllMemory(): Promise<ClearMemoryResponse> {
  return serializeClear(async () => {
    dispatchAppEvent.memoryClearStarted();
    const storage = centerLocalStorage();
    const operationId = storage.getItem(PENDING_KEY) ?? crypto.randomUUID();
    storage.setItem(PENDING_KEY, operationId);
    return waitForClear(await serverApi.clear(operationId), operationId);
  });
}

/** Reconnect observes durable server work without restarting or stopping the center. */
export async function recoverPendingFullDataClear(retryFailed = false): Promise<boolean> {
  const status = await serverApi.maintenance();
  const pendingId = centerLocalStorage().getItem(PENDING_KEY);
  const running = !['idle', 'completed'].includes(status.phase);
  if (running || pendingId) {
    const id = running ? status.operation_id : pendingId;
    if (!id) throw new Error('Center maintenance identity is missing');
    dispatchAppEvent.memoryClearStarted();
    await serializeClear(async () => {
      const initial = (status.phase === 'failed' && retryFailed) || (!running && pendingId)
        ? await serverApi.clear(id) : status;
      return waitForClear(initial, id);
    });
    return true;
  }
  try { await applyDataEpoch(status); }
  catch (error) { dispatchAppEvent.memoryClearFailed(error instanceof Error ? error.message : 'This device cleanup is incomplete'); throw error; }
  return false;
}
