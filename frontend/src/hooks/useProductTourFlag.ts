import { useEffect } from 'react';
import { useProductTourStore } from '@/stores/productTour';

/**
 * One-time gate for the post-onboarding first context prompt. Thin wrapper over
 * the shared `useProductTourStore` so that completing the prompt in one consumer
 * (MainLayout) propagates to every other consumer (useChatSessionLifecycle,
 * which releases the deferred persona opening). Returns the same shape callers
 * already use: { completed, loaded, markCompleted }.
 */
export function useProductTourFlag() {
  const completed = useProductTourStore((s) => s.completed);
  const loaded = useProductTourStore((s) => s.loaded);
  const refresh = useProductTourStore((s) => s.refresh);
  const markCompleted = useProductTourStore((s) => s.markCompleted);

  useEffect(() => {
    if (!loaded) void refresh();
  }, [loaded, refresh]);

  return { completed, loaded, markCompleted };
}
