import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { memoryStoriesApi, type StoryItem, type StoryReviewState } from '@/api/modules/memoryStories';
import StoryCard from '@/components/memory/story/StoryCard';
import StoryDetailRail from '@/components/memory/story/StoryDetailRail';
import MemoryPageFrame, { MEMORY_EMPTY_PANEL_CLASS } from './MemoryPageFrame';
import { LoadingSpinner } from '@/components/ui/loading-spinner';

export const MemoryStoryPage = () => {
  const { t } = useTranslation('app');
  const [items, setItems] = useState<StoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [detailStory, setDetailStory] = useState<StoryItem | null>(null);

  const fetchFeed = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await memoryStoriesApi.list({ limit: 30, offset: 0 });
      setItems(payload.items);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchFeed();
  }, [fetchFeed]);

  const handleReview = useCallback(async (story: StoryItem, state: StoryReviewState, userNote?: string) => {
    await memoryStoriesApi.review(story.summary_id, { review_state: state, user_note: userNote ?? null });
    setItems((prev) => prev.map((it) => (
      it.summary_id === story.summary_id ? { ...it, review_state: state } : it
    )));
  }, []);

  const handleSaveNote = useCallback(async (note: string) => {
    if (!detailStory) return;
    await memoryStoriesApi.review(detailStory.summary_id, {
      review_state: detailStory.review_state,
      user_note: note,
    });
    setItems((prev) => prev.map((it) => (
      it.summary_id === detailStory.summary_id
        ? { ...it, insight_metadata: { ...it.insight_metadata, user_note: note } }
        : it
    )));
    setDetailStory((prev) => prev
      ? { ...prev, insight_metadata: { ...prev.insight_metadata, user_note: note } }
      : prev);
  }, [detailStory]);

  return (
    <MemoryPageFrame title={t('memory.stories.title')} description={t('memory.stories.subtitle')}>
      <section data-testid="memory-stories-feed" className="space-y-3">
        {loading ? (
          <div className={`${MEMORY_EMPTY_PANEL_CLASS} flex items-center gap-2`}>
            <LoadingSpinner className="h-4 w-4" />
          </div>
        ) : items.length === 0 ? (
          <div data-testid="memory-stories-empty" className={MEMORY_EMPTY_PANEL_CLASS}>
            <div className="font-semibold text-[hsl(var(--memory-title))]">{t('memory.stories.emptyTitle')}</div>
            <p className="mt-1 text-sm">{t('memory.stories.emptyBody')}</p>
          </div>
        ) : (
          items.map((story) => (
            <StoryCard
              key={story.summary_id}
              story={story}
              onConfirm={() => void handleReview(story, 'confirmed')}
              onReject={() => void handleReview(story, 'rejected')}
              onArchive={() => void handleReview(story, 'archived')}
              onOpenDetail={() => setDetailStory(story)}
            />
          ))
        )}
      </section>

      <StoryDetailRail
        story={detailStory}
        onClose={() => setDetailStory(null)}
        onSaveNote={handleSaveNote}
      />
    </MemoryPageFrame>
  );
};

export default MemoryStoryPage;
