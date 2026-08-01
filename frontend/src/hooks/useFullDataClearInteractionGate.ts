import { useCallback, useEffect, useState } from 'react';

import { APP_EVENTS, subscribeToAppEvent } from '@/constants/events';

export type FullDataClearInteractionGate =
  | { status: 'idle'; message: null }
  | { status: 'running'; message: null }
  | { status: 'failed'; message: string };

const IDLE_GATE: FullDataClearInteractionGate = {
  status: 'idle',
  message: null,
};

export function useFullDataClearInteractionGate(): {
  gate: FullDataClearInteractionGate;
  markRetrying: () => void;
} {
  const [gate, setGate] = useState<FullDataClearInteractionGate>(IDLE_GATE);

  useEffect(() => {
    const unsubscribeStarted = subscribeToAppEvent(
      APP_EVENTS.MEMORY_CLEAR_STARTED,
      () => setGate({ status: 'running', message: null }),
    );
    const unsubscribeFailed = subscribeToAppEvent(
      APP_EVENTS.MEMORY_CLEAR_FAILED,
      (event) => {
        const detail = (event as CustomEvent<{ message?: unknown }>).detail;
        const message = typeof detail?.message === 'string' && detail.message.trim()
          ? detail.message
          : 'Full data clear remains incomplete';
        setGate({ status: 'failed', message });
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
      unsubscribeStarted();
      unsubscribeFailed();
      unsubscribeCompleted();
      unsubscribeRecoveryReleased();
    };
  }, []);

  const markRetrying = useCallback(() => {
    setGate({ status: 'running', message: null });
  }, []);

  return { gate, markRetrying };
}
