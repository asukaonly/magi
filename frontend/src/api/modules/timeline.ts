import { api } from '../client';

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

export interface TimelineDigestSummary {
  summary_id: string;
  summary_type: string;
  summary_category: string;
  content: string;
  period_start: number;
  period_end: number;
  key_topics: string[];
  key_entities: Array<Record<string, unknown>>;
  sentiment_summary?: Record<string, unknown> | null;
  change_and_pattern?: Record<string, unknown> | null;
  importance_aggregate?: number;
  source_event_count?: number;
  generated_by_model?: string;
  updated_at?: string;
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

  getDigests: async (options?: {
    limit?: number;
    category?: string;
  }): Promise<TimelineDigestSummary[]> => {
    const response = await api.get<TimelineDigestSummary[]>('/timeline/digests', {
      params: {
        limit: options?.limit ?? 5,
        category: options?.category ?? 'day',
      },
    });
    return (response.data || response) as TimelineDigestSummary[];
  },

  triggerDigest: async (category: string = 'day'): Promise<{ status: string; summary: TimelineDigestSummary | null }> => {
    const response = await api.post<{ status: string; summary: TimelineDigestSummary | null }>(
      '/timeline/digests/generate',
      null,
      { params: { category } },
    );
    return (response.data || response) as { status: string; summary: TimelineDigestSummary | null };
  },
};
