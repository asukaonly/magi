import { create } from 'zustand';
import type { ExecutionTraceSnapshot } from '@/api';
import type { NormalizedExecutionTraceSummary } from '@/domain/chat/state';

interface ChatTraceState {
  summaries: Record<string, NormalizedExecutionTraceSummary>;
  snapshots: Record<string, ExecutionTraceSnapshot>;
  drawerOpen: boolean;
  activeTurnId: string | null;
  upsertSummary: (summary: NormalizedExecutionTraceSummary) => void;
  replaceSummaries: (summaries: NormalizedExecutionTraceSummary[]) => void;
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
        [summary.turnId]: summary,
      },
    })),
  replaceSummaries: (summaries) =>
    set((state) => ({
      summaries: Object.fromEntries(summaries.map((summary) => [summary.turnId, summary])),
      snapshots: state.snapshots,
      drawerOpen: state.drawerOpen,
      activeTurnId: state.activeTurnId,
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
