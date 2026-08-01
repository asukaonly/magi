import { create } from 'zustand';
import type { BackgroundTaskDTO, BackgroundTaskStatus } from '@/api';

/** Live cache of background-task state for the Tasks page and sidebar badge. */
interface BackgroundTaskState {
  /** Tasks indexed by ``task_id`` for O(1) upserts. */
  tasksById: Record<string, BackgroundTaskDTO>;
  /** Insertion/update order so the UI can render newest-first without re-sorting. */
  orderedIds: string[];
  /** ``active_count`` reported by the last list-refresh; kept in sync with upserts. */
  activeCount: number;
  /** Timestamp of the last successful refresh; ``0`` means never loaded. */
  lastRefreshedAt: number;
  clearBoundaryAt: number | null;
  retiredTaskIds: Record<string, true>;

  /** Replace the entire cache with a fresh snapshot from the list endpoint. */
  hydrate: (tasks: BackgroundTaskDTO[], activeCount: number) => void;
  /** Apply a realtime state update (always the authoritative task record). */
  upsert: (task: BackgroundTaskDTO) => boolean;
  /** Drop a task after a successful dismiss. */
  remove: (taskId: string) => void;
  /** Reset to an empty state (used on sign-out / session change). */
  reset: () => void;
  /** Clear content and permanently reject events belonging to the old boundary. */
  retireForMemoryClear: (clearBoundaryAt: number) => void;
}

const ACTIVE_STATUSES: ReadonlyArray<BackgroundTaskStatus> = [
  'pending',
  'running',
  'cancelling',
];

const isTaskAllowedAfterClear = (
  state: Pick<BackgroundTaskState, 'clearBoundaryAt' | 'retiredTaskIds'>,
  task: BackgroundTaskDTO,
): boolean => {
  if (state.clearBoundaryAt === null) {
    return true;
  }
  if (state.retiredTaskIds[task.task_id]) {
    return false;
  }
  const createdAt = Number(task.created_at);
  return Number.isFinite(createdAt) && createdAt > state.clearBoundaryAt;
};

export const useBackgroundTaskStore = create<BackgroundTaskState>((set) => ({
  tasksById: {},
  orderedIds: [],
  activeCount: 0,
  lastRefreshedAt: 0,
  clearBoundaryAt: null,
  retiredTaskIds: {},

  hydrate: (tasks, activeCount) =>
    set((state) => {
      const acceptedTasks = tasks.filter((task) => isTaskAllowedAfterClear(state, task));
      const tasksById: Record<string, BackgroundTaskDTO> = {};
      const orderedIds: string[] = [];
      for (const task of acceptedTasks) {
        tasksById[task.task_id] = task;
        orderedIds.push(task.task_id);
      }
      return {
        tasksById,
        orderedIds,
        activeCount: state.clearBoundaryAt === null
          ? activeCount
          : acceptedTasks.filter((task) => ACTIVE_STATUSES.includes(task.status)).length,
        lastRefreshedAt: Date.now(),
      };
    }),

  upsert: (task) => {
    let accepted = false;
    set((state) => {
      if (!isTaskAllowedAfterClear(state, task)) {
        return state;
      }
      accepted = true;
      const previous = state.tasksById[task.task_id];
      const wasActive = previous ? ACTIVE_STATUSES.includes(previous.status) : false;
      const isActive = ACTIVE_STATUSES.includes(task.status);
      const tasksById = { ...state.tasksById, [task.task_id]: task };
      const existing = state.orderedIds.includes(task.task_id);
      const orderedIds = existing
        ? state.orderedIds
        : [task.task_id, ...state.orderedIds];
      let activeCount = state.activeCount;
      if (!wasActive && isActive) {
        activeCount += 1;
      } else if (wasActive && !isActive) {
        activeCount = Math.max(0, activeCount - 1);
      }
      return {
        tasksById,
        orderedIds,
        activeCount,
      };
    });
    return accepted;
  },

  remove: (taskId) =>
    set((state) => {
      const existing = state.tasksById[taskId];
      if (!existing) {
        return state;
      }
      const { [taskId]: _removed, ...rest } = state.tasksById;
      return {
        tasksById: rest,
        orderedIds: state.orderedIds.filter((id) => id !== taskId),
        activeCount: ACTIVE_STATUSES.includes(existing.status)
          ? Math.max(0, state.activeCount - 1)
          : state.activeCount,
      };
    }),

  reset: () => set({
    tasksById: {},
    orderedIds: [],
    activeCount: 0,
    lastRefreshedAt: 0,
    clearBoundaryAt: null,
    retiredTaskIds: {},
  }),

  retireForMemoryClear: (clearBoundaryAt) => set((state) => {
    const normalizedBoundary = Number.isFinite(clearBoundaryAt)
      ? Math.max(0, clearBoundaryAt)
      : Date.now() / 1000;
    const retiredTaskIds = { ...state.retiredTaskIds };
    for (const taskId of state.orderedIds) {
      retiredTaskIds[taskId] = true;
    }
    return {
      tasksById: {},
      orderedIds: [],
      activeCount: 0,
      lastRefreshedAt: 0,
      clearBoundaryAt: normalizedBoundary,
      retiredTaskIds,
    };
  }),
}));

/** Returns all tasks in the current newest-first order. */
export const selectOrderedBackgroundTasks = (state: BackgroundTaskState): BackgroundTaskDTO[] => {
  return state.orderedIds
    .map((id) => state.tasksById[id])
    .filter((task): task is BackgroundTaskDTO => Boolean(task));
};
