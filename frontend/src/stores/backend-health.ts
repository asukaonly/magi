import { create } from 'zustand';

export type BackendStatus = 'healthy' | 'degraded' | 'offline' | 'exited';

export interface BackendHealthDetails {
  runtimeStatus?: string | null;
  startupState?: string | null;
  deferredReason?: string | null;
  llmReady?: boolean | null;
  agentRuntimeReady?: boolean | null;
}

export interface BackendHealthState {
  status: BackendStatus;
  runtimeStatus: string | null;
  startupState: string | null;
  deferredReason: string | null;
  llmReady: boolean | null;
  agentRuntimeReady: boolean | null;
  lastCheckedAt: number | null;
  setHealth: (status: BackendStatus, details?: BackendHealthDetails) => void;
}

export const useBackendHealthStore = create<BackendHealthState>((set) => ({
  status: 'healthy',
  runtimeStatus: null,
  startupState: null,
  deferredReason: null,
  llmReady: null,
  agentRuntimeReady: null,
  lastCheckedAt: null,
  setHealth: (status, details = {}) =>
    set({
      status,
      runtimeStatus: details.runtimeStatus ?? null,
      startupState: details.startupState ?? null,
      deferredReason: details.deferredReason ?? null,
      llmReady: details.llmReady ?? null,
      agentRuntimeReady: details.agentRuntimeReady ?? null,
      lastCheckedAt: Date.now(),
    }),
}));
