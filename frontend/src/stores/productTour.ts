import { create } from 'zustand';
import { configApi } from '@/api/modules/config';
import { requireConfiguration } from '@/api/config-contract';

/**
 * Shared one-time first-run context prompt gate.
 *
 * MUST be a shared store (not per-component local state): the flag is read by
 * BOTH `MainLayout` (to mount/unmount the prompt) AND
 * `useChatSessionLifecycle` (to release the deferred persona opening once the
 * prompt finishes). With local state each consumer had its own copy, so
 * completing the prompt in MainLayout never reached the lifecycle hook and the
 * opening never fired. A single store makes the completion flip propagate to
 * every consumer.
 */
interface ProductTourState {
  completed: boolean;
  loaded: boolean;
  refresh: () => Promise<void>;
  markCompleted: () => Promise<void>;
}

export const useProductTourStore = create<ProductTourState>((set) => ({
  completed: true, // assume done until we learn otherwise (avoids a prompt flash)
  loaded: false,
  refresh: async () => {
    try {
      const response = await configApi.get();
      const done = requireConfiguration(response).preferences.product_tour_completed;
      set({ completed: done, loaded: true });
    } catch {
      set({ completed: true, loaded: true }); // on error, don't nag
    }
  },
  markCompleted: async () => {
    set({ completed: true }); // optimistic: propagates to ALL consumers and releases the opening
    try {
      const response = await configApi.get();
      const current = requireConfiguration(response);
      const next = structuredClone(current);
      next.preferences.product_tour_completed = true;
      requireConfiguration(await configApi.update(next));
    } catch (err) {
      console.warn('failed to persist product_tour_completed', err);
    }
  },
}));
