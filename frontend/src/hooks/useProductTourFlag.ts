import { useCallback, useEffect, useState } from 'react';
import { configApi } from '@/api/modules/config';

/** One-time gate for the post-onboarding product tour. Mirrors useFirstConversationFlag. */
export function useProductTourFlag() {
  const [completed, setCompleted] = useState(true); // assume done until we learn otherwise (no flash)
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const response = await configApi.get();
        const done = Boolean((response as any)?.data?.preferences?.product_tour_completed);
        if (!cancelled) setCompleted(done);
      } catch {
        if (!cancelled) setCompleted(true); // on error, don't nag
      } finally {
        if (!cancelled) setLoaded(true);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const markCompleted = useCallback(async () => {
    setCompleted(true); // optimistic
    try {
      const response = await configApi.get();
      const current = (response as any)?.data;
      if (!current) return;
      const next = structuredClone(current);
      if (!next.preferences) next.preferences = {};
      next.preferences.product_tour_completed = true;
      await configApi.update(next);
    } catch (err) {
      console.warn('failed to persist product_tour_completed', err);
    }
  }, []);

  return { completed, loaded, markCompleted };
}
