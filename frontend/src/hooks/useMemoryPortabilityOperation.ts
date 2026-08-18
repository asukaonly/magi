import { useCallback, useEffect, useRef, useState } from 'react';

import {
  memoryPortabilityApi,
  type MemoryPortabilityOperation,
} from '@/api/modules/memoryPortability';
import { isTransientPortabilityError } from '@/components/settings/memory-data/presentation';

const OPERATION_POLL_INTERVAL_MS = 1_500;

const isActiveOperation = (operation: MemoryPortabilityOperation | null): boolean =>
  operation?.status === 'pending' || operation?.status === 'running';

interface UseMemoryPortabilityOperationOptions {
  onRestoreSucceeded?: () => void;
}

export function useMemoryPortabilityOperation({
  onRestoreSucceeded,
}: UseMemoryPortabilityOperationOptions = {}) {
  const [operation, setOperation] = useState<MemoryPortabilityOperation | null>(null);
  const [loadingActiveOperation, setLoadingActiveOperation] = useState(true);
  const [pollingInterrupted, setPollingInterrupted] = useState(false);
  const onRestoreSucceededRef = useRef(onRestoreSucceeded);
  const notifiedRestoreIdsRef = useRef(new Set<string>());

  useEffect(() => {
    onRestoreSucceededRef.current = onRestoreSucceeded;
  }, [onRestoreSucceeded]);

  useEffect(() => {
    let cancelled = false;
    void memoryPortabilityApi.getActiveOperation()
      .then((activeOperation) => {
        if (!cancelled) {
          setOperation(activeOperation);
        }
      })
      .catch(() => {
        // The backend remains the authority for operation exclusivity.
      })
      .finally(() => {
        if (!cancelled) {
          setLoadingActiveOperation(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

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
        setPollingInterrupted(false);
        setOperation(nextOperation);
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
  }, [operationId, operationStatus]);

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
    setPollingInterrupted(false);
    setOperation(nextOperation);
  }, []);

  const clearOperation = useCallback(() => {
    setPollingInterrupted(false);
    setOperation(null);
  }, []);

  return {
    operation,
    busy: isActiveOperation(operation),
    loadingActiveOperation,
    pollingInterrupted,
    trackOperation,
    clearOperation,
  };
}

