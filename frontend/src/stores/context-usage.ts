import { create } from 'zustand';

export interface ContextUsageSnapshot {
  turnId: string | null;
  usedTokens: number;
  windowSize: number;
  inputCapacity: number;
  threshold: number;
  measurement: 'actual' | 'estimated';
  modelProvider: string | null;
  modelId: string | null;
  updatedAt: number;
}

export interface ContextUsagePayload {
  turn_id?: string | null;
  used_tokens: number;
  window_size: number;
  input_capacity?: number;
  threshold: number;
  measurement?: 'actual' | 'estimated';
  model_provider?: string | null;
  model_id?: string | null;
  updated_at_ms?: number;
  timestamp?: number;
}

interface ContextUsageState {
  /** Latest context usage per session. */
  usage: Record<string, ContextUsageSnapshot>;
  update: (sessionId: string, data: ContextUsagePayload) => void;
  clear: (sessionId: string) => void;
  reset: () => void;
}

export const useContextUsageStore = create<ContextUsageState>((set) => ({
  usage: {},
  update: (sessionId, data) =>
    set((state) => {
      if (
        !Number.isFinite(data.used_tokens)
        || data.used_tokens <= 0
        || !Number.isFinite(data.window_size)
        || data.window_size <= 0
      ) {
        return state;
      }
      const serverTimestamp = Number(data.updated_at_ms);
      const eventTimestamp = Number(data.timestamp);
      const updatedAt = Number.isFinite(serverTimestamp) && serverTimestamp > 0
        ? serverTimestamp
        : Number.isFinite(eventTimestamp) && eventTimestamp > 0
          ? eventTimestamp * 1000
          : Date.now();
      const previous = state.usage[sessionId];
      if (previous && previous.updatedAt > updatedAt) {
        return state;
      }
      return {
        usage: {
          ...state.usage,
          [sessionId]: {
            turnId: String(data.turn_id || '').trim() || null,
            usedTokens: data.used_tokens,
            windowSize: data.window_size,
            inputCapacity: data.input_capacity || data.window_size,
            threshold: data.threshold,
            measurement: data.measurement === 'estimated' ? 'estimated' : 'actual',
            modelProvider: String(data.model_provider || '').trim() || null,
            modelId: String(data.model_id || '').trim() || null,
            updatedAt,
          },
        },
      };
    }),
  clear: (sessionId) =>
    set((state) => {
      const { [sessionId]: _, ...rest } = state.usage;
      return { usage: rest };
    }),
  reset: () => set({ usage: {} }),
}));
