import { create } from 'zustand';
import type { ExecutionTraceSnapshot, ExecutionTraceSummary } from '@/api';

interface ChatTraceState {
  summaries: Record<string, ExecutionTraceSummary>;
  snapshots: Record<string, ExecutionTraceSnapshot>;
  drawerOpen: boolean;
  activeTurnId: string | null;
  upsertSummary: (summary: ExecutionTraceSummary) => void;
  setSnapshot: (snapshot: ExecutionTraceSnapshot) => void;
  openDrawer: (turnId: string) => void;
  closeDrawer: () => void;
  reset: () => void;
}

export const useChatTraceStore = create<ChatTraceState>((set) => ({
  summaries: {},
  snapshots: {},
  drawerOpen: false,
  activeTurnId: null,
  upsertSummary: (summary) =>
    set((state) => ({
      summaries: {
        ...state.summaries,
        [summary.turn_id]: summary,
      },
    })),
  setSnapshot: (snapshot) =>
    set((state) => ({
      snapshots: {
        ...state.snapshots,
        [snapshot.turn_id]: snapshot,
      },
    })),
  openDrawer: (activeTurnId) => set({ activeTurnId, drawerOpen: true }),
  closeDrawer: () => set({ activeTurnId: null, drawerOpen: false }),
  reset: () =>
    set({
      summaries: {},
      snapshots: {},
      drawerOpen: false,
      activeTurnId: null,
    }),
}));
