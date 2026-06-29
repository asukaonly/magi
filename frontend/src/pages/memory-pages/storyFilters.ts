import type { StoryItem } from '@/api/modules/memoryStories';

export const isMemoryUpdateStory = (story: StoryItem): boolean => (
  story.feed_group === 'memory_update'
);

export const isSummaryInsightStory = (story: StoryItem): boolean => (
  story.summary_feed_visible && !isMemoryUpdateStory(story)
);
