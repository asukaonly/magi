/**
 * 工具管理API
 */
import { api } from '../client';

// 类型定义
export interface Tool {
  name: string;
  description: string;
  category: string;
  parameters: Record<string, {
    type: string;
    description: string;
    required?: boolean;
    default?: any;
  }>;
  examples: Array<{
    input: Record<string, any>;
    output: string;
  }>;
  metadata: Record<string, any>;
}

export interface ToolTestRequest {
  parameters?: Record<string, any>;
}

export interface ToolTestResult {
  tool_name: string;
  parameters: Record<string, any>;
  result: any;
}

// API方法
export const toolsApi = {
  // 获取工具列表
  list: (params?: { category?: string; limit?: number; offset?: number }) =>
    api.get<Tool[]>('/tools', params),

  // 获取工具详情
  get: (toolName: string) => api.get<Tool>(`/tools/${toolName}`),

  // 测试工具
  test: (toolName: string, data: ToolTestRequest) =>
    api.post<{ success: boolean; message: string; data: ToolTestResult }>(
      `/tools/${toolName}/test`,
      data
    ),

  // 获取工具分类列表
  getCategories: () => api.get<string[]>('/tools/categories/list'),
};

export default toolsApi;
