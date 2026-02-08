/**
 * Agent管理API
 */
import { api, PaginatedResponse } from '../client';

// 类型定义
export interface Agent {
  id: string;
  name: string;
  agent_type: 'master' | 'task' | 'worker';
  state: 'stopped' | 'starting' | 'running' | 'stopping' | 'error';
  config: Record<string, any>;
  created_at: string;
  updated_at?: string;
}

export interface AgentCreateRequest {
  name: string;
  agent_type: 'master' | 'task' | 'worker';
  config?: Record<string, any>;
}

export interface AgentUpdateRequest {
  name?: string;
  config?: Record<string, any>;
}

export interface AgentActionRequest {
  action: 'start' | 'stop' | 'restart';
}

export interface AgentStats {
  agent_id: string;
  pending_tasks: number;
  completed_tasks: number;
  failed_tasks: number;
  average_processing_time: number;
}

// API方法
export const agentsApi = {
  // 获取Agent列表
  list: (params?: { agent_type?: string; state?: string; limit?: number; offset?: number }) =>
    api.get<Agent[]>('/agents', params),

  // 获取Agent详情
  get: (agentId: string) =>
    api.get<Agent>(`/agents/${agentId}`),

  // 创建Agent
  create: (data: AgentCreateRequest) =>
    api.post<Agent>('/agents', data),

  // 更新Agent
  update: (agentId: string, data: AgentUpdateRequest) =>
    api.put<Agent>(`/agents/${agentId}`, data),

  // 删除Agent
  delete: (agentId: string) =>
    api.delete(`/agents/${agentId}`),

  // Agent操作（启动/停止/重启）
  action: (agentId: string, data: AgentActionRequest) =>
    api.post<{ success: boolean; message: string; data: Agent }>(`/agents/${agentId}/action`, data),

  // 获取Agent统计信息
  getStats: (agentId: string) =>
    api.get<AgentStats>(`/agents/${agentId}/stats`),
};

export default agentsApi;
