/**
 * 任务管理API
 */
import { api } from '../client';

// 类型定义
export interface Task {
  id: string;
  type: string;
  data: Record<string, any>;
  priority: 'low' | 'normal' | 'high';
  status: 'pending' | 'running' | 'completed' | 'failed';
  assignee?: string;
  created_at: string;
  updated_at?: string;
}

export interface TaskCreateRequest {
  type: string;
  data?: Record<string, any>;
  priority?: 'low' | 'normal' | 'high';
  assignee?: string;
}

export interface TaskRetryRequest {
  retry_count?: number;
}

export interface TaskStats {
  total: number;
  pending: number;
  running: number;
  completed: number;
  failed: number;
}

// API方法
export const tasksApi = {
  // 获取任务列表
  list: (params?: {
    status?: string;
    priority?: string;
    assignee?: string;
    limit?: number;
    offset?: number;
  }) => api.get<Task[]>('/tasks', params),

  // 获取任务详情
  get: (taskId: string) => api.get<Task>(`/tasks/${taskId}`),

  // 创建任务
  create: (data: TaskCreateRequest) => api.post<Task>('/tasks', data),

  // 重试任务
  retry: (taskId: string, data?: TaskRetryRequest) =>
    api.post<{ success: boolean; message: string; data: any }>(`/tasks/${taskId}/retry`, data || {}),

  // 删除任务
  delete: (taskId: string) => api.delete(`/tasks/${taskId}`),

  // 获取任务统计
  getStats: () => api.get<TaskStats>('/tasks/stats/summary'),
};

export default tasksApi;
