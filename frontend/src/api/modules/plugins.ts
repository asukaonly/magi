import { api } from '../client';
import type { ApiResponse } from '../client';

export type ExtensionSurface = 'extensions' | 'tools' | 'timeline' | 'actions';
export type ExtensionFieldType = 'switch' | 'select' | 'input' | 'number' | 'secret' | 'path' | 'tags';

export interface ExtensionFieldOption {
  label: string;
  value: string;
}

export interface ExtensionFieldSpec {
  key: string;
  type: ExtensionFieldType;
  label: string;
  description: string;
  default?: any;
  required: boolean;
  options: ExtensionFieldOption[];
  section: string;
  surface: ExtensionSurface;
  order: number;
  placeholder?: string | null;
}

export interface PluginManifest {
  plugin_id: string;
  name: string;
  version: string;
  description: string;
  author: string;
  official: boolean;
  contribution_types: string[];
  source: string;
  plugin_dir: string;
  manifest_path: string;
}

export interface PluginContribution {
  plugin_id: string;
  contribution_id: string;
  contribution_type: string;
  display_name: string;
  description: string;
  surface: ExtensionSurface;
  fields: ExtensionFieldSpec[];
  metadata: Record<string, any>;
}

export interface PluginPackageState {
  manifest: PluginManifest;
  enabled: boolean;
  trusted: boolean;
  loaded: boolean;
  healthy: boolean;
  last_error?: string | null;
  contributions: PluginContribution[];
  current_settings: Record<string, any>;
}

export interface PluginsListResponse {
  plugins: PluginPackageState[];
  total: number;
}

export interface PluginSettingsUpdateRequest {
  updates: Record<string, any>;
}

const unwrapPayload = <T>(payload: T | ApiResponse<T>): T => {
  if (payload && typeof payload === 'object' && 'data' in (payload as ApiResponse<T>)) {
    return ((payload as ApiResponse<T>).data ?? payload) as T;
  }
  return payload as T;
};

export const getNestedPluginSetting = (
  settings: Record<string, any>,
  path: string,
  fallback?: any
): any => {
  const value = path.split('.').reduce<any>((current, part) => {
    if (current && typeof current === 'object' && part in current) {
      return current[part];
    }
    return undefined;
  }, settings);
  return value === undefined ? fallback : value;
};

export const buildPluginFieldValueMap = (
  fields: ExtensionFieldSpec[],
  settings: Record<string, any>
): Record<string, any> =>
  Object.fromEntries(fields.map((field) => [field.key, getNestedPluginSetting(settings, field.key, field.default)]));

export const pluginsApi = {
  list: async (): Promise<PluginsListResponse> => {
    const response = await api.get<PluginsListResponse>('/plugins');
    return unwrapPayload(response as PluginsListResponse | ApiResponse<PluginsListResponse>);
  },

  rescan: async (): Promise<PluginsListResponse> => {
    const response = await api.post<PluginsListResponse>('/plugins/rescan', {});
    return unwrapPayload(response as PluginsListResponse | ApiResponse<PluginsListResponse>);
  },

  enable: async (pluginId: string): Promise<PluginPackageState> => {
    const response = await api.post<PluginPackageState>(`/plugins/${pluginId}/enable`, {});
    return unwrapPayload(response as PluginPackageState | ApiResponse<PluginPackageState>);
  },

  disable: async (pluginId: string): Promise<PluginPackageState> => {
    const response = await api.post<PluginPackageState>(`/plugins/${pluginId}/disable`, {});
    return unwrapPayload(response as PluginPackageState | ApiResponse<PluginPackageState>);
  },

  reload: async (pluginId: string): Promise<PluginPackageState> => {
    const response = await api.post<PluginPackageState>(`/plugins/${pluginId}/reload`, {});
    return unwrapPayload(response as PluginPackageState | ApiResponse<PluginPackageState>);
  },

  getSettings: async (pluginId: string): Promise<PluginPackageState> => {
    const response = await api.get<PluginPackageState>(`/plugins/${pluginId}/settings`);
    return unwrapPayload(response as PluginPackageState | ApiResponse<PluginPackageState>);
  },

  updateSettings: async (
    pluginId: string,
    updates: Record<string, any>
  ): Promise<PluginPackageState> => {
    const response = await api.put<PluginPackageState>(`/plugins/${pluginId}/settings`, {
      updates,
    } satisfies PluginSettingsUpdateRequest);
    return unwrapPayload(response as PluginPackageState | ApiResponse<PluginPackageState>);
  },
};

export default pluginsApi;
