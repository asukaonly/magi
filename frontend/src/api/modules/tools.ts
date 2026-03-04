/**
 * Tools API - Tool configuration management
 */
import { api } from '../client';

// ============ Types ============

export type ConfigValueType = 'string' | 'integer' | 'float' | 'boolean' | 'array' | 'object';

export interface ToolProviderInfo {
  name: string;
  display_name: string;
  is_ready: boolean;
  required_config: string[];
}

export interface ToolConfigSpec {
  path: string;
  type: ConfigValueType;
  description: string;
  sensitive: boolean;
  read_only: boolean;
  required: boolean;
  default?: any;
  enum?: any[];
  placeholder?: string;
  is_template: boolean;
}

export interface ToolConfig {
  name: string;
  display_name: string;
  description: string;
  category: string;
  version: string;
  enabled: boolean;
  is_ready: boolean;
  is_multi_provider: boolean;
  providers: ToolProviderInfo[];
  config_specs: ToolConfigSpec[];
  current_values: Record<string, any>;
}

export interface ToolsListResponse {
  tools: ToolConfig[];
  total: number;
}

export interface ToolConfigUpdateRequest {
  updates: Record<string, any>;
  enabled?: boolean;
}

// ============ API ============

export const toolsApi = {
  /**
   * Get all tools with configuration info
   */
  listWithConfig: () => api.get<ToolsListResponse>('/tools/config'),

  /**
   * Get single tool configuration
   */
  getToolConfig: (toolName: string) =>
    api.get<ToolConfig>(`/tools/${toolName}/config`),

  /**
   * Update tool configuration
   */
  updateToolConfig: (toolName: string, updates: ToolConfigUpdateRequest) =>
    api.put<{ success: boolean; message: string; updated_keys?: string[] }>(
      `/tools/${toolName}/config`,
      updates
    ),
};

export default toolsApi;
