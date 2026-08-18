import { useCallback, useEffect, useRef, useState } from 'react';

import {
  memoryPortabilityApi,
  type MemoryPortabilityOperation,
  type MemoryPortabilityOperationKind,
} from '@/api/modules/memoryPortability';
import { isTransientPortabilityError } from '@/components/settings/memory-data/presentation';

const OPERATION_POLL_INTERVAL_MS = 1_500;
const OPERATION_TRACKING_KEY = 'magi_memory_portability_operation_v1';

interface PersistedOperationTracking {
  version: 1;
  trackedOperationId: string | null;
  dismissedOperationId: string | null;
}

interface OperationDiscovery {
  active: MemoryPortabilityOperation | null | undefined;
  latest: MemoryPortabilityOperation | null | undefined;
  tracked: MemoryPortabilityOperation | null | undefined;
  transientFailure: boolean;
}

const isActiveOperation = (operation: MemoryPortabilityOperation | null): boolean =>
  operation?.status === 'pending' || operation?.status === 'running';

function readPersistedTracking(): PersistedOperationTracking {
  const empty: PersistedOperationTracking = {
    version: 1,
    trackedOperationId: null,
    dismissedOperationId: null,
  };
  try {
    const raw = window.localStorage.getItem(OPERATION_TRACKING_KEY);
    if (!raw) {
      return empty;
    }
    const parsed = JSON.parse(raw) as Partial<PersistedOperationTracking>;
    if (parsed.version !== 1) {
      return empty;
    }
    return {
      version: 1,
      trackedOperationId: typeof parsed.trackedOperationId === 'string'
        ? parsed.trackedOperationId
        : null,
      dismissedOperationId: typeof parsed.dismissedOperationId === 'string'
        ? parsed.dismissedOperationId
        : null,
    };
  } catch {
    return empty;
  }
}

function persistTracking(tracking: PersistedOperationTracking): void {
  try {
    window.localStorage.setItem(OPERATION_TRACKING_KEY, JSON.stringify(tracking));
  } catch {
    // Tracking is a convenience; the backend remains the operation authority.
  }
}

function settledValue<T>(result: PromiseSettledResult<T>): T | undefined {
  return result.status === 'fulfilled' ? result.value : undefined;
}

async function discoverOperations(trackedOperationId: string | null): Promise<OperationDiscovery> {
  const trackedRequest = trackedOperationId
    ? memoryPortabilityApi.getOperation(trackedOperationId)
    : Promise.resolve(null);
  const results = await Promise.allSettled([
    memoryPortabilityApi.getActiveOperation(),
    memoryPortabilityApi.getLatestOperation(),
    trackedRequest,
  ]);
  return {
    active: settledValue(results[0]),
    latest: settledValue(results[1]),
    tracked: settledValue(results[2]),
    transientFailure: results.some(
      (result) => result.status === 'rejected' && isTransientPortabilityError(result.reason),
    ),
  };
}

function recoveredOperation(
  discovery: OperationDiscovery,
  dismissedOperationId: string | null,
): MemoryPortabilityOperation | null | undefined {
  if (discovery.active) {
    return discovery.active;
  }
  if (discovery.latest !== undefined) {
    return discovery.latest?.operation_id === dismissedOperationId
      ? null
      : discovery.latest;
  }
  if (discovery.tracked && discovery.tracked.operation_id !== dismissedOperationId) {
    return discovery.tracked;
  }
  return undefined;
}

interface UseMemoryPortabilityOperationOptions {
  onRestoreSucceeded?: () => void;
}

