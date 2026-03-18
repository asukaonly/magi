import { api } from '../client';
import type { ActivationFlowSpec, ExtensionFieldSpec } from './plugins';

export interface TimelineContentBlock {
  kind: string;
  value: string;
  mime_type?: string | null;
}

export interface TimelineRetentionInfo {
  mode: string;
  retained: boolean;
  raw_payload_ref?: string | null;
  content_block_count: number;
}

export interface TimelineEntity {
  id?: string;
  label?: string;
  type?: string;
}

export interface TimelineGraphEvidence {
  subject_id: string;
  predicate: string;
  object_id: string;
  confidence: number;
  evidence_event_ids: string[];
}

export interface TimelineEventRecord {
  event_id: string;
  source_type: string;
  source_item_id: string;
  occurred_at: number;
  captured_at: number;
  title: string;
  summary: string;
  retention_mode: string;
  raw_payload_ref?: string | null;
  content_blocks: TimelineContentBlock[];
  entities: TimelineEntity[];
  tags: string[];
  privacy_labels: string[];
  processing_status: Record<string, any>;
  provenance: Record<string, any>;
  retention?: TimelineRetentionInfo;
}

export interface TimelineEventDetail extends TimelineEventRecord {
  graph_evidence: TimelineGraphEvidence[];
}

export interface TimelineProjectionDisplayPayload {
  title?: string;
  summary?: string;
  source_type?: string;
  source_item_id?: string;
  event_type?: string;
  content_blocks?: TimelineContentBlock[];
  entities?: TimelineEntity[];
  tags?: string[];
  retention_mode?: string;
  raw_payload_ref?: string | null;
  provenance?: Record<string, any>;
  summary_type?: string;
  summary_category?: string;
  key_topics?: string[];
  key_entities?: string[];
  source_event_count?: number;
}

export interface TimelineProjectionItem {
  item_id: string;
  item_type: string;
  time_start: number;
  time_end: number;
  sort_time: number;
  primary_event_id?: string | null;
  primary_summary_id?: string | null;
  source_event_ids: string[];
  source_summary_ids: string[];
  display_payload: TimelineProjectionDisplayPayload;
  projection_version: number;
  generated_at: number;
}

export interface TimelineProjectionListResponse {
  items: TimelineProjectionItem[];
  count: number;
}

export interface TimelineManualEntryRequest {
  title: string;
  summary: string;
  text: string;
  image_refs: string[];
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

export const timelineApi = {
  listItems: async (
    options: { limit?: number; sourceType?: string; range?: 'all' | '7d' | '30d' } = {}
  ): Promise<TimelineProjectionListResponse> => {
    const response = await api.get<TimelineProjectionListResponse>('/timeline/items', {
      params: {
        limit: options.limit ?? 80,
        source_type: options.sourceType || undefined,
        range: options.range ?? 'all',
      },
    });
    return (response.data || response) as TimelineProjectionListResponse;
  },

  getEvent: async (eventId: string): Promise<TimelineEventDetail> => {
    const response = await api.get<TimelineEventDetail>(`/timeline/events/${eventId}`);
    return (response.data || response) as TimelineEventDetail;
  },

  createManualEntry: async (payload: TimelineManualEntryRequest): Promise<TimelineEventRecord> => {
    const response = await api.post<TimelineEventRecord>('/timeline/manual', payload);
    return (response.data || response) as TimelineEventRecord;
  },

  getSourceStatus: async (): Promise<TimelineSourceStatusResponse> => {
    const response = await api.get<TimelineSourceStatusResponse>('/timeline/sources/status');
    return (response.data || response) as TimelineSourceStatusResponse;
  },

  requestSync: async (sourceName: string): Promise<{ queued: boolean; source_name: string }> => {
    const response = await api.post<{ queued: boolean; source_name: string }>(`/timeline/sources/${sourceName}/sync`, {});
    return (response.data || response) as { queued: boolean; source_name: string };
  },

  requestReanalysis: async (
    eventId: string
  ): Promise<{ queued: boolean; event_id: string; event: TimelineEventDetail }> => {
    const response = await api.post<{ queued: boolean; event_id: string; event: TimelineEventDetail }>(
      `/timeline/events/${eventId}/reanalyze`,
      {}
    );
    return (response.data || response) as { queued: boolean; event_id: string; event: TimelineEventDetail };
  },
};
