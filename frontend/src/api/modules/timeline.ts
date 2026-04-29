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
  user_pinned?: boolean;
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

export interface TimelineSourceMixItem {
  source_type: string;
  label: string;
  event_count: number;
  duration_seconds?: number;
}

export interface TimelineOverview {
  title: string;
  summary: string;
  key_takeaways: string[];
  confidence: number;
}

export interface TimelineStateChange {
  label: string;
  summary: string;
  timestamp?: number;
  anchor?: Record<string, unknown>;
}

export interface TimelineStateSummary {
  mood_label: string;
  stress_label: string;
  engagement_label: string;
  mood_value?: number | null;
  stress_value?: number | null;
  engagement_value?: number | null;
  notable_changes: TimelineStateChange[];
}

export interface TimelineAnchor {
  anchor_type: string;
  anchor_id?: string;
  representative_event_ids?: string[];
  episode_id?: string | null;
  time_start: number;
  time_end: number;
}

export interface TimelineThemeCard {
  theme_id: string;
  title: string;
  summary: string;
  source_types: string[];
  event_count: number;
  anchor: TimelineAnchor;
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
  overview: TimelineOverview;
  state_summary: TimelineStateSummary;
  state_bands: TimelineStateBand[];
  state_markers: TimelineStateMarker[];
  source_mix: TimelineSourceMixItem[];
  theme_cards: TimelineThemeCard[];
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
