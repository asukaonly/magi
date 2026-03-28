import { api } from '../client';
import type { ActivationFlowSpec, ExtensionFieldSpec, PluginSettingsUiBlockSpec } from './plugins';

export interface SensorSourceStatusItem {
  source_name: string;
  plugin_id: string;
  contribution_id: string;
  display_name: string;
  description: string;
  fields: ExtensionFieldSpec[];
  current_settings: Record<string, any>;
  enabled: boolean;
  sync_mode: string;
  sync_interval_minutes: number;
  storage_mode: string;
  source_path?: string | null;
  fetch_page_content: boolean;
  edge_whitelist: string[];
  supports_pull_sync: boolean;
  supports_state_flush?: boolean;
  activation_flow?: ActivationFlowSpec | null;
  settings_ui_blocks?: PluginSettingsUiBlockSpec[];
  activation_required?: boolean;
  running?: boolean;
  last_run_at?: number | string | null;
  last_result_count?: number;
  last_raw_result_count?: number;
  last_error?: string | null;
  last_success?: string | null;
  last_sync_at?: number | string | null;
  next_run_at?: number | string | null;
  scheduler_job_id?: string | null;
  runtime_base_dir?: string | null;
}

export interface SensorSourceStatusResponse {
  sources: SensorSourceStatusItem[];
}

export interface SensorSourceAuthorizationResponse {
  authorized: boolean;
  requested_types: string[];
  granted_types: string[];
  denied_types: string[];
  message?: string | null;
}

export const sensorsApi = {
  getStatus: async (): Promise<SensorSourceStatusResponse> => {
    const response = await api.get<SensorSourceStatusResponse>('/sensors/status');
    return (response.data || response) as SensorSourceStatusResponse;
  },

  requestSync: async (sourceName: string): Promise<{ queued: boolean; source_name: string }> => {
    const response = await api.post<{ queued: boolean; source_name: string }>(`/sensors/${sourceName}/sync`, {});
    return (response.data || response) as { queued: boolean; source_name: string };
  },

  requestStateFlush: async (sourceName: string): Promise<{ queued: boolean; source_name: string }> => {
    const response = await api.post<{ queued: boolean; source_name: string }>(`/sensors/${sourceName}/flush-state`, {});
    return (response.data || response) as { queued: boolean; source_name: string };
  },

  requestAuthorization: async (
    sourceName: string,
    fieldValues: Record<string, any>
  ): Promise<SensorSourceAuthorizationResponse> => {
    const response = await api.post<SensorSourceAuthorizationResponse>(
      `/sensors/${sourceName}/authorize`,
      { field_values: fieldValues }
    );
    return (response.data || response) as SensorSourceAuthorizationResponse;
  },
};
