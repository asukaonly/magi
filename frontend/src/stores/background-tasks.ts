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

  /** Replace the entire cache with a fresh snapshot from the list endpoint. */
  hydrate: (tasks: BackgroundTaskDTO[], activeCount: number) => void;
  /** Apply a realtime state update (always the authoritative task record). */
  upsert: (task: BackgroundTaskDTO) => void;
  /** Drop a task after a successful dismiss. */
  remove: (taskId: string) => void;
  /** Reset to an empty state (used on sign-out / session change). */
  reset: () => void;
}

const ACTIVE_STATUSES: ReadonlyArray<BackgroundTaskStatus> = [
  'pending',
  'running',
  'cancelling',
];

const countActive = (tasks: Record<string, BackgroundTaskDTO>): number => {
  let count = 0;
  for (const task of Object.values(tasks)) {
    if (ACTIVE_STATUSES.includes(task.status)) {
      count += 1;
    }
  }
  return count;
};

export const useBackgroundTaskStore = create<BackgroundTaskState>((set) => ({
  tasksById: {},
  orderedIds: [],
  activeCount: 0,
  lastRefreshedAt: 0,

  hydrate: (tasks, activeCount) =>
    set(() => {
      const tasksById: Record<string, BackgroundTaskDTO> = {};
      const orderedIds: string[] = [];
      for (const task of tasks) {
        tasksById[task.task_id] = task;
        orderedIds.push(task.task_id);
      }
      return {
        tasksById,
        orderedIds,
        activeCount,
        lastRefreshedAt: Date.now(),
      };
    }),

  upsert: (task) =>
    set((state) => {
      const tasksById = { ...state.tasksById, [task.task_id]: task };
      const existing = state.orderedIds.includes(task.task_id);
      const orderedIds = existing
        ? state.orderedIds
        : [task.task_id, ...state.orderedIds];
      return {
        tasksById,
        orderedIds,
        activeCount: countActive(tasksById),
      };
    }),

  remove: (taskId) =>
    set((state) => {
      if (!(taskId in state.tasksById)) {
        return state;
      }
      const { [taskId]: _removed, ...rest } = state.tasksById;
      return {
        tasksById: rest,
        orderedIds: state.orderedIds.filter((id) => id !== taskId),
        activeCount: countActive(rest),
      };
    }),

  reset: () => set({ tasksById: {}, orderedIds: [], activeCount: 0, lastRefreshedAt: 0 }),
}));

/** Returns all tasks in the current newest-first order. */
export const selectOrderedBackgroundTasks = (state: BackgroundTaskState): BackgroundTaskDTO[] => {
  return state.orderedIds
    .map((id) => state.tasksById[id])
    .filter((task): task is BackgroundTaskDTO => Boolean(task));
};
