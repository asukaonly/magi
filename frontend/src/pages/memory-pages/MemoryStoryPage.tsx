import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  memoryStoriesApi,
  type StoryFeedGroup,
  type StoryFeedStats,
  type StoryItem,
} from '@/api/modules/memoryStories';
import StoryCard from '@/components/memory/story/StoryCard';
import StoryDetailRail from '@/components/memory/story/StoryDetailRail';
import MemoryPageFrame, { MEMORY_EMPTY_PANEL_CLASS } from './MemoryPageFrame';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { MarkdownBlock } from '@/components/ui/markdown-block';
import { cn } from '@/lib/utils';

type StoryFilter = 'all' | Exclude<StoryFeedGroup, 'memory_update'>;

const FILTERS: Array<{ id: StoryFilter; labelKey: string }> = [
  { id: 'all', labelKey: 'memory.stories.filters.all' },
  { id: 'periodic', labelKey: 'memory.stories.filters.periodic' },
  { id: 'observations', labelKey: 'memory.stories.filters.observations' },
  { id: 'tasks', labelKey: 'memory.stories.filters.tasks' },
];

const PAGE_SIZE = 30;

const EMPTY_STATS: StoryFeedStats = {
  highlights: 0,
  periodic: 0,
  observations: 0,
  tasks: 0,
};

const storyTimestamp = (story: StoryItem): number => (
  story.display_timestamp || 0
);

const formatStoryDate = (story: StoryItem, locale: string): string => {
  const timestamp = storyTimestamp(story);
  if (!timestamp) return '';
  return new Intl.DateTimeFormat(locale, {
    month: 'numeric',
    day: 'numeric',
  }).format(new Date(timestamp * 1000));
};

const storyEssenceText = (story: StoryItem): string => (
  String(story.essence_prose || '').trim()
);

const storyPreviewText = (story: StoryItem): string => (
  String(story.preview_text || '').trim() || storyEssenceText(story) || story.title || story.content
);

const storyDetailLeadText = (story: StoryItem): string => (
  String(story.detail_lead_text || '').trim()
);

const storyCategoryLabelKey = (story: StoryItem): string => (
  `memory.stories.categories.${story.summary_category}`
);

const groupForFilter = (filter: StoryFilter): Exclude<StoryFeedGroup, 'memory_update'> | undefined => (
  filter === 'all' ? undefined : filter
);

const decrementStatsForStory = (stats: StoryFeedStats, story: StoryItem): StoryFeedStats => {
  if (!story.summary_feed_visible || story.review_state === 'archived') {
    return stats;
  }
  return {
    highlights: Math.max(0, stats.highlights - (story.summary_type === 'insight' ? 1 : 0)),
    periodic: Math.max(0, stats.periodic - (story.feed_group === 'periodic' ? 1 : 0)),
    observations: Math.max(0, stats.observations - (story.feed_group === 'observations' ? 1 : 0)),
    tasks: Math.max(0, stats.tasks - (story.feed_group === 'tasks' ? 1 : 0)),
  };
};

