import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowRight } from 'lucide-react';
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

const formatDate = (timestamp: number, locale: string): string => (
  new Intl.DateTimeFormat(locale, {
    month: 'numeric',
    day: 'numeric',
  }).format(new Date(timestamp * 1000))
);

const formatStoryPeriod = (story: StoryItem, locale: string): string => {
  if (story.period_start != null && story.period_end != null) {
    const endDate = new Date(story.period_end * 1000);
    const endsAtMidnight = endDate.getHours() === 0
      && endDate.getMinutes() === 0
      && endDate.getSeconds() === 0
      && endDate.getMilliseconds() === 0;
    const adjustedEnd = story.period_end > story.period_start && endsAtMidnight
      ? story.period_end - 1
      : story.period_end;
    const start = formatDate(story.period_start, locale);
    const end = formatDate(adjustedEnd, locale);
    return start === end ? start : `${start} – ${end}`;
  }
  return story.display_timestamp ? formatDate(story.display_timestamp, locale) : '';
};

const storyEssenceText = (story: StoryItem): string => (
  String(story.essence_prose || '').trim()
);

const storyPreviewText = (story: StoryItem): string => (
  String(story.preview_text || '').trim() || storyEssenceText(story) || story.title || story.content
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
    () => filteredItems.filter((story) => story.summary_id !== featuredStory?.summary_id),
    [featuredStory?.summary_id, filteredItems]
  );

  const visibleStats = [
    { count: stats.periodic, labelKey: 'memory.stories.stats.periodicCount' },
    { count: stats.observations, labelKey: 'memory.stories.stats.observationsCount' },
    { count: stats.tasks, labelKey: 'memory.stories.stats.tasksCount' },
  ].filter((item) => item.count > 0);

  const totalSummaryCount = stats.periodic + stats.observations + stats.tasks;

  return (
    <MemoryPageFrame
      title={t('memory.stories.title')}
      description={t('memory.stories.subtitle')}
      hideHeader
      className="max-w-[1040px] gap-3 px-5 pb-5 pt-3"
      contentClassName="pb-6"
    >
      <section data-testid="memory-stories-feed" className="space-y-6">
        {loading ? (
          <div className={`${MEMORY_EMPTY_PANEL_CLASS} flex items-center gap-2`}>
            <LoadingSpinner className="h-4 w-4" />
            <span>{t('memory.stories.loading')}</span>
          </div>
        ) : (
          <>
            <div className="flex flex-col gap-3 border-b border-[hsl(var(--memory-divider)/0.5)] sm:flex-row sm:items-end sm:justify-between">
              <nav className="flex min-w-0 flex-wrap items-center gap-5" aria-label={t('memory.stories.filters.label')}>
                  {FILTERS.map((filter) => (
                    <button
                      key={filter.id}
                      type="button"
                      onClick={() => setActiveFilter(filter.id)}
                      aria-pressed={activeFilter === filter.id}
                      className={cn(
                        'relative inline-flex h-10 items-center whitespace-nowrap px-0.5 text-sm transition-colors after:absolute after:inset-x-0 after:bottom-[-1px] after:h-0.5 after:origin-center after:rounded-sm after:bg-[hsl(var(--memory-accent))] after:transition-transform after:duration-200',
                        activeFilter === filter.id
                          ? 'font-semibold text-[hsl(var(--memory-title))] after:scale-x-100'
                          : 'font-medium text-[hsl(var(--memory-muted))] after:scale-x-0 hover:text-[hsl(var(--memory-title))]'
                      )}
                    >
                      {t(filter.labelKey)}
                    </button>
                  ))}
              </nav>

              <div
                data-testid="memory-stories-stats"
                className="flex min-h-10 flex-wrap items-center gap-x-4 gap-y-1 pb-2 text-xs text-[hsl(var(--memory-muted))] sm:justify-end"
              >
                {visibleStats.length > 0
                  ? visibleStats.map((item) => (
                    <span key={item.labelKey} className="whitespace-nowrap">
                      {t(item.labelKey, { count: item.count })}
                    </span>
                  ))
                  : <span>{t('memory.stories.stats.summaryCount', { count: totalSummaryCount })}</span>}
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
                    className="rounded-xl bg-[hsl(var(--memory-panel-elevated)/0.72)] px-6 py-7 shadow-[0_18px_48px_hsl(var(--memory-shadow)/0.035)] sm:px-8 sm:py-8"
                  >
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-xs text-[hsl(var(--memory-muted))]">
                      <span className="inline-flex rounded-md bg-[hsl(var(--memory-accent-soft)/0.64)] px-2.5 py-1 font-medium text-[hsl(var(--memory-title))]">
                        {t(storyCategoryLabelKey(featuredStory), { defaultValue: featuredStory.summary_category })}
                      </span>
                      {formatStoryPeriod(featuredStory, i18n.language) ? (
                        <span>{formatStoryPeriod(featuredStory, i18n.language)}</span>
                      ) : null}
                      {featuredStory.evidence_event_count > 0 ? (
                        <span>{t('memory.stories.evidenceChip', { count: featuredStory.evidence_event_count })}</span>
                      ) : null}
                    </div>
                    <button
                      type="button"
                      onClick={() => setDetailStory(featuredStory)}
                      aria-label={t('memory.stories.actions.readFull')}
                      className="group mt-5 block w-full rounded-md text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--memory-accent)/0.2)]"
                    >
                      <p
                        data-testid="memory-stories-featured-preview"
                        className="max-w-[760px] whitespace-pre-wrap text-[1.05rem] font-normal leading-8 text-[hsl(var(--memory-title))]"
                      >
                        {storyPreviewText(featuredStory)}
                      </p>
                      <span className="mt-5 inline-flex items-center gap-1.5 text-sm font-medium text-[hsl(var(--memory-accent))] transition-colors group-hover:text-[hsl(var(--memory-title))]">
                        {t('memory.stories.actions.readFull')}
                        <ArrowRight className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-0.5" aria-hidden="true" />
                      </span>
                    </button>
                  </article>
                ) : null}

                {feedStories.length > 0 ? (
                  <section data-testid="memory-stories-section-feed" className="space-y-2 pt-2">
                    <div className="flex items-center justify-between gap-3 px-2">
                      <h2 className="text-sm font-semibold text-[hsl(var(--memory-title))]">
                        {t('memory.stories.sections.feed')}
                      </h2>
                      <span className="text-xs text-[hsl(var(--memory-muted))]">
                        {t('memory.stories.sortHint')}
                      </span>
                    </div>
                    <div className="space-y-1">
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
                ) : null}

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
