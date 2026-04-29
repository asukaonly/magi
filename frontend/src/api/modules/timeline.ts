import { api, unwrapGatewayPayload } from '../client';

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
  episode_id?: string;
  user_label?: string | null;
  user_note?: string | null;
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
    time_start?: number;
    time_end?: number;
    source_types?: string[];
  };
  l1_events: Array<Record<string, unknown>>;
  l2_state_evidence: Array<Record<string, unknown>>;
  l3_reflections: Array<Record<string, unknown>>;
  l4_related_procedures: Array<Record<string, unknown>>;
  chat_excerpts: Array<Record<string, unknown>>;
  runtime_trace: Array<Record<string, unknown>>;
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
    return unwrapGatewayPayload(response);
  },

  getContext: async (anchorId: string): Promise<TimelineContextBundle> => {
    const response = await api.get<TimelineContextBundle>(`/timeline/context/${anchorId}`);
    return unwrapGatewayPayload(response);
  },
};
