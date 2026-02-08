/**
 * API模块统一导出
 */
export { apiClient, api } from './client';
export type { ApiResponse, ApiError, PaginatedResponse } from './client';

export { agentsApi } from './modules/agents';
export type {
  Agent,
  AgentCreateRequest,
  AgentUpdateRequest,
  AgentActionRequest,
  AgentStats,
} from './modules/agents';

export { tasksApi } from './modules/tasks';
export type { Task, TaskCreateRequest, TaskRetryRequest, TaskStats } from './modules/tasks';

export { toolsApi } from './modules/tools';
export type { Tool, ToolTestRequest, ToolTestResult } from './modules/tools';

export { memoryApi } from './modules/memory';
export type { Memory, MemorySearchRequest, MemorySearchResult, MemoryStats } from './modules/memory';

export { metricsApi } from './modules/metrics';
export type {
  SystemMetrics,
  AgentMetrics,
  PerformanceMetrics,
  HealthStatus,
} from './modules/metrics';
