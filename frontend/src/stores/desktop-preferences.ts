import { create } from 'zustand';

/** Keep an unapplied system preference visible across settings dialog lifetimes. */
export const useDesktopPreferencesStore = create<{ autoStartSyncFailed: boolean }>(() => ({
  autoStartSyncFailed: false,
}));
