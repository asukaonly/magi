import { create } from 'zustand';

export interface RealtimeStoreState {
  connected: boolean;
  lastError: string | null;
  reconnectAttempts: number;
  lastEventType: string | null;
  setConnected: (connected: boolean) => void;
  setLastError: (message: string | null) => void;
  setReconnectAttempts: (attempts: number) => void;
  setLastEventType: (eventType: string | null) => void;
  reset: () => void;
}

export const useRealtimeStore = create<RealtimeStoreState>((set) => ({
  connected: false,
  lastError: null,
  reconnectAttempts: 0,
  lastEventType: null,
  setConnected: (connected) => set({ connected }),
  setLastError: (lastError) => set({ lastError }),
  setReconnectAttempts: (reconnectAttempts) => set({ reconnectAttempts }),
  setLastEventType: (lastEventType) => set({ lastEventType }),
  reset: () => set({
    connected: false,
    lastError: null,
    reconnectAttempts: 0,
    lastEventType: null,
  }),
}));
