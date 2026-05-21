import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { memoryStoriesApi, type StoryItem } from '@/api/modules/memoryStories';
import StoryCard from '@/components/memory/story/StoryCard';
import StoryDetailRail from '@/components/memory/story/StoryDetailRail';
import MemoryPageFrame, { MEMORY_EMPTY_PANEL_CLASS } from './MemoryPageFrame';
import { LoadingSpinner } from '@/components/ui/loading-spinner';

interface StorySectionProps {
  title: string;
  emptyText: string;
  stories: StoryItem[];
  onArchive: (s: StoryItem) => void;
  onOpenDetail: (s: StoryItem) => void;
  testId: string;
}

const StorySection = ({
  title, emptyText, stories,
  onArchive, onOpenDetail,
  testId,
}: StorySectionProps) => (
  <section data-testid={testId} className="space-y-3">
    <h2 className="text-sm font-medium text-[hsl(var(--memory-muted))]">{title}</h2>
    {stories.length === 0 ? (
      <div className={MEMORY_EMPTY_PANEL_CLASS}>
        <p className="text-sm">{emptyText}</p>
      </div>
    ) : (
      stories.map((story) => (
        <StoryCard
          key={story.summary_id}
          story={story}
          onArchive={() => onArchive(story)}
          onOpenDetail={() => onOpenDetail(story)}
        />
      ))
    )}
  </section>
);

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

  const handleArchive = useCallback(async (story: StoryItem) => {
    await memoryStoriesApi.review(story.summary_id, { review_state: 'archived' });
    setItems((prev) => prev.map((it) =>
      it.summary_id === story.summary_id ? { ...it, review_state: 'archived' } : it
    ));
  }, []);

  return (
    <MemoryPageFrame title={t('memory.stories.title')} description={t('memory.stories.subtitle')}>
      <section data-testid="memory-stories-feed" className="space-y-6">
        {loading ? (
          <div className={`${MEMORY_EMPTY_PANEL_CLASS} flex items-center gap-2`}>
            <LoadingSpinner className="h-4 w-4" />
          </div>
        ) : (
          <>
            <StorySection
              title={t('memory.stories.sections.reflections')}
              emptyText={t('memory.stories.sections.reflectionsEmpty')}
              stories={items.filter((s) => s.summary_type === 'insight')}
              onArchive={(s) => void handleArchive(s)}
              onOpenDetail={(s) => setDetailStory(s)}
              testId="memory-stories-section-reflections"
            />
            <StorySection
              title={t('memory.stories.sections.periodic')}
              emptyText={t('memory.stories.sections.periodicEmpty')}
              stories={items.filter((s) => s.summary_type !== 'insight')}
              onArchive={(s) => void handleArchive(s)}
              onOpenDetail={(s) => setDetailStory(s)}
              testId="memory-stories-section-periodic"
            />
          </>
        )}
      </section>

      <StoryDetailRail
        story={detailStory}
        onClose={() => setDetailStory(null)}
      />
    </MemoryPageFrame>
  );
};

export default MemoryStoryPage;
