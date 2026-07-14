import { api } from '../client';
import type { ApiResponse } from '../client';

export type ExtensionSurface = 'extensions' | 'tools' | 'timeline';
export type ExtensionFieldType = 'switch' | 'select' | 'input' | 'number' | 'secret' | 'path' | 'tags';
export type PluginSettingsActionStatus = 'pending' | 'succeeded' | 'failed' | 'cancelled';

export interface PluginCapability {
  capability: string;
  scope: string[];
  optional: boolean;
  reason: string;
  reason_i18n: Record<string, string>;
}

export interface PluginDisplayGroupSpec {
  id: string;
  name: string;
  name_i18n: Record<string, string>;
  description: string;
  description_i18n: Record<string, string>;
  icon?: string;
  order: number;
  member_label: string;
  member_label_i18n: Record<string, string>;
  member_order: number;
}

export interface ExtensionFieldOption {
  label: string;
  value: string;
  /**
   * Plugin-i18n-sourced label. Prefer over ``label`` and host i18n fallbacks.
   */
  label_translated?: string | null;
}

export interface ExtensionFieldSpec {
  key: string;
  type: ExtensionFieldType;
  label: string;
  /**
   * Plugin-i18n-sourced label (from the plugin's own ``i18n/<lang>.json``).
   * Frontend code MUST prefer this over host i18n lookups when present.
   */
  label_translated?: string | null;
  description: string;
  /** Plugin-i18n-sourced description; see ``label_translated``. */
  description_translated?: string | null;
  default?: any;
  required: boolean;
  options: ExtensionFieldOption[];
  section: string;
  /** Plugin-i18n-sourced section label (only set when the plugin overrides it). */
  section_translated?: string | null;
  /** Plugin-i18n-sourced section note (only set when the plugin overrides it). */
  section_note_translated?: string | null;
  surface: ExtensionSurface;
  order: number;
  placeholder?: string | null;
  depends_on_key?: string | null;
  depends_on_values?: string[];
}

export interface ActivationFlowSpec {
  title: string;
  /** Plugin-i18n-sourced title. */
  title_translated?: string | null;
  description: string;
  /** Plugin-i18n-sourced description. */
  description_translated?: string | null;
  confirm_label: string;
  /** Plugin-i18n-sourced confirm button label. */
  confirm_label_translated?: string | null;
  cancel_label: string;
  /** Plugin-i18n-sourced cancel button label. */
  cancel_label_translated?: string | null;
  authorize_on_confirm?: boolean;
  enabled_key: string;
  configured_key: string;
  fields: ExtensionFieldSpec[];
  first_context?: {
    max_items_per_sync?: number | null;
    settings_overrides?: Record<string, unknown>;
  } | null;
}

export interface PluginSettingsUiBlockSpec {
  block_id: string;
  type: 'resource_picker';
  title: string;
  /** Plugin-i18n-sourced title. */
  title_translated?: string | null;
  description: string;
  /** Plugin-i18n-sourced description. */
  description_translated?: string | null;
  resource_name: string;
  value_key: string;
  presentation: 'calendar_list' | 'list' | 'permission_status';
  depends_on_key?: string | null;
  depends_on_values?: string[];
}

export interface PluginSettingsLayoutTabSpec {
  tab_id: string;
  value: string;
  label: string;
  label_translated?: string | null;
  description?: string;
  description_translated?: string | null;
  available?: boolean;
  unavailable_reason?: string;
  unavailable_reason_translated?: string | null;
  platforms?: string[];
}

export interface PluginSettingsLayoutSpec {
  kind: 'tabs';
  controller_key: string;
  tabs: PluginSettingsLayoutTabSpec[];
}

export type PluginPermissionStatus = 'granted' | 'denied' | 'not_determined' | 'unknown';

export interface PluginPermissionStatusItem {
  id: string;
  label: string;
  label_i18n_key?: string;
  description?: string;
  description_i18n_key?: string;
  status: PluginPermissionStatus;
  required?: boolean;
  /**
   * Optional deep link to the OS-level settings pane for this permission.
   * Plugins may set this so the UI can render an "Open Settings" affordance
   * when the permission is denied. On macOS this is typically a
   * ``x-apple.systempreferences:`` URL.
   */
  settings_url?: string;
}

export interface PluginPermissionStatusData {
  items: PluginPermissionStatusItem[];
}

