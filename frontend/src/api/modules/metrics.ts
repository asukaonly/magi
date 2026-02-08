/**
 * 指标监控API
 */
import { api } from '../client';

// 类型定义
export interface SystemMetrics {
  cpu_percent: number;
  memory_percent: number;
  memory_used: number;
  memory_total: number;
  disk_percent: number;
  disk_used: number;
  disk_total: number;
}

export interface AgentMetrics {
  agent_id: string;
  agent_name: string;
  state: string;
  pending_tasks: number;
  completed_tasks: number;
  failed_tasks: number;
  average_processing_time: number;
}

export interface PerformanceMetrics {
  total_requests: number;
  requests_per_second: number;
  average_response_time: number;
  error_rate: number;
  active_connections: number;
}

export interface HealthStatus {
  status: 'healthy' | 'warning' | 'error';
  checks: {
    cpu: { status: string; value: number };
    memory: { status: string; value: number };
  };
}

// API方法
export const metricsApi = {
  // 获取系统指标
  getSystem: () => api.get<SystemMetrics>('/metrics/system'),

  // 获取所有Agent指标
  getAgents: () => api.get<AgentMetrics[]>('/metrics/agents'),

  // 获取指定Agent指标
  getAgent: (agentId: string) => api.get<AgentMetrics>(`/metrics/agents/${agentId}`),

  // 获取性能指标
  getPerformance: () => api.get<PerformanceMetrics>('/metrics/performance'),

  // 获取健康状态
  getHealth: () => api.get<{ success: boolean; data: HealthStatus }>('/metrics/health'),
};

export default metricsApi;
