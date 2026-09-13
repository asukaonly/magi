import { useEffect } from 'react';
import { useNotificationStore } from '@/stores/notifications';
import { subscribeCenterRefresh } from '@/realtime/center-refresh';

let subscribers = 0;
let unsubscribe: (() => void) | undefined;
let running = false;
let queued = false;

/** One read-model owner for the bell and notification panel together. */
async function reconcile(): Promise<void> {
  if (running) { queued = true; return; }
  running = true;
  try {
    do {
      queued = false;
      await useNotificationStore.getState().refresh();
    } while (queued && subscribers > 0);
  } finally { running = false; }
}

export function useNotifications() {
  const store = useNotificationStore();
  useEffect(() => {
    subscribers += 1;
    if (subscribers === 1) {
      const refresh = () => { void reconcile().catch(() => undefined); };
      unsubscribe = subscribeCenterRefresh(refresh);
      refresh();
    }
    return () => {
      subscribers -= 1;
      if (subscribers === 0) { unsubscribe?.(); unsubscribe = undefined; queued = false; }
    };
  }, []);
  return store;
}
