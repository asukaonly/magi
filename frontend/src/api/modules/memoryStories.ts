import { api, unwrapGatewayPayload } from '../client';

export type StoryReviewState =
  | 'neutral'
  | 'pending_confirmation'
  | 'confirmed'
  | 'rejected'
  | 'archived';

export type StorySummaryCategory = string;

export interface StoryItem {
  summary_id: string;
  summary_type: 'insight' | 'temporal' | 'thematic' | string;
  summary_category: StorySummaryCategory;
  title: string;
  content: string;
  period_start: number | null;
  period_end: number | null;
  updated_at: number;
  review_state: StoryReviewState;
  insight_key: string | null;
  insight_metadata: Record<string, unknown>;
  evidence_event_count: number;
}

export interface StoryFeedPayload {
  items: StoryItem[];
  total: number;
  limit: number;
  offset: number;
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

export const memoryStoriesApi = {
  list: async (params?: { limit?: number; offset?: number }): Promise<StoryFeedPayload> => {
    const response = await api.get<StoryFeedPayload>('/memory/stories', { params });
    return unwrapGatewayPayload(response);
  },
  review: async (summaryId: string, patch: StoryReviewPatch): Promise<StoryReviewResult> => {
    const response = await api.patch<StoryReviewResult>(`/memory/stories/${summaryId}/review`, patch);
    return unwrapGatewayPayload(response);
  },
};
