import { create } from 'zustand';

export interface ContextUsageSnapshot {
  usedTokens: number;
  windowSize: number;
  threshold: number;
  updatedAt: number;
}

interface ContextUsageState {
  /** Latest context usage per session. */
  usage: Record<string, ContextUsageSnapshot>;
  update: (sessionId: string, data: { used_tokens: number; window_size: number; threshold: number }) => void;
  clear: (sessionId: string) => void;
  reset: () => void;
}

export const useContextUsageStore = create<ContextUsageState>((set) => ({
  usage: {},
  update: (sessionId, data) =>
    set((state) => ({
      usage: {
        ...state.usage,
        [sessionId]: {
          usedTokens: data.used_tokens,
          windowSize: data.window_size,
          threshold: data.threshold,
          updatedAt: Date.now(),
        },
      },
    })),
  clear: (sessionId) =>
    set((state) => {
      const { [sessionId]: _, ...rest } = state.usage;
      return { usage: rest };
    }),
  reset: () => set({ usage: {} }),
}));