export function useMemoryPortabilityOperation({
  onRestoreSucceeded,
}: UseMemoryPortabilityOperationOptions = {}) {
  const [initialTracking] = useState(readPersistedTracking);
  const [operation, setOperation] = useState<MemoryPortabilityOperation | null>(null);
  const [loadingActiveOperation, setLoadingActiveOperation] = useState(true);
  const [pollingInterrupted, setPollingInterrupted] = useState(false);
  const operationRef = useRef<MemoryPortabilityOperation | null>(null);
  const trackedOperationIdRef = useRef(initialTracking.trackedOperationId);
  const dismissedOperationIdRef = useRef(initialTracking.dismissedOperationId);
  const knownLatestOperationIdRef = useRef<string | null>(null);
  const latestOperationKnownRef = useRef(false);
  const onRestoreSucceededRef = useRef(onRestoreSucceeded);
  const notifiedRestoreIdsRef = useRef(new Set<string>());

  useEffect(() => {
    onRestoreSucceededRef.current = onRestoreSucceeded;
  }, [onRestoreSucceeded]);

  const rememberOperation = useCallback((nextOperation: MemoryPortabilityOperation) => {
    operationRef.current = nextOperation;
    trackedOperationIdRef.current = nextOperation.operation_id;
    dismissedOperationIdRef.current = null;
    setPollingInterrupted(false);
    setOperation(nextOperation);
    persistTracking({
      version: 1,
      trackedOperationId: nextOperation.operation_id,
      dismissedOperationId: null,
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    let retryTimer: number | null = null;

    const recover = async (): Promise<void> => {
      const discovery = await discoverOperations(trackedOperationIdRef.current);
      if (cancelled) {
        return;
      }
      if (discovery.latest !== undefined) {
        latestOperationKnownRef.current = true;
        knownLatestOperationIdRef.current = discovery.latest?.operation_id ?? null;
      }
      const recovered = recoveredOperation(discovery, dismissedOperationIdRef.current);
      if (recovered !== undefined) {
        setLoadingActiveOperation(false);
        setPollingInterrupted(false);
        if (recovered) {
          rememberOperation(recovered);
        } else {
          operationRef.current = null;
          setOperation(null);
        }
        return;
      }
      setPollingInterrupted(discovery.transientFailure);
      retryTimer = window.setTimeout(() => void recover(), OPERATION_POLL_INTERVAL_MS);
    };

    void recover();
    return () => {
      cancelled = true;
      if (retryTimer !== null) {
        window.clearTimeout(retryTimer);
      }
    };
  }, [rememberOperation]);

  const operationId = operation?.operation_id ?? null;
  const operationStatus = operation?.status ?? null;

  useEffect(() => {
    if (!operationId || (operationStatus !== 'pending' && operationStatus !== 'running')) {
      return undefined;
    }

    let cancelled = false;
    let timer: number | null = null;

    const poll = async (): Promise<void> => {
      try {
        const nextOperation = await memoryPortabilityApi.getOperation(operationId);
        if (cancelled) {
          return;
        }
        rememberOperation(nextOperation);
        if (isActiveOperation(nextOperation)) {
          timer = window.setTimeout(() => void poll(), OPERATION_POLL_INTERVAL_MS);
        }
      } catch (error) {
        if (cancelled) {
          return;
        }
        setPollingInterrupted(true);
        const retryDelay = isTransientPortabilityError(error)
          ? OPERATION_POLL_INTERVAL_MS
          : OPERATION_POLL_INTERVAL_MS * 2;
        timer = window.setTimeout(() => void poll(), retryDelay);
      }
    };

    timer = window.setTimeout(() => void poll(), OPERATION_POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      if (timer !== null) {
        window.clearTimeout(timer);
      }
    };
  }, [operationId, operationStatus, rememberOperation]);

  useEffect(() => {
    if (
      !operation
      || operation.kind !== 'restore'
      || operation.status !== 'succeeded'
      || notifiedRestoreIdsRef.current.has(operation.operation_id)
    ) {
      return;
    }
    notifiedRestoreIdsRef.current.add(operation.operation_id);
    onRestoreSucceededRef.current?.();
  }, [operation]);

  const trackOperation = useCallback((nextOperation: MemoryPortabilityOperation) => {
    latestOperationKnownRef.current = true;
    knownLatestOperationIdRef.current = nextOperation.operation_id;
    rememberOperation(nextOperation);
  }, [rememberOperation]);

  const reconcileStartedOperation = useCallback(async (
    expectedKind: MemoryPortabilityOperationKind,
  ): Promise<MemoryPortabilityOperation | null> => {
    const previousLatestId = knownLatestOperationIdRef.current;
    const latestWasKnown = latestOperationKnownRef.current;
    const discovery = await discoverOperations(null);
    if (discovery.latest !== undefined) {
      latestOperationKnownRef.current = true;
      knownLatestOperationIdRef.current = discovery.latest?.operation_id ?? null;
    }
    const accepted = discovery.active?.kind === expectedKind
      ? discovery.active
      : discovery.latest?.kind === expectedKind
        && latestWasKnown
        && discovery.latest.operation_id !== previousLatestId
        ? discovery.latest
        : null;
    if (accepted) {
      rememberOperation(accepted);
    }
    return accepted;
  }, [rememberOperation]);

  const clearOperation = useCallback(() => {
    const dismissedOperationId = operationRef.current?.operation_id ?? null;
    if (isActiveOperation(operationRef.current)) {
      return;
    }
    dismissedOperationIdRef.current = dismissedOperationId;
    trackedOperationIdRef.current = null;
    operationRef.current = null;
    setPollingInterrupted(false);
    setOperation(null);
    persistTracking({
      version: 1,
      trackedOperationId: null,
      dismissedOperationId,
    });
  }, []);

  return {
    operation,
    busy: isActiveOperation(operation),
    loadingActiveOperation,
    pollingInterrupted,
    trackOperation,
    reconcileStartedOperation,
    clearOperation,
  };
}
