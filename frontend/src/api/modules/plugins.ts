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
  depends_on_key?: string | null;
  depends_on_values?: string[];
}

export interface ActivationFlowSpec {
  title: string;
  description: string;
  confirm_label: string;
  cancel_label: string;
  authorize_on_confirm?: boolean;
  enabled_key: string;
  configured_key: string;
  fields: ExtensionFieldSpec[];
}

export interface PluginSettingsUiBlockSpec {
  block_id: string;
  type: 'resource_picker';
  title: string;
  description: string;
  resource_name: string;
  value_key: string;
  presentation: 'calendar_list' | 'list';
  depends_on_key?: string | null;
  depends_on_values?: string[];
}

export interface PluginSettingsResourceItem {
  item_id: string;
  label: string;
  description?: string;
  accent_color?: string | null;
}

export interface PluginSettingsResourceGroup {
  group_id: string;
  label: string;
  items: PluginSettingsResourceItem[];
}

export interface PluginSettingsResourcePayload {
  plugin_id: string;
  resource_name: string;
  resource_type: string;
  data: {
    groups?: PluginSettingsResourceGroup[];
  };
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
  if (
    payload &&
    typeof payload === 'object' &&
    'success' in (payload as ApiResponse<T>) &&
    typeof (payload as ApiResponse<T>).success === 'boolean'
  ) {
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

// ---------------------------------------------------------------------------
// Registry / Marketplace types
// ---------------------------------------------------------------------------

export interface PluginRegistryEntry {
  plugin_id: string;
  name: string;
  name_i18n: Record<string, string>;
  version: string;
  description: string;
  description_i18n: Record<string, string>;
  author: string;
  official: boolean;
  contribution_types: string[];
  platforms: string[];
  min_sdk_version: string;
  homepage: string;
  repository: string;
  path: string;
  installed: boolean;
  installed_version: string | null;
  update_available: boolean;
}

export interface PluginRegistryResponse {
  plugins: PluginRegistryEntry[];
  registry_version: string;
}

export interface PluginUpdateCheck {
  plugin_id: string;
  current_version: string;
  latest_version: string;
  update_available: boolean;
}

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

  getSettingsResource: async (
    pluginId: string,
    resourceName: string
  ): Promise<PluginSettingsResourcePayload> => {
    const response = await api.get<PluginSettingsResourcePayload>(
      `/plugins/${pluginId}/settings/resources/${resourceName}`
    );
    return unwrapPayload(
      response as PluginSettingsResourcePayload | ApiResponse<PluginSettingsResourcePayload>
    );
  },

  // -----------------------------------------------------------------------
  // Installation
  // -----------------------------------------------------------------------

  installFromRegistry: async (pluginId: string): Promise<PluginPackageState> => {
    const response = await api.post<PluginPackageState>('/plugins/install/registry', {
      plugin_id: pluginId,
    });
    return unwrapPayload(response as PluginPackageState | ApiResponse<PluginPackageState>);
  },

  installFromUpload: async (file: File): Promise<PluginPackageState> => {
    const formData = new FormData();
    formData.append('file', file);
    const response = await api.post<PluginPackageState>('/plugins/install/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return unwrapPayload(response as PluginPackageState | ApiResponse<PluginPackageState>);
  },

  uninstall: async (pluginId: string): Promise<void> => {
    await api.delete(`/plugins/${pluginId}`);
  },

  // -----------------------------------------------------------------------
  // Registry / Marketplace
  // -----------------------------------------------------------------------

  getRegistry: async (): Promise<PluginRegistryResponse> => {
    const response = await api.get<PluginRegistryResponse>('/plugins/registry');
    return unwrapPayload(response as PluginRegistryResponse | ApiResponse<PluginRegistryResponse>);
  },

  checkUpdates: async (): Promise<PluginUpdateCheck[]> => {
    const response = await api.get<PluginUpdateCheck[]>('/plugins/updates');
    return unwrapPayload(response as PluginUpdateCheck[] | ApiResponse<PluginUpdateCheck[]>);
  },

  updatePlugin: async (pluginId: string): Promise<PluginPackageState> => {
    const response = await api.post<PluginPackageState>(`/plugins/${pluginId}/update`, {});
    return unwrapPayload(response as PluginPackageState | ApiResponse<PluginPackageState>);
  },
};

export default pluginsApi;
