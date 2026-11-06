import { api, unwrapGatewayPayload } from '../client';
import { z } from 'zod';

const reviewPeriodSchema = z.object({
  start: z.number().finite(), end: z.number().finite(), target_start: z.number().finite(),
  scale: z.enum(['day', 'week']), summary: z.string(), event_count: z.number().int().nonnegative(),
  source_types: z.array(z.string()), has_summary: z.boolean(),
});
const periodReviewSchema = z.object({
  periods: z.array(reviewPeriodSchema).max(7),
  topics: z.array(z.object({
    topic_id: z.string(), title: z.string(), summary: z.string(), source_types: z.array(z.string()),
    period_starts: z.array(z.number().finite()).max(7),
  })).max(3),
  summary_status: z.enum(['ready', 'partial', 'pending']),
  summary_updated_at: z.number().finite().nullable(), active_days: z.number().int().min(0).max(32),
});
export type TimelineReviewPeriod = z.infer<typeof reviewPeriodSchema>;
export type TimelinePeriodReview = z.infer<typeof periodReviewSchema>;

const contextSchema = z.object({
  anchor: z.object({ anchor_id: z.string(), anchor_type: z.string(), title: z.string(), summary: z.string() }).passthrough(),
  l1_events: z.array(z.object({
    event_id: z.string(), timestamp: z.number().finite(), title: z.string(), summary: z.string(), source_type: z.string(),
    source_item_id: z.string().optional(), url: z.string().nullable().optional(), user_prompts: z.array(z.string()).optional(), visit_count: z.number().int().positive().nullable().optional(),
  }).passthrough()),
  l2_state_evidence: z.array(z.record(z.string(), z.unknown())),
  l3_reflections: z.array(z.record(z.string(), z.unknown())),
  l4_related_procedures: z.array(z.record(z.string(), z.unknown())),
  chat_excerpts: z.array(z.record(z.string(), z.unknown())),
  runtime_trace: z.array(z.record(z.string(), z.unknown())),
});

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
  source_event_ids?: string[];
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
  /** Existing durable experience relation, when this cluster is a member. */
  experience_id?: string | null;
  experience_title?: string | null;
  /** Present only when a persisted experience chapter explicitly owns the cluster. */
  experience_chapter_id?: string | null;
  experience_chapter_title?: string | null;

  // Plan 1+2 immersive fields (Plan 3 backend Task 1 surfaces them)
  slice_narrative?: string;
  slice_sensory_detail?: string;
  representative_asset_ref?: string;
}

export type TimelineCoverMode = 'auto' | 'asset' | 'hidden';
export type TimelineCoverSource = 'auto' | 'current_period' | 'hidden' | string;

export interface TimelineCoverCandidate {
  asset_ref: string;
  source: TimelineCoverSource;
  label?: string | null;
  cluster_id?: string | null;
  episode_id?: string | null;
}

export interface TimelineCoverState {
  mode: TimelineCoverMode;
  asset_ref: string | null;
  source: TimelineCoverSource;
  candidates: TimelineCoverCandidate[];
}

export interface TimelineCoverPreferencePayload {
  scale: 'month' | 'week' | 'day' | 'hour';
  start: number;
  end: number;
  mode: TimelineCoverMode;
  asset_ref?: string | null;
  source?: TimelineCoverSource;
  locale?: string;
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
  essence_prose?: string;
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
    locale?: string | null;
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
  cover?: TimelineCoverState;
  period_review?: TimelinePeriodReview;
  /** Top labels for the period from LocationResolver (city/region/POI),
   *  ordered by aggregate time-weighted contribution. Index 0 is the
   *  primary chip; subsequent entries can be rendered as secondary chips. */
  place_hints?: string[];
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
    locale?: string;
    focus?: 'self';
    signal?: AbortSignal;
  }): Promise<TimelineViewportResponse> => {
    const response = await api.get<TimelineViewportResponse>('/timeline/viewport', {
      signal: options.signal,
      params: {
        scale: options.scale,
        start: options.start,
        end: options.end,
        query: options.query || undefined,
        timezone: options.timezone || undefined,
        locale: options.locale || undefined,
        focus: options.focus ?? 'self',
      },
    });
    const viewport = unwrapGatewayPayload(response);
    if (options.scale === 'week' || options.scale === 'month') {
      return { ...viewport, period_review: periodReviewSchema.parse(viewport.period_review) };
    }
    return viewport;
  },

  getContext: async (anchorId: string): Promise<TimelineContextBundle> => {
    const response = await api.get<unknown>(`/timeline/context/${encodeURIComponent(anchorId)}`);
    return contextSchema.parse(unwrapGatewayPayload(response));
  },

  getEventContext: async (eventIds: string[]): Promise<TimelineContextBundle> => {
    const response = await api.post<unknown>('/timeline/context', { event_ids: eventIds });
    return contextSchema.parse(unwrapGatewayPayload(response));
  },

  getStandout: async (
    options?: { month?: string; periodStart?: number; periodEnd?: number; limit?: number }
  ): Promise<TimelineStandoutResponse> => {
    const params: Record<string, string> = { limit: String(options?.limit ?? 50) };
    if (options?.month) params.month = options.month;
    if (options?.periodStart !== undefined) params.period_start = String(options.periodStart);
    if (options?.periodEnd !== undefined) params.period_end = String(options.periodEnd);
    const response = await api.get<TimelineStandoutResponse>('/timeline/standout', { params });
    return unwrapGatewayPayload(response);
  },

  getMoodCalendar: async (month: string): Promise<TimelineMoodCalendarResponse> => {
    const response = await api.get<TimelineMoodCalendarResponse>('/timeline/mood-calendar', {
      params: { month },
    });
    return unwrapGatewayPayload(response);
  },

  setCoverPreference: async (
    payload: TimelineCoverPreferencePayload
  ): Promise<TimelineCoverState> => {
    const response = await api.post<TimelineCoverState>('/timeline/cover', payload);
    return unwrapGatewayPayload(response);
  },
};

// ============================================
// Standout — Plan 1 endpoint, frontend wrapper
// ============================================

export interface TimelineStandoutItem {
  episode_id: string;
  scale: string;
  start: number;
  end: number;
  title: string;
  date: string;
  source: 'user' | 'magi';
  score: number;
}

export interface TimelineStandoutResponse {
  month: string | null;
  items: TimelineStandoutItem[];
}

// ============================================
// Mood calendar — Plan 1 endpoint, frontend wrapper
// ============================================

export interface TimelineMoodCalendarDay {
  date: string;
  dominant_valence: string;
  volatility: number;
  event_count: number;
  sparkline: number[];
}

export interface TimelineMoodCalendarResponse {
  month: string;
  days: TimelineMoodCalendarDay[];
}
