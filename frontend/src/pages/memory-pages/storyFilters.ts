import type { StoryItem } from '@/api/modules/memoryStories';

const MEMORY_UPDATE_CATEGORIES = new Set(['state_change']);

export const isMemoryUpdateStory = (story: StoryItem): boolean => (
  story.summary_type === 'insight' && MEMORY_UPDATE_CATEGORIES.has(story.summary_category)
);

export const isSummaryInsightStory = (story: StoryItem): boolean => (
  story.summary_type === 'insight' && !isMemoryUpdateStory(story)
);
