import { create } from 'zustand';

export type BackendStatus = 'healthy' | 'degraded' | 'offline' | 'exited';

export interface BackendHealthState {
  status: BackendStatus;
  runtimeStatus: string | null;
  lastCheckedAt: number | null;
  setHealth: (status: BackendStatus, runtimeStatus?: string | null) => void;
}

export const useBackendHealthStore = create<BackendHealthState>((set) => ({
  status: 'healthy',
  runtimeStatus: null,
  lastCheckedAt: null,
  setHealth: (status, runtimeStatus = null) =>
    set({ status, runtimeStatus, lastCheckedAt: Date.now() }),
}));
