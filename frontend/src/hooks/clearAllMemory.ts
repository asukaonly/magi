import type { ClearMemoryResponse } from '@/api/modules/memory';
import { parseClearMemory } from '@/api/lifecycle-contract';
import { serverApi, type CenterMaintenance } from '@/api/modules/server';
import { clearPrivateResourceAccessCache } from '@/api/modules/privateResources';
import { configureApiClient } from '@/api/client';
import { APP_EVENTS, dispatchAppEvent, dispatchCustomAppEvent } from '@/constants/events';
import { clearDesktopLogHistory } from '@/runtime/desktop';
import { getRuntimeConfig, getRuntimeGeneration, assertRuntimeGeneration, setRuntimeEpochs, subscribeRuntimeReset } from '@/runtime/config';
import { centerLocalStorage, setCenterStorageScope } from '@/runtime/center-storage';
import { completeMemoryClear } from './chatRetryLifecycle';

type Kind = 'clear' | 'restore';
const pendingKey = (kind: Kind) => `maintenance.pending-${kind}`;
let activeMaintenance: Promise<CenterMaintenance> | null = null;
let activeClear: Promise<ClearMemoryResponse> | null = null;
subscribeRuntimeReset(() => { activeMaintenance = null; activeClear = null; });
const pause = () => new Promise<void>((resolve) => window.setTimeout(resolve, 750));

async function applyCenterEpochs(status: CenterMaintenance): Promise<void> {
  const runtime = getRuntimeConfig();
  const owner = getRuntimeGeneration();
  if (!runtime.serverId) throw new Error('Center identity is missing');
  const dataChanged = status.data_epoch !== runtime.dataEpoch;
  const contentChanged = status.content_epoch !== runtime.contentEpoch;
  setCenterStorageScope(runtime.serverId, status.content_epoch);
  if (contentChanged) centerLocalStorage().setItem('maintenance.device-cleanup', 'pending');
  if (contentChanged || centerLocalStorage().getItem('maintenance.device-cleanup')) {
    dispatchAppEvent.memoryClearStarted();
    const cleanup = completeMemoryClear({ announce: false });
    if (!cleanup.browserStateCleared) throw new Error('This device could not clear its cached content');
    const logs = await clearDesktopLogHistory();
    assertRuntimeGeneration(owner);
    if (logs && logs.failedEntries > 0) throw new Error('This device could not clear its diagnostic logs');
    centerLocalStorage().removeItem('maintenance.device-cleanup');
    dispatchAppEvent.memoryCleared();
  }
  setRuntimeEpochs(status.data_epoch, status.content_epoch);
  if (dataChanged) {
    clearPrivateResourceAccessCache();
    configureApiClient({ baseUrl: runtime.apiBaseUrl, sessionToken: runtime.sessionToken });
    dispatchCustomAppEvent(APP_EVENTS.CENTER_STATE_CHANGED, { resource: 'memory' });
  }
}

async function waitForOperation(initial: CenterMaintenance, operationId: string, kind: Kind): Promise<CenterMaintenance> {
  const owner = getRuntimeGeneration();
  let status = initial;
  const deadline = Date.now() + 65 * 60_000;
  while (Date.now() < deadline) {
    assertRuntimeGeneration(owner);
    if (status.operation_id !== operationId || status.kind !== kind) throw new Error('Maintenance operation identity changed');
    if (status.phase === 'failed') throw new Error(status.error ?? 'Center maintenance failed; retry the same operation');
    if (status.phase === 'completed') {
      if (kind === 'clear') {
        const result = parseClearMemory(status.result);
        if (result.warnings.length > 0) throw new Error('Center clear is incomplete');
      }
      // Completion is durable before a new normal worker becomes ready.
      const info = await serverApi.info();
      assertRuntimeGeneration(owner);
      if (info.runtime_ready) {
        await applyCenterEpochs(info.maintenance);
        centerLocalStorage().removeItem(pendingKey(kind));
        dispatchAppEvent.centerMaintenance(null, 'idle');
        dispatchAppEvent.memoryClearRecoveryReleased();
        return status;
      }
    }
    await pause();
    status = await serverApi.operation(operationId);
  }
  throw new Error('Center maintenance is still running; reconnect to inspect its status');
}

function ownMaintenance(kind: Kind, operation: () => Promise<CenterMaintenance>): Promise<CenterMaintenance> {
  if (activeMaintenance) return activeMaintenance;
  const owner = getRuntimeGeneration();
  dispatchAppEvent.centerMaintenance(kind, 'running');
  const running = operation().catch((error: unknown) => {
    if (owner === getRuntimeGeneration()) dispatchAppEvent.centerMaintenance(kind, 'failed', error instanceof Error ? error.message : 'Center maintenance remains pending');
    throw error;
  }).finally(() => { if (activeMaintenance === running) activeMaintenance = null; });
  activeMaintenance = running;
  return running;
}

export function clearAllMemory(): Promise<ClearMemoryResponse> {
  if (activeClear) return activeClear;
  if (activeMaintenance) return Promise.reject(new Error('Another maintenance operation is running'));
  const running = ownMaintenance('clear', async () => {
    dispatchAppEvent.memoryClearStarted();
    const storage = centerLocalStorage();
    const operationId = storage.getItem(pendingKey('clear')) ?? crypto.randomUUID();
    storage.setItem(pendingKey('clear'), operationId);
    return waitForOperation(await serverApi.clear(operationId), operationId, 'clear');
  }).then((status) => parseClearMemory(status.result)).finally(() => { if (activeClear === running) activeClear = null; });
  activeClear = running;
  return running;
}

/** Admission and completion belong to the service, including after this device disconnects. */
export async function confirmCenterRestore(candidateId: string): Promise<void> {
  if (activeMaintenance) throw new Error('Another maintenance operation is running');
  await ownMaintenance('restore', async () => {
    centerLocalStorage().setItem(pendingKey('restore'), candidateId);
    return waitForOperation(await serverApi.restore(candidateId), candidateId, 'restore');
  });
}

/** Observe receipts by identity; reconnect never silently resubmits a destructive request. */
export async function recoverPendingCenterMaintenance(retryFailed = false): Promise<boolean> {
  if (activeMaintenance) { await activeMaintenance; return true; }
  const status = await serverApi.maintenance();
  const running = !['idle', 'completed'].includes(status.phase);
  const localKind: Kind | null = centerLocalStorage().getItem(pendingKey('clear')) ? 'clear'
    : centerLocalStorage().getItem(pendingKey('restore')) ? 'restore' : null;
  if (running || localKind) {
    const kind = running ? status.kind : localKind;
    const id = running ? status.operation_id : localKind && centerLocalStorage().getItem(pendingKey(localKind));
    if (!kind || !id) throw new Error('Center maintenance identity is missing');
    await ownMaintenance(kind, async () => {
      // Only an explicit retry may publish an operation whose first response was lost.
      const initial = retryFailed
        ? await (kind === 'clear' ? serverApi.clear(id) : serverApi.restore(id))
        : status.operation_id === id ? status : await serverApi.operation(id);
      return waitForOperation(initial, id, kind);
    });
    return true;
  }
  try { await applyCenterEpochs(status); }
  catch (error) {
    dispatchAppEvent.centerMaintenance('clear', 'failed', error instanceof Error ? error.message : 'This device cleanup is incomplete');
    throw error;
  }
  return false;
}
