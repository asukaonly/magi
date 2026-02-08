/**
 * 记忆管理API
 */
import { api } from '../client';

// 类型定义
export interface Memory {
  id: string;
  type: 'self' | 'other';
  content: Record<string, any>;
  metadata: Record<string, any>;
  created_at: string;
  updated_at?: string;
}

export interface MemorySearchRequest {
  query: string;
  memory_type?: string;
  limit?: number;
}

export interface MemorySearchResult {
  success: boolean;
  data: Memory[];
  total: number;
}

export interface MemoryStats {
  total: number;
  self: number;
  other: number;
}

// API方法
export const memoryApi = {
  // 获取记忆列表
  list: (params?: { memory_type?: string; limit?: number; offset?: number }) =>
    api.get<Memory[]>('/memory', params),

  // 获取记忆详情
  get: (memoryId: string) => api.get<Memory>(`/memory/${memoryId}`),

  // 搜索记忆
  search: (data: MemorySearchRequest) =>
    api.post<MemorySearchResult>('/memory/search', data),

  // 删除记忆
  delete: (memoryId: string) => api.delete(`/memory/${memoryId}`),

  // 获取记忆统计
  getStats: () => api.get<MemoryStats>('/memory/stats/summary'),
};

export default memoryApi;
