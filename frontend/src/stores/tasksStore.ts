/**
 * Tasks状态管理
 */
import { create } from 'zustand';
import { Task, tasksApi } from '../api';

interface TasksState {
  tasks: Task[];
  selectedTask: Task | null;
  stats: any;
  loading: boolean;
  error: string | null;

  // Actions
  fetchTasks: (params?: any) => Promise<void>;
  fetchTask: (id: string) => Promise<void>;
  createTask: (data: any) => Promise<void>;
  retryTask: (id: string, retryCount?: number) => Promise<void>;
  deleteTask: (id: string) => Promise<void>;
  fetchStats: () => Promise<void>;
  setSelectedTask: (task: Task | null) => void;
}

export const useTasksStore = create<TasksState>((set, get) => ({
  tasks: [],
  selectedTask: null,
  stats: null,
  loading: false,
  error: null,

  fetchTasks: async (params) => {
    set({ loading: true, error: null });
    try {
      const response = await tasksApi.list(params);
      set({ tasks: response.data || [], loading: false });
    } catch (error: any) {
      set({ error: error.message || 'Failed to fetch tasks', loading: false });
    }
  },

  fetchTask: async (id: string) => {
    set({ loading: true, error: null });
    try {
      const response = await tasksApi.get(id);
      set({ selectedTask: response.data, loading: false });
    } catch (error: any) {
      set({ error: error.message || 'Failed to fetch task', loading: false });
    }
  },

  createTask: async (data) => {
    set({ loading: true, error: null });
    try {
      const response = await tasksApi.create(data);
      const newTask = response.data;
      set((state) => ({
        tasks: [newTask, ...state.tasks],
        loading: false,
      }));
      return newTask;
    } catch (error: any) {
      set({ error: error.message || 'Failed to create task', loading: false });
      throw error;
    }
  },

  retryTask: async (id, retryCount = 1) => {
    set({ loading: true, error: null });
    try {
      const response = await tasksApi.retry(id, { retry_count: retryCount });
      // 重新获取任务列表
      await get().fetchTasks();
      set({ loading: false });
    } catch (error: any) {
      set({ error: error.message || 'Failed to retry task', loading: false });
      throw error;
    }
  },

  deleteTask: async (id) => {
    set({ loading: true, error: null });
    try {
      await tasksApi.delete(id);
      set((state) => ({
        tasks: state.tasks.filter((t) => t.id !== id),
        selectedTask: state.selectedTask?.id === id ? null : state.selectedTask,
        loading: false,
      }));
    } catch (error: any) {
      set({ error: error.message || 'Failed to delete task', loading: false });
      throw error;
    }
  },

  fetchStats: async () => {
    try {
      const response = await tasksApi.getStats();
      set({ stats: response.data });
    } catch (error: any) {
      console.error('Failed to fetch task stats:', error);
    }
  },

  setSelectedTask: (task) => {
    set({ selectedTask: task });
  },
}));
