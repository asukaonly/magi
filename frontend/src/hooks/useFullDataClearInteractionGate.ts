import { useCallback, useEffect, useState } from 'react';

import { APP_EVENTS, subscribeToAppEvent } from '@/constants/events';

export type FullDataClearInteractionGate =
  | { status: 'idle'; message: null; kind: null }
  | { status: 'running'; message: null; kind: 'clear' | 'restore' }
  | { status: 'failed'; message: string; kind: 'clear' | 'restore' };

const IDLE_GATE: FullDataClearInteractionGate = {
  kind: null,
  status: 'idle',
  message: null,
};

export function useFullDataClearInteractionGate(): {
  gate: FullDataClearInteractionGate;
  markRetrying: () => void;
} {
  const [gate, setGate] = useState<FullDataClearInteractionGate>(IDLE_GATE);

  useEffect(() => {
    const unsubscribeMaintenance = subscribeToAppEvent(APP_EVENTS.CENTER_MAINTENANCE, (event) => {
      const raw: unknown = (event as CustomEvent<unknown>).detail;
      if (!raw || typeof raw !== 'object' || !('status' in raw)) return;
      if (raw.status === 'idle') { setGate(IDLE_GATE); return; }
      if (!('kind' in raw) || (raw.kind !== 'clear' && raw.kind !== 'restore')) return;
      if (raw.status === 'running') setGate({ status: 'running', kind: raw.kind, message: null });
      if (raw.status === 'failed' && 'message' in raw && typeof raw.message === 'string') setGate({ status: 'failed', kind: raw.kind, message: raw.message });
    });
    const unsubscribeStarted = subscribeToAppEvent(
      APP_EVENTS.MEMORY_CLEAR_STARTED,
      () => setGate({ status: 'running', message: null, kind: 'clear' }),
    );
    const unsubscribeFailed = subscribeToAppEvent(
      APP_EVENTS.MEMORY_CLEAR_FAILED,
      (event) => {
        const detail = (event as CustomEvent<{ message?: unknown }>).detail;
        const message = typeof detail?.message === 'string' && detail.message.trim()
          ? detail.message
          : 'Full data clear remains incomplete';
        setGate({ status: 'failed', message, kind: 'clear' });
      },
    );
    const unsubscribeCompleted = subscribeToAppEvent(
      APP_EVENTS.MEMORY_CLEARED,
      () => setGate(IDLE_GATE),
    );
    const unsubscribeRecoveryReleased = subscribeToAppEvent(
      APP_EVENTS.MEMORY_CLEAR_RECOVERY_RELEASED,
      () => setGate(IDLE_GATE),
    );

    return () => {
      unsubscribeMaintenance();
      unsubscribeStarted();
      unsubscribeFailed();
      unsubscribeCompleted();
      unsubscribeRecoveryReleased();
    };
  }, []);

  const markRetrying = useCallback(() => {
    setGate((current) => ({ status: 'running', message: null, kind: current.kind ?? 'clear' }));
  }, []);

  return { gate, markRetrying };
}
