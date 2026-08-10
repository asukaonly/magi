import type { L2ExperienceSeed, L2PendingReview } from '@/api/modules/memory';
import type { StoryItem } from '@/api/modules/memoryStories';
import type { NotificationItem } from '@/api/modules/notifications';

export type PendingAction = 'confirmed' | 'rejected';
export type ConflictAction = 'confirm' | 'reject';
export type PendingFilter = 'all' | 'memory' | 'experiences' | 'observations';
export type PendingReviewAction = 'confirm' | 'reject' | 'edit';

export interface PendingFilterOption {
  key: PendingFilter;
  labelKey: string;
  count: number;
}

export const buildPendingFilterOptions = ({
  totalCount,
  memoryCount,
  experienceCount,
  observationCount,
}: {
  totalCount: number;
  memoryCount: number;
  experienceCount: number;
  observationCount: number;
}): PendingFilterOption[] => [
  {
    key: 'all',
    labelKey: 'memory.pending.filters.all',
    count: totalCount,
  },
  {
    key: 'memory',
    labelKey: 'memory.pending.filters.memory',
    count: memoryCount,
  },
  {
    key: 'experiences',
    labelKey: 'memory.pending.filters.experiences',
    count: experienceCount,
  },
  {
    key: 'observations',
    labelKey: 'memory.pending.filters.observations',
    count: observationCount,
  },
];

export const storyTitle = (story: StoryItem, fallback: string): string => (
  String(story.title || story.preview_text || '').trim() || fallback
);

export const seedTitle = (seed: L2ExperienceSeed, fallback: string): string => (
  String(seed.display_title || seed.title || '').trim() || fallback
);

export const seedBody = (seed: L2ExperienceSeed): string => (
  String(seed.display_description || seed.description || '').trim()
);

export const conflictTitle = (notification: NotificationItem, fallback: string): string => (
  String(notification.title || notification.payload.trait_name || '').trim() || fallback
);

export const conflictBody = (notification: NotificationItem): string => (
  String(notification.body || notification.payload.inferred_value || '').trim()
);

export const pendingReviewValue = (review: L2PendingReview, fallback: string): string => (
  String(review.proposed.trait_value || '').trim() || fallback
);

export const pendingReviewSummary = (review: L2PendingReview, fallback: string): string => (
  String(review.proposed.natural_summary || '').trim() || fallback
);

export const isCurrentPlanReview = (review: L2PendingReview): boolean => (
  review.kind === 'goal_currentness'
);

export const isOpenProfileConflict = (notification: NotificationItem): boolean => (
  notification.payload?.conflict_type === 'profile_conflict' &&
  (notification.status === 'unread' || notification.status === 'read')
);