export const MemoryStoryPage = () => {
  const { t, i18n } = useTranslation('app');
  const [items, setItems] = useState<StoryItem[]>([]);
  const [stats, setStats] = useState<StoryFeedStats>(EMPTY_STATS);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [detailStory, setDetailStory] = useState<StoryItem | null>(null);
  const [activeFilter, setActiveFilter] = useState<StoryFilter>('all');

  const fetchFeed = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await memoryStoriesApi.list({
        limit: PAGE_SIZE,
        offset: 0,
        surface: 'summary',
        group: groupForFilter(activeFilter),
      });
      setItems(payload.items);
      setStats(payload.stats || EMPTY_STATS);
      setHasMore(payload.items.length === PAGE_SIZE);
    } finally {
      setLoading(false);
    }
  }, [activeFilter]);

  useEffect(() => {
    void fetchFeed();
  }, [fetchFeed]);

  const handleArchive = useCallback(async (story: StoryItem) => {
    await memoryStoriesApi.review(story.summary_id, { review_state: 'archived' });
    setStats((current) => decrementStatsForStory(current, story));
    setItems((prev) => prev.map((it) =>
      it.summary_id === story.summary_id ? { ...it, review_state: 'archived' } : it
    ));
    setDetailStory((current) => (
      current?.summary_id === story.summary_id ? { ...current, review_state: 'archived' } : current
    ));
  }, []);

  const handleLoadMore = useCallback(async () => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    try {
      const payload = await memoryStoriesApi.list({
        limit: PAGE_SIZE,
        offset: items.length,
        surface: 'summary',
        group: groupForFilter(activeFilter),
      });
      setItems((prev) => [...prev, ...payload.items]);
      setStats(payload.stats || EMPTY_STATS);
      setHasMore(payload.items.length === PAGE_SIZE);
    } finally {
      setLoadingMore(false);
    }
  }, [activeFilter, hasMore, items.length, loadingMore]);

  const summaryItems = useMemo(
    () => items.filter((story) => story.summary_feed_visible),
    [items]
  );

  const visibleBaseItems = useMemo(
    () => summaryItems.filter((story) => story.review_state !== 'archived'),
    [summaryItems]
  );

  const filteredItems = visibleBaseItems;

  const featuredStory = useMemo(
    () => (
      filteredItems.find((story) => story.featured_rank !== null && story.featured_rank !== undefined)
      || filteredItems[0]
      || null
    ),
    [filteredItems]
  );

  const feedStories = useMemo(
    () => {
      const withoutFeatured = filteredItems.filter((story) => story.summary_id !== featuredStory?.summary_id);
      return withoutFeatured.length > 0 ? withoutFeatured : filteredItems;
    },
    [featuredStory?.summary_id, filteredItems]
  );

  return (
    <MemoryPageFrame
      title={t('memory.stories.title')}
      description={t('memory.stories.subtitle')}
      hideHeader
      className="max-w-[900px] gap-3 px-4 pb-4 pt-3"
      contentClassName="pb-6"
    >
      <section data-testid="memory-stories-feed" className="space-y-4">
        {loading ? (
          <div className={`${MEMORY_EMPTY_PANEL_CLASS} flex items-center gap-2`}>
            <LoadingSpinner className="h-4 w-4" />
            <span>{t('memory.stories.loading')}</span>
          </div>
        ) : (
          <>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <div className="inline-flex w-fit max-w-full flex-wrap gap-0.5 rounded-lg border border-[hsl(var(--memory-border)/0.58)] bg-[hsl(var(--memory-panel-elevated)/0.72)] p-0.5">
                  {FILTERS.map((filter) => (
                    <button
                      key={filter.id}
                      type="button"
                      onClick={() => setActiveFilter(filter.id)}
                      className={cn(
                        'inline-flex h-8 items-center whitespace-nowrap rounded-md px-2.5 text-sm font-medium transition-colors',
                        activeFilter === filter.id
                          ? 'bg-[hsl(var(--memory-title))] text-[hsl(var(--memory-panel))]'
                          : 'text-[hsl(var(--memory-body))] hover:bg-[hsl(var(--memory-panel-subtle)/0.62)]'
                      )}
                    >
                      {t(filter.labelKey)}
                    </button>
                  ))}
                </div>
              </div>

              <div
                data-testid="memory-stories-stats"
                className="inline-flex h-8 w-fit max-w-full items-center gap-2 rounded-lg border border-[hsl(var(--memory-border)/0.52)] bg-[hsl(var(--memory-panel-elevated)/0.58)] px-2.5 text-xs text-[hsl(var(--memory-muted))]"
              >
                <span className="inline-flex items-center gap-1 whitespace-nowrap">
                  <span className="font-semibold text-[hsl(var(--memory-title))]">{stats.highlights}</span>
                  <span>{t('memory.stories.stats.highlights')}</span>
                </span>
                <span className="h-3 w-px bg-[hsl(var(--memory-divider)/0.78)]" aria-hidden="true" />
                <span className="inline-flex items-center gap-1 whitespace-nowrap">
                  <span className="font-semibold text-[hsl(var(--memory-title))]">{stats.periodic}</span>
                  <span>{t('memory.stories.stats.periodic')}</span>
                </span>
                <span className="h-3 w-px bg-[hsl(var(--memory-divider)/0.78)]" aria-hidden="true" />
                <span className="inline-flex items-center gap-1 whitespace-nowrap">
                  <span className="font-semibold text-[hsl(var(--memory-title))]">{stats.observations}</span>
                  <span>{t('memory.stories.stats.observations')}</span>
                </span>
              </div>
            </div>

            {filteredItems.length === 0 ? (
              <div className={MEMORY_EMPTY_PANEL_CLASS}>
                <p className="text-sm">{t('memory.stories.emptyBody')}</p>
              </div>
            ) : (
              <>
                {featuredStory ? (
                  <article
                    data-testid="memory-stories-featured"
                    className="rounded-lg border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-elevated)/0.72)] px-4 py-4"
                  >
                    <div className="mb-2 inline-flex rounded-full bg-sky-50 px-2.5 py-1 text-xs font-medium text-sky-700">
                      {t(storyCategoryLabelKey(featuredStory), { defaultValue: featuredStory.summary_category })}
                    </div>
                    <div
                      role="button"
                      tabIndex={0}
                      onClick={() => setDetailStory(featuredStory)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault();
                          setDetailStory(featuredStory);
                        }
                      }}
                      className="cursor-pointer text-left transition-colors hover:text-[hsl(var(--memory-accent))] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--memory-accent)/0.3)]"
                    >
                      <MarkdownBlock className="text-base font-semibold leading-7 text-[hsl(var(--memory-title))] [&_h1]:mb-3 [&_h1]:border-0 [&_h1]:pb-0 [&_h1]:text-lg [&_h2]:mb-2 [&_h2]:mt-3 [&_h2]:text-base [&_h2]:normal-case [&_h2]:tracking-normal [&_h2]:text-[hsl(var(--memory-title))] [&_li]:text-base [&_p]:text-base [&_p]:leading-7">
                        {storyPreviewText(featuredStory)}
                      </MarkdownBlock>
                    </div>
                    {storyDetailLeadText(featuredStory) ? (
                      <MarkdownBlock className="mt-2 text-sm leading-6 text-[hsl(var(--memory-body))]">
                        {storyDetailLeadText(featuredStory)}
                      </MarkdownBlock>
                    ) : null}
                    <div className="mt-4 flex flex-wrap items-center gap-2 text-xs text-[hsl(var(--memory-muted))]">
                      {formatStoryDate(featuredStory, i18n.language) ? <span>{formatStoryDate(featuredStory, i18n.language)}</span> : null}
                      {featuredStory.evidence_event_count > 0 ? (
                        <>
                          <span>·</span>
                          <span>{t('memory.stories.evidenceChip', { count: featuredStory.evidence_event_count })}</span>
                        </>
                      ) : null}
                    </div>
                  </article>
                ) : null}

                <section data-testid="memory-stories-section-feed" className="space-y-3">
                  <div className="flex items-center justify-between gap-3">
                    <h2 className="text-sm font-semibold text-[hsl(var(--memory-body))]">
                      {t('memory.stories.sections.feed')}
                    </h2>
                    <span className="text-xs text-[hsl(var(--memory-muted))]">
                      {t('memory.stories.sortHint')}
                    </span>
                  </div>
                  <div className="overflow-hidden rounded-2xl border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-elevated)/0.72)]">
                    {feedStories.map((story) => (
                      <StoryCard
                        key={story.summary_id}
                        story={story}
                        onArchive={() => void handleArchive(story)}
                        onOpenDetail={() => setDetailStory(story)}
                      />
                    ))}
                  </div>
                </section>

                <div className="flex justify-center pt-1">
                  {hasMore ? (
                    <button
                      type="button"
                      onClick={() => void handleLoadMore()}
                      disabled={loadingMore}
                      className="rounded-xl border border-[hsl(var(--memory-border)/0.58)] bg-[hsl(var(--memory-panel-elevated)/0.72)] px-5 py-2.5 text-sm font-medium text-[hsl(var(--memory-title))] transition-colors hover:bg-[hsl(var(--memory-panel-elevated)/0.92)] disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {loadingMore ? t('memory.stories.pagination.loading') : t('memory.stories.pagination.loadMore')}
                    </button>
                  ) : summaryItems.length > 0 ? (
                    <span className="text-xs text-[hsl(var(--memory-muted))]">
                      {t('memory.stories.pagination.end')}
                    </span>
                  ) : null}
                </div>
              </>
            )}
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
