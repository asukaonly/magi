import { api } from '../client';
import type { ActivationFlowSpec, ExtensionFieldSpec } from './plugins';

export interface TimelineStateBand {
  band_id: string;
  time_start: number;
  time_end: number;
  valence: number;
  stress_level: number;
  engagement: number;
  confidence: number;
  label: string;
  source_summary_ids: string[];
  source_assertion_ids: string[];
}

export interface TimelineStateMarker {
  marker_id: string;
  timestamp: number;
  kind: string;
  label: string;
  summary: string;
  source_band_ids: string[];
  source_summary_ids: string[];
}

export interface TimelineClusterBlock {
  block_id: string;
  time_start: number;
  time_end: number;
  duration_seconds: number;
  label: string;
  summary: string;
  dominant_mode: string;
  source_types: string[];
  event_count: number;
  representative_event_ids: string[];
  keywords: string[];
  media_refs: string[];
  state_snapshot?: {
    valence?: number;
    stress_level?: number;
    engagement?: number;
  };
}

export interface TimelineReflectionWindow {
  reflection_id: string;
  time_start: number;
  time_end: number;
  title: string;
  summary: string;
  key_topics: string[];
  key_entities: Array<Record<string, unknown>>;
  sentiment_summary?: Record<string, unknown> | null;
  change_and_pattern?: Record<string, unknown> | null;
  source_summary_ids: string[];
  source_event_ids: string[];
}

export interface TimelineRawEvent {
  event_id: string;
  timestamp: number;
  title: string;
  summary: string;
  source_type: string;
}

export interface TimelineViewportResponse {
  viewport: {
    scale: 'month' | 'week' | 'day' | 'hour';
    start: number;
    end: number;
    focus: 'self';
    query?: string | null;
    timezone?: string | null;
  };
  summary: {
    cluster_count: number;
    event_count: number;
    dominant_modes: string[];
  };
  state_bands: TimelineStateBand[];
  state_markers: TimelineStateMarker[];
  clusters: TimelineClusterBlock[];
  reflections: TimelineReflectionWindow[];
  raw_events: TimelineRawEvent[];
}

export interface TimelineContextBundle {
  anchor: {
    anchor_id: string;
    anchor_type: string;
    title: string;
    summary: string;
  };
  l1_events: Array<Record<string, unknown>>;
  l2_state_evidence: Array<Record<string, unknown>>;
  l3_reflections: Array<Record<string, unknown>>;
  l4_related_procedures: Array<Record<string, unknown>>;
  chat_excerpts: Array<Record<string, unknown>>;
  runtime_trace: Array<Record<string, unknown>>;
}

export interface TimelineSourceStatusItem {
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
  default_retention_mode: string;
  storage_mode: string;
  source_path?: string | null;
  fetch_page_content: boolean;
  edge_whitelist: string[];
  supports_pull_sync: boolean;
  activation_flow?: ActivationFlowSpec | null;
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

export interface TimelineSourceStatusResponse {
  sources: TimelineSourceStatusItem[];
}

export interface TimelineSourceAuthorizationResponse {
  authorized: boolean;
  requested_types: string[];
  granted_types: string[];
  denied_types: string[];
  message?: string | null;
}

export const timelineApi = {
  getViewport: async (options: {
    scale: 'month' | 'week' | 'day' | 'hour';
    start: number;
    end: number;
    query?: string;
    timezone?: string;
    focus?: 'self';
  }): Promise<TimelineViewportResponse> => {
    const response = await api.get<TimelineViewportResponse>('/timeline/viewport', {
      params: {
        scale: options.scale,
        start: options.start,
        end: options.end,
        query: options.query || undefined,
        timezone: options.timezone || undefined,
        focus: options.focus ?? 'self',
      },
    });
    return (response.data || response) as TimelineViewportResponse;
  },

  getContext: async (anchorId: string): Promise<TimelineContextBundle> => {
    const response = await api.get<TimelineContextBundle>(`/timeline/context/${anchorId}`);
    return (response.data || response) as TimelineContextBundle;
  },

  getSourceStatus: async (): Promise<TimelineSourceStatusResponse> => {
    const response = await api.get<TimelineSourceStatusResponse>('/timeline/sources/status');
    return (response.data || response) as TimelineSourceStatusResponse;
  },

  requestSync: async (sourceName: string): Promise<{ queued: boolean; source_name: string }> => {
    const response = await api.post<{ queued: boolean; source_name: string }>(`/timeline/sources/${sourceName}/sync`, {});
    return (response.data || response) as { queued: boolean; source_name: string };
  },

  requestAuthorization: async (
    sourceName: string,
    fieldValues: Record<string, any>
  ): Promise<TimelineSourceAuthorizationResponse> => {
    const response = await api.post<TimelineSourceAuthorizationResponse>(
      `/timeline/sources/${sourceName}/authorize`,
      { field_values: fieldValues }
    );
    return (response.data || response) as TimelineSourceAuthorizationResponse;
  },
};
