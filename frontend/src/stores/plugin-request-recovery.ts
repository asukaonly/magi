import { create } from 'zustand';

export interface PluginRequestRecovery {
  operationId: string;
  path: string;
  resolve: () => Promise<'closed' | 'available'>;
}

interface RecoveryState {
  request: PluginRequestRecovery | null;
  closed: { path: string; operationId: string } | null;
  show: (request: PluginRequestRecovery) => void;
  dismiss: () => void;
  finish: (request: PluginRequestRecovery, result: 'closed' | 'available') => void;
  reset: () => void;
}

/** One visible recovery owner; no request body or credentials enter this store. */
export const usePluginRequestRecoveryStore = create<RecoveryState>((set) => ({
  request: null,
  closed: null,
  show: (request) => set({ request }),
  dismiss: () => set({ request: null }),
  finish: (request, result) => set((state) => ({
    request: state.request?.operationId === request.operationId ? null : state.request,
    closed: result === 'closed' ? { path: request.path, operationId: request.operationId } : state.closed,
  })),
  reset: () => set({ request: null, closed: null }),
}));
