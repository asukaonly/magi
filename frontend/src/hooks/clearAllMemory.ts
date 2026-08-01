import { memoryApi, type ClearMemoryResponse } from '@/api/modules/memory';
import { dispatchAppEvent } from '@/constants/events';
import {
  beginFullDataClear,
  clearDesktopLogHistory,
  completeFullDataClear,
  readPendingFullDataClear,
  type PendingFullDataClear,
} from '@/runtime/desktop';
import { stopRuntimeForFullDataClearRecovery } from '@/runtime/config';
import { completeMemoryClear } from './chatRetryLifecycle';

let activeClear: Promise<ClearMemoryResponse> | null = null;

async function runPendingClear(
  pending: PendingFullDataClear,
): Promise<ClearMemoryResponse> {
  const transactionId = String(pending.transactionId || '').trim();
  if (!transactionId) {
    throw new Error('Desktop full data clear marker is invalid');
  }

  const clearBoundaryAtSeconds = Date.now() / 1000;
  const result = await memoryApi.clearAll(transactionId);
  if (!result.success || (result.warnings?.length ?? 0) > 0) {
    throw new Error('Backend full data clear was not completed');
  }

  const browserCleanup = completeMemoryClear({
    clearBoundaryAtSeconds,
    announce: false,
  });
  if (!browserCleanup.browserStateCleared) {
    throw new Error(
      `Browser full data clear was not completed: ${browserCleanup.failedScopes.join(', ')}`,
    );
  }

  const desktopLogResult = await clearDesktopLogHistory();
  if (!desktopLogResult || desktopLogResult.failedEntries > 0) {
    throw new Error('Desktop diagnostic log clear was not completed');
  }

  await completeFullDataClear(transactionId);
  dispatchAppEvent.memoryCleared();
  return result;
}

async function runPendingClearWithProductGate(
  pending: PendingFullDataClear,
  options: { gateAlreadyStarted?: boolean } = {},
): Promise<ClearMemoryResponse> {
  if (!options.gateAlreadyStarted) {
    dispatchAppEvent.memoryClearStarted();
  }
  try {
    return await runPendingClear(pending);
  } catch (error) {
    return failFullDataClear(error);
  }
}

async function failFullDataClear(error: unknown): Promise<never> {
  const message = error instanceof Error
    ? error.message
    : 'Full data clear remains incomplete';
  try {
    await stopRuntimeForFullDataClearRecovery();
  } catch {
    // The durable desktop marker still blocks normal startup even when the
    // current backend cannot be stopped cleanly.
  }
  dispatchAppEvent.memoryClearFailed(message);
  throw error;
}

function serializeClear(
  operation: () => Promise<ClearMemoryResponse>,
): Promise<ClearMemoryResponse> {
  if (activeClear) {
    return activeClear;
  }
  const running = operation();
  activeClear = running;
  void running.finally(() => {
    if (activeClear === running) {
      activeClear = null;
    }
  }).catch(() => undefined);
  return running;
}

export const clearAllMemory = async (): Promise<ClearMemoryResponse> => serializeClear(
  async () => {
    dispatchAppEvent.memoryClearStarted();
    let pending: PendingFullDataClear | undefined;
    try {
      pending = await beginFullDataClear();
      if (!pending) {
        throw new Error('Desktop full data clear owner is unavailable');
      }
    } catch (error) {
      return failFullDataClear(error);
    }
    return runPendingClearWithProductGate(pending, { gateAlreadyStarted: true });
  },
);

export const recoverPendingFullDataClear = async (): Promise<boolean> => {
  const pending = await readPendingFullDataClear();
  if (pending === undefined) {
    return false;
  }
  if (pending === null) {
    return false;
  }
  await serializeClear(() => runPendingClearWithProductGate(pending));
  return true;
};