export interface PluginSettingsActionSpec {
  action_id: string;
  label: string;
  /** Plugin-i18n-sourced label. */
  label_translated?: string | null;
  description: string;
  /** Plugin-i18n-sourced description. */
  description_translated?: string | null;
  button_label: string;
  /** Plugin-i18n-sourced button label. */
  button_label_translated?: string | null;
  presentation: 'inline' | 'qr_code';
  surface: ExtensionSurface;
  contribution_id: string;
  contribution_type?: string | null;
  order: number;
  destructive: boolean;
  requires_enabled: boolean;
  poll_interval_ms: number;
  timeout_ms: number;
  persist_settings_on_success: boolean;
  depends_on_key?: string | null;
  depends_on_values?: string[];
}

export interface PluginSettingsActionRunResponse {
  plugin_id: string;
  action_id: string;
  session_id: string;
  status: PluginSettingsActionStatus;
  message: string;
  data: Record<string, any>;
  settings_updates: Record<string, any>;
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
    [key: string]: any;
  };
}

export interface PluginChannelStatusData {
  state?: string;
  running?: boolean;
  configured?: boolean;
  account_id?: string;
  last_start_at_ms?: number;
  last_stop_at_ms?: number;
  last_poll_at_ms?: number;
  last_inbound_at_ms?: number;
  last_outbound_at_ms?: number;
  last_error?: string;
  last_error_at_ms?: number;
}

