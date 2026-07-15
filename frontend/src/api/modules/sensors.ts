import { api, unwrapGatewayPayload } from '../client';
import type { components } from '../../types/api/generated';
import type {
  ActivationFlowSpec,
  ExtensionFieldSpec,
  PluginSettingsActionSpec,
  PluginSettingsLayoutSpec,
  PluginSettingsUiBlockSpec,
} from './plugins';

/** Honest memory-readiness signal for one sensor source (see backend GET /sensors/{source}/memory-readiness). */
export type MemoryReadinessResponse = components['schemas']['MemoryReadinessResponse'];

export interface SensorSyncActivity {
  job_id: string;
  mode: 'latest' | 'backfill';
  status: 'queued' | 'running' | 'continuing' | 'success' | 'failed' | string;
  backfill_scope?: SensorBackfillScope | null;
  backfill_start_date?: string | null;
  backfill_end_date?: string | null;
  created_at?: number | null;
  started_at?: number | null;
  finished_at?: number | null;
  error?: string | null;
}

export interface SensorSourceStatusItem {
  source_name: string;
  plugin_id: string;
  contribution_id: string;
  icon?: string | null;
  display_name: string;
  /**
   * Pre-translated display_name supplied by the backend from the plugin's own
   * i18n. Prefer this over host i18n fallbacks. Falls back to the raw English
   * ``display_name`` when the plugin has no translation entry.
   */
  display_name_translated?: string | null;
  description: string;
  /** Pre-translated description; see ``display_name_translated``. */
  description_translated?: string | null;
  capability_id?: string | null;
  capability_display_name?: string | null;
  capability_display_name_translated?: string | null;
  capability_description?: string | null;
  capability_description_translated?: string | null;
  entry_id?: string | null;
  entry_display_name?: string | null;
  entry_display_name_translated?: string | null;
  entry_description?: string | null;
  entry_description_translated?: string | null;
  entry_order?: number | null;
  available?: boolean | null;
  unavailable_reason?: string | null;
  unavailable_reason_translated?: string | null;
  platforms?: string[] | null;
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
  settings_layout?: PluginSettingsLayoutSpec | null;
  settings_ui_blocks?: PluginSettingsUiBlockSpec[];
  settings_actions?: PluginSettingsActionSpec[];
  activation_required?: boolean;
  status?: 'ready' | 'running' | 'stale' | 'error' | 'never_synced' | 'setup_required' | 'disabled' | string;
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
  sync_activity?: SensorSyncActivity | null;
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

export interface SensorTodaySummaryEntry {
  source_name: string;
  plugin_id: string | null;
  display_name: string;
  enabled: boolean;
  count: number;
  last_event_at: number | null;
}

export interface SensorTodaySummaryResponse {
  date: string;
  weekday: number;
  sources: SensorTodaySummaryEntry[];
}

export type SensorSyncMode = 'latest' | 'backfill';
export type SensorBackfillScope = 'last_7_days' | 'last_30_days' | 'full' | 'custom';

export interface SensorSyncRequestOptions {
  firstContext?: boolean;
  mode?: SensorSyncMode;
  backfillScope?: SensorBackfillScope;
  backfillStartDate?: string;
  backfillEndDate?: string;
}

export interface SensorSyncResponse {
  queued: boolean;
  source_name: string;
  command_id?: number;
  mode?: SensorSyncMode;
  backfill_scope?: SensorBackfillScope;
  backfill_days?: number;
  backfill_start_date?: string;
  backfill_end_date?: string;
}

export const sensorsApi = {
  getStatus: async (): Promise<SensorSourceStatusResponse> => {
    const response = await api.get<SensorSourceStatusResponse>('/sensors/status');
    return unwrapGatewayPayload(response);
  },

  getTodaySummary: async (day?: string): Promise<SensorTodaySummaryResponse> => {
    const response = await api.get<SensorTodaySummaryResponse>(
      '/sensors/today-summary',
      day ? { params: { day } } : undefined,
    );
    return unwrapGatewayPayload(response);
  },

  getMemoryReadiness: async (
    sourceName: string,
    opts?: { maxWaitMs?: number },
  ): Promise<MemoryReadinessResponse> => {
    const qs = opts?.maxWaitMs != null ? `?max_wait_ms=${opts.maxWaitMs}` : '';
    const response = await api.get<MemoryReadinessResponse>(
      `/sensors/${encodeURIComponent(sourceName)}/memory-readiness${qs}`,
    );
    return unwrapGatewayPayload(response);
  },

  requestSync: async (
    sourceName: string,
    opts?: SensorSyncRequestOptions,
  ): Promise<SensorSyncResponse> => {
    const payload: Record<string, unknown> = {};
    if (opts?.firstContext) {
      payload.first_context = true;
    }
    if (opts?.mode === 'backfill') {
      payload.mode = 'backfill';
      payload.backfill_scope = opts.backfillScope ?? 'last_30_days';
      if (opts.backfillStartDate) {
        payload.backfill_start_date = opts.backfillStartDate;
      }
      if (opts.backfillEndDate) {
        payload.backfill_end_date = opts.backfillEndDate;
      }
    }
    const response = await api.post<SensorSyncResponse>(
      `/sensors/${sourceName}/sync`,
      payload,
    );
    return unwrapGatewayPayload(response);
  },

  requestStateFlush: async (sourceName: string): Promise<{ queued: boolean; source_name: string }> => {
    const response = await api.post<{ queued: boolean; source_name: string }>(`/sensors/${sourceName}/flush-state`, {});
    return unwrapGatewayPayload(response);
  },

  requestAuthorization: async (
    sourceName: string,
    fieldValues: Record<string, any>
  ): Promise<SensorSourceAuthorizationResponse> => {
    const response = await api.post<SensorSourceAuthorizationResponse>(
      `/sensors/${sourceName}/authorize`,
      { field_values: fieldValues }
    );
    return unwrapGatewayPayload(response);
  },
};
