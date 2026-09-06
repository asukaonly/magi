import { api, unwrapGatewayPayload } from '../client';

export type StoryReviewState =
  | 'neutral'
  | 'pending_confirmation'
  | 'confirmed'
  | 'rejected'
  | 'archived';

export type StorySummaryCategory = string;
export type StoryFeedGroup = 'periodic' | 'observations' | 'tasks' | 'memory_update' | 'other';
export type StoryFeedSurface = 'all' | 'summary';

export interface StoryFeedStats {
  highlights: number;
  periodic: number;
  observations: number;
  tasks: number;
}

export interface StoryItem {
  summary_id: string;
  summary_type: 'insight' | 'temporal' | 'thematic' | string;
  summary_category: StorySummaryCategory;
  title: string;
  content: string;
  essence_prose?: string | null;
  period_start: number | null;
  period_end: number | null;
  updated_at: number;
  review_state: StoryReviewState;
  insight_key: string | null;
  insight_metadata: Record<string, unknown>;
  evidence_event_count: number;
  generated_by_model?: string | null;
  narrative_style?: string | null;
  feed_group: StoryFeedGroup;
  summary_feed_visible: boolean;
  featured_rank: number | null;
  display_timestamp: number;
  preview_text: string;
  detail_lead_text: string;
}

export interface StoryFeedPayload {
  items: StoryItem[];
  total: number;
  limit: number;
  offset: number;
  stats: StoryFeedStats;
}

export interface StoryReviewPatch {
  review_state: StoryReviewState;
  user_note?: string | null;
}

export interface StoryReviewResult {
  ok: true;
  summary_id: string;
  review_state: StoryReviewState;
}

export interface StoryEvidenceItem {
  event_id: string;
  timestamp: number | null;
  source: string | null;
  event_type: string | null;
  memory_domain: string | null;
  content: string;
}

export interface StoryEvidencePayload {
  summary_id: string;
  summary_type: string;
  summary_category: string;
  mode: 'source_ids' | 'time_window' | 'no_l1' | 'no_window';
  items: StoryEvidenceItem[];
  total: number;
}

export const memoryStoriesApi = {
  list: async (params?: {
    limit?: number;
    offset?: number;
    surface?: StoryFeedSurface;
    group?: StoryFeedGroup;
    review_state?: 'pending_confirmation' | 'confirmed' | 'neutral' | 'archived';
  }): Promise<StoryFeedPayload> => {
    const response = await api.get<StoryFeedPayload>('/memory/stories', { params });
    return unwrapGatewayPayload(response);
  },
  review: async (summaryId: string, patch: StoryReviewPatch): Promise<StoryReviewResult> => {
    const response = await api.patch<StoryReviewResult>(`/memory/stories/${summaryId}/review`, patch);
    return unwrapGatewayPayload(response);
  },
  evidence: async (summaryId: string, params?: { limit?: number }): Promise<StoryEvidencePayload> => {
    const response = await api.get<StoryEvidencePayload>(`/memory/stories/${summaryId}/evidence`, { params });
    return unwrapGatewayPayload(response);
  },
};