export interface PluginManifest {
  plugin_id: string;
  name: string;
  version: string;
  description: string;
  author: string;
  icon?: string;
  display_group?: PluginDisplayGroupSpec | null;
  official: boolean;
  contribution_types: string[];
  source: string;
  plugin_dir: string;
  manifest_path: string;
  capabilities: PluginCapability[];
  consented_capabilities?: PluginCapability[] | null;
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

export type PluginInstallJobStatus = 'queued' | 'running' | 'completed' | 'failed';
export type PluginInstallOperation = 'install' | 'update' | 'upload';

export interface PluginInstallLogEntry {
  ts_ms: number;
  level: 'info' | 'warning' | 'error';
  stage: string;
  message: string;
}

export interface PluginInstallJobSnapshot {
  job_id: string;
  operation: PluginInstallOperation;
  plugin_id: string | null;
  filename: string | null;
  status: PluginInstallJobStatus;
  stage: string;
  progress_pct: number;
  message: string;
  error?: string | null;
  logs: PluginInstallLogEntry[];
  result?: PluginPackageState | null;
  created_at_ms: number;
  updated_at_ms: number;
  finished_at_ms?: number | null;
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

const INSTALL_JOB_POLL_MS = 1000;
const INSTALL_JOB_TIMEOUT_MS = 10 * 60 * 1000;

const wait = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

const waitForInstallJob = async (
  initialSnapshot: PluginInstallJobSnapshot,
  onProgress?: (snapshot: PluginInstallJobSnapshot) => void,
): Promise<PluginPackageState> => {
  let snapshot = initialSnapshot;
  const startedAt = Date.now();
  onProgress?.(snapshot);

  while (snapshot.status === 'queued' || snapshot.status === 'running') {
    if (Date.now() - startedAt > INSTALL_JOB_TIMEOUT_MS) {
      throw new Error('Plugin installation timed out');
    }
    await wait(INSTALL_JOB_POLL_MS);
    snapshot = await pluginsApi.getInstallJob(snapshot.job_id);
    onProgress?.(snapshot);
  }

  if (snapshot.status === 'completed' && snapshot.result) {
    return snapshot.result;
  }

  throw new Error(snapshot.error || snapshot.message || 'Plugin installation failed');
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
  icon?: string;
  display_group?: PluginDisplayGroupSpec | null;
  official: boolean;
  /** Privacy signal: "local_only" renders a Local-only badge; "" is unspecified. */
  data_locality?: string;
  contribution_types: string[];
  platforms: string[];
  min_sdk_version: string;
  homepage: string;
  repository: string;
  path: string;
  installed: boolean;
  installed_version: string | null;
  update_available: boolean;
  capabilities: PluginCapability[];
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

  startSettingsAction: async (
    pluginId: string,
    actionId: string,
    fieldValues: Record<string, any>
  ): Promise<PluginSettingsActionRunResponse> => {
    const response = await api.post<PluginSettingsActionRunResponse>(
      `/plugins/${pluginId}/settings/actions/${actionId}/start`,
      { field_values: fieldValues }
    );
    return unwrapPayload(
      response as PluginSettingsActionRunResponse | ApiResponse<PluginSettingsActionRunResponse>
    );
  },

  pollSettingsAction: async (
    pluginId: string,
    actionId: string,
    sessionId: string,
    fieldValues: Record<string, any>
  ): Promise<PluginSettingsActionRunResponse> => {
    const response = await api.post<PluginSettingsActionRunResponse>(
      `/plugins/${pluginId}/settings/actions/${actionId}/sessions/${sessionId}/poll`,
      { field_values: fieldValues }
    );
    return unwrapPayload(
      response as PluginSettingsActionRunResponse | ApiResponse<PluginSettingsActionRunResponse>
    );
  },

  cancelSettingsAction: async (
    pluginId: string,
    actionId: string,
    sessionId: string
  ): Promise<PluginSettingsActionRunResponse> => {
    const response = await api.post<PluginSettingsActionRunResponse>(
      `/plugins/${pluginId}/settings/actions/${actionId}/sessions/${sessionId}/cancel`,
      {}
    );
    return unwrapPayload(
      response as PluginSettingsActionRunResponse | ApiResponse<PluginSettingsActionRunResponse>
    );
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

  startInstallFromRegistry: async (pluginId: string): Promise<PluginInstallJobSnapshot> => {
    const response = await api.post<PluginInstallJobSnapshot>('/plugins/install/registry/jobs', {
      plugin_id: pluginId,
    });
    return unwrapPayload(response as PluginInstallJobSnapshot | ApiResponse<PluginInstallJobSnapshot>);
  },

  getInstallJob: async (jobId: string): Promise<PluginInstallJobSnapshot> => {
    const response = await api.get<PluginInstallJobSnapshot>(`/plugins/install/jobs/${jobId}`);
    return unwrapPayload(response as PluginInstallJobSnapshot | ApiResponse<PluginInstallJobSnapshot>);
  },

  installFromRegistryWithProgress: async (
    pluginId: string,
    onProgress?: (snapshot: PluginInstallJobSnapshot) => void,
  ): Promise<PluginPackageState> => {
    const snapshot = await pluginsApi.startInstallFromRegistry(pluginId);
    return waitForInstallJob(snapshot, onProgress);
  },

  installFromUpload: async (file: File): Promise<PluginPackageState> => {
    const formData = new FormData();
    formData.append('file', file);
    const response = await api.post<PluginPackageState>('/plugins/install/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return unwrapPayload(response as PluginPackageState | ApiResponse<PluginPackageState>);
  },

  startInstallFromUpload: async (file: File): Promise<PluginInstallJobSnapshot> => {
    const formData = new FormData();
    formData.append('file', file);
    const response = await api.post<PluginInstallJobSnapshot>('/plugins/install/upload/jobs', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    });
    return unwrapPayload(response as PluginInstallJobSnapshot | ApiResponse<PluginInstallJobSnapshot>);
  },

  installFromUploadWithProgress: async (
    file: File,
    onProgress?: (snapshot: PluginInstallJobSnapshot) => void,
  ): Promise<PluginPackageState> => {
    const snapshot = await pluginsApi.startInstallFromUpload(file);
    return waitForInstallJob(snapshot, onProgress);
  },

  inspectUpload: async (file: File): Promise<PluginManifest> => {
    const formData = new FormData();
    formData.append('file', file);
    const response = await api.post<PluginManifest>('/plugins/install/upload/inspect', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    });
    return unwrapPayload(response as PluginManifest | ApiResponse<PluginManifest>);
  },

  uninstall: async (pluginId: string): Promise<void> => {
    await api.delete(`/plugins/${pluginId}`);
  },

  // -----------------------------------------------------------------------
  // Registry / Marketplace
  // -----------------------------------------------------------------------

  getRegistry: async (options?: { force?: boolean }): Promise<PluginRegistryResponse> => {
    // `force` bypasses the backend's in-memory registry TTL cache so a
    // freshly published plugin version shows up immediately (wired to the
    // marketplace refresh button).
    const response = options?.force
      ? await api.get<PluginRegistryResponse>('/plugins/registry', { refresh: true })
      : await api.get<PluginRegistryResponse>('/plugins/registry');
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

  startUpdatePlugin: async (pluginId: string): Promise<PluginInstallJobSnapshot> => {
    const response = await api.post<PluginInstallJobSnapshot>(`/plugins/${pluginId}/update/jobs`, {});
    return unwrapPayload(response as PluginInstallJobSnapshot | ApiResponse<PluginInstallJobSnapshot>);
  },

  updatePluginWithProgress: async (
    pluginId: string,
    onProgress?: (snapshot: PluginInstallJobSnapshot) => void,
  ): Promise<PluginPackageState> => {
    const snapshot = await pluginsApi.startUpdatePlugin(pluginId);
    return waitForInstallJob(snapshot, onProgress);
  },
};

export default pluginsApi;
