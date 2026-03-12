import { create } from 'zustand';

export interface RealtimeStoreState {
  connected: boolean;
  lastError: string | null;
  reconnectAttempts: number;
  setConnected: (connected: boolean) => void;
  setLastError: (message: string | null) => void;
  setReconnectAttempts: (attempts: number) => void;
  reset: () => void;
}

export const useRealtimeStore = create<RealtimeStoreState>((set) => ({
  connected: false,
  lastError: null,
  reconnectAttempts: 0,
  setConnected: (connected) => set({ connected }),
  setLastError: (lastError) => set({ lastError }),
  setReconnectAttempts: (reconnectAttempts) => set({ reconnectAttempts }),
  reset: () => set({
    connected: false,
    lastError: null,
    reconnectAttempts: 0,
  }),
}));
