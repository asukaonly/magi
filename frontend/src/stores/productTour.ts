import { create } from 'zustand';
import { configApi } from '@/api/modules/config';

/**
 * Shared one-time product-tour gate.
 *
 * MUST be a shared store (not per-component local state): the flag is read by
 * BOTH `MainLayout` (to mount/unmount the tour) AND `useChatSessionLifecycle`
 * (to release the deferred persona opening once the tour finishes). With local
 * state each consumer had its own copy, so completing the tour in MainLayout
 * never reached the lifecycle hook and the opening never fired. A single store
 * makes the completion flip propagate to every consumer.
 */
interface ProductTourState {
  completed: boolean;
  loaded: boolean;
  refresh: () => Promise<void>;
  markCompleted: () => Promise<void>;
}

export const useProductTourStore = create<ProductTourState>((set) => ({
  completed: true, // assume done until we learn otherwise (avoids a flash of the tour)
  loaded: false,
  refresh: async () => {
    try {
      const response = await configApi.get();
      const done = Boolean((response as any)?.data?.preferences?.product_tour_completed);
      set({ completed: done, loaded: true });
    } catch {
      set({ completed: true, loaded: true }); // on error, don't nag
    }
  },
  markCompleted: async () => {
    set({ completed: true }); // optimistic — propagates to ALL consumers (releases the opening)
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
  },
}));
