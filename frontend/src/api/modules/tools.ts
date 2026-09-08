/**
 * Tools API - Tool configuration management
 */
import { api } from '../client';
import { ApiContractError } from '../config-contract';
import type { components } from '../generated/config-types';
import { validateToolConfigResponse, validateToolsListResponse } from '../generated/config-validators';

// ============ Types ============

type Wire = components['schemas'];
export type ConfigValueType = Wire['ToolConfigSpecResponse']['type'];
export type ToolProviderInfo = Wire['ToolProviderInfo'];
export type ToolConfigSpec = Omit<Wire['ToolConfigSpecResponse'], 'enum' | 'placeholder' | 'providers' | 'default'> & {
  default?: unknown; enum?: unknown[]; placeholder?: string; providers?: string[];
};
export type ToolConfig = Omit<Wire['ToolConfigResponse'], 'config_specs'> & { config_specs: ToolConfigSpec[] };
export interface ToolsListResponse { tools: ToolConfig[]; total: number; }

function parseToolConfig(value: unknown): ToolConfig {
  if (!validateToolConfigResponse(value)) throw new ApiContractError('Invalid tool configuration');
  return { ...value, config_specs: value.config_specs.map(spec => ({
    ...spec, enum: spec.enum ?? undefined, placeholder: spec.placeholder ?? undefined, providers: spec.providers ?? undefined,
  })) };
}

export interface ToolConfigUpdateRequest {
  revision: string;
  updates: Record<string, unknown>;
  enabled?: boolean;
}

// ============ API ============

export const toolsApi = {
  /**
   * Get all tools with configuration info
   */
  listWithConfig: async (): Promise<ToolsListResponse> => {
    const response = await api.get<unknown>('/tools/config');
    if (!validateToolsListResponse(response)) throw new ApiContractError('Invalid tools list');
    return { tools: response.tools.map(parseToolConfig), total: response.total };
  },

  getToolConfig: async (toolName: string): Promise<ToolConfig> => {
    const tool = parseToolConfig(await api.get<unknown>(`/tools/${encodeURIComponent(toolName)}/config`));
    if (tool.name !== toolName) throw new ApiContractError('Tool configuration identity mismatch');
    return tool;
  },

  /** Use the atomic write receipt as the acknowledged baseline. */
  updateToolConfig: async (toolName: string, updates: ToolConfigUpdateRequest): Promise<ToolConfig> => {
    const response = await api.put<unknown>(`/tools/${encodeURIComponent(toolName)}/config`, updates);
    const tool = parseToolConfig(response);
    if (tool.name !== toolName) throw new ApiContractError('Tool configuration identity mismatch');
    return tool;
  },
};

export default toolsApi;
