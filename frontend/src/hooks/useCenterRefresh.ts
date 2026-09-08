import { useEffect, useRef } from 'react';
import { subscribeCenterRefresh } from '@/realtime/center-refresh';

/** Reconcile read snapshots without replaying mutations or remounting an editor. */
export function useCenterRefresh(refresh: () => Promise<unknown> | void, enabled = true): void {
  const latest = useRef(refresh);
  latest.current = refresh;
  useEffect(() => {
    if (!enabled) return;
    let active = true;
    let running = false;
    let queued = false;
    const reconcile = async () => {
      if (!active) return;
      if (running) { queued = true; return; }
      running = true;
      try {
        do {
          queued = false;
          try { await latest.current(); }
          catch { /* The owning loader reports read errors and retains its snapshot. */ }
        } while (queued && active);
      } finally { running = false; }
    };
    const unsubscribe = subscribeCenterRefresh(() => { void reconcile(); });
    return () => { active = false; unsubscribe(); };
  }, [enabled]);
}
