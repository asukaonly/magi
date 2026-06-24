import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { memoryStoriesApi, type StoryItem } from '@/api/modules/memoryStories';
import StoryCard from '@/components/memory/story/StoryCard';
import StoryDetailRail from '@/components/memory/story/StoryDetailRail';
import MemoryPageFrame, { MEMORY_EMPTY_PANEL_CLASS } from './MemoryPageFrame';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { isSummaryInsightStory } from './storyFilters';
import { cn } from '@/lib/utils';

type StoryFilter = 'all' | 'periodic' | 'observations' | 'tasks';

const FILTERS: Array<{ id: StoryFilter; labelKey: string }> = [
  { id: 'all', labelKey: 'memory.stories.filters.all' },
  { id: 'periodic', labelKey: 'memory.stories.filters.periodic' },
  { id: 'observations', labelKey: 'memory.stories.filters.observations' },
  { id: 'tasks', labelKey: 'memory.stories.filters.tasks' },
];

const PAGE_SIZE = 30;

const TEMPORAL_CATEGORIES = new Set(['day', 'week', 'month', 'quarter', 'year']);
const OBSERVATION_CATEGORIES = new Set([
  'trend_shift',
  'preference_emergence',
  'conflict_resolution',
  'risk_escalation',
]);
const TASK_CATEGORIES = new Set(['task_reflection', 'goal_refinement', 'milestone_review']);

const isTemporalStory = (story: StoryItem): boolean => (
  story.summary_type !== 'insight' || TEMPORAL_CATEGORIES.has(story.summary_category)
);

const storyTimestamp = (story: StoryItem): number => (
  story.period_end || story.updated_at || story.period_start || 0
);

const formatStoryDate = (story: StoryItem, locale: string): string => {
  const timestamp = storyTimestamp(story);
  if (!timestamp) return '';
  return new Intl.DateTimeFormat(locale, {
    month: 'numeric',
    day: 'numeric',
  }).format(new Date(timestamp * 1000));
};

const matchesFilter = (story: StoryItem, filter: StoryFilter): boolean => {
  switch (filter) {
    case 'periodic':
      return isTemporalStory(story);
    case 'observations':
      return OBSERVATION_CATEGORIES.has(story.summary_category);
    case 'tasks':
      return TASK_CATEGORIES.has(story.summary_category);
    default:
      return true;
  }
};

const storyPrimaryText = (story: StoryItem): string => story.title || story.content;

const storySecondaryText = (story: StoryItem): string => (
  story.title ? story.content : ''
);

export const MemoryStoryPage = () => {
  const { t, i18n } = useTranslation('app');
  const [items, setItems] = useState<StoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [detailStory, setDetailStory] = useState<StoryItem | null>(null);
  const [activeFilter, setActiveFilter] = useState<StoryFilter>('all');

  const fetchFeed = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await memoryStoriesApi.list({ limit: PAGE_SIZE, offset: 0 });
      setItems(payload.items);
      setHasMore(payload.items.length === PAGE_SIZE);
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
    setDetailStory((current) => (
      current?.summary_id === story.summary_id ? { ...current, review_state: 'archived' } : current
    ));
  }, []);

  const handleLoadMore = useCallback(async () => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    try {
      const payload = await memoryStoriesApi.list({ limit: PAGE_SIZE, offset: items.length });
      setItems((prev) => [...prev, ...payload.items]);
      setHasMore(payload.items.length === PAGE_SIZE);
    } finally {
      setLoadingMore(false);
    }
  }, [hasMore, items.length, loadingMore]);

  const summaryItems = useMemo(
    () => items.filter((story) => isSummaryInsightStory(story) || isTemporalStory(story)),
    [items]
  );

  const visibleBaseItems = useMemo(
    () => summaryItems.filter((story) => story.review_state !== 'archived'),
    [summaryItems]
  );

  const filteredItems = useMemo(
    () => visibleBaseItems.filter((story) => matchesFilter(story, activeFilter)),
    [activeFilter, visibleBaseItems]
  );

  const featuredStory = useMemo(
    () => (
      filteredItems.find((story) => ['week', 'month', 'quarter', 'year'].includes(story.summary_category))
      || filteredItems[0]
      || null
    ),
    [filteredItems]
  );

  const focusStories = useMemo(
    () => filteredItems.filter((story) => story.summary_id !== featuredStory?.summary_id).slice(0, 3),
    [featuredStory?.summary_id, filteredItems]
  );

  const feedStories = useMemo(
    () => {
      const withoutFeatured = filteredItems.filter((story) => story.summary_id !== featuredStory?.summary_id);
      return withoutFeatured.length > 0 ? withoutFeatured : filteredItems;
    },
    [featuredStory?.summary_id, filteredItems]
  );

  const timelineStories = filteredItems.filter(isTemporalStory).slice(0, 4);

  const statItems = visibleBaseItems;
  const insightCount = statItems.filter((story) => story.summary_type === 'insight').length;
  const temporalCount = statItems.filter(isTemporalStory).length;
  const observationCount = statItems.filter((story) => OBSERVATION_CATEGORIES.has(story.summary_category)).length;

  return (
    <MemoryPageFrame
      title={t('memory.stories.title')}
      description={t('memory.stories.subtitle')}
      hideHeader
      className="max-w-[1240px] gap-3 px-4 py-4 lg:px-6 lg:py-6"
      contentClassName="pb-6"
    >
      <section data-testid="memory-stories-feed" className="space-y-5">
        {loading ? (
          <div className={`${MEMORY_EMPTY_PANEL_CLASS} flex items-center gap-2`}>
            <LoadingSpinner className="h-4 w-4" />
            <span>{t('memory.stories.loading')}</span>
          </div>
        ) : (
          <>
            <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <div className="flex max-w-full overflow-x-auto rounded-xl border border-[hsl(var(--memory-border)/0.58)] bg-[hsl(var(--memory-panel-elevated)/0.78)] p-1">
                  {FILTERS.map((filter) => (
                    <button
                      key={filter.id}
                      type="button"
                      onClick={() => setActiveFilter(filter.id)}
                      className={cn(
                        'whitespace-nowrap rounded-lg px-3.5 py-2 text-sm font-medium transition-colors',
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

              <div className="grid grid-cols-3 gap-2 sm:flex sm:items-center">
                <div className="rounded-xl border border-[hsl(var(--memory-border)/0.52)] bg-[hsl(var(--memory-panel-elevated)/0.58)] px-4 py-2.5">
                  <div className="text-lg font-semibold leading-none text-[hsl(var(--memory-title))]">{insightCount}</div>
                  <div className="mt-1 text-xs text-[hsl(var(--memory-muted))]">{t('memory.stories.stats.highlights')}</div>
                </div>
                <div className="rounded-xl border border-[hsl(var(--memory-border)/0.52)] bg-[hsl(var(--memory-panel-elevated)/0.58)] px-4 py-2.5">
                  <div className="text-lg font-semibold leading-none text-[hsl(var(--memory-title))]">{temporalCount}</div>
                  <div className="mt-1 text-xs text-[hsl(var(--memory-muted))]">{t('memory.stories.stats.periodic')}</div>
                </div>
                <div className="rounded-xl border border-[hsl(var(--memory-border)/0.52)] bg-[hsl(var(--memory-panel-elevated)/0.58)] px-4 py-2.5">
                  <div className="text-lg font-semibold leading-none text-[hsl(var(--memory-title))]">{observationCount}</div>
                  <div className="mt-1 text-xs text-[hsl(var(--memory-muted))]">{t('memory.stories.stats.observations')}</div>
                </div>
              </div>
            </div>

            {filteredItems.length === 0 ? (
              <div className={MEMORY_EMPTY_PANEL_CLASS}>
                <p className="text-sm">{t('memory.stories.emptyBody')}</p>
              </div>
            ) : (
              <>
                <div className={cn(
                  'grid gap-4',
                  focusStories.length > 0 ? 'xl:grid-cols-[1.08fr_0.92fr]' : ''
                )}>
                  {featuredStory ? (
                    <article
                      className="rounded-2xl border border-[hsl(var(--memory-border)/0.56)] bg-[linear-gradient(135deg,hsl(var(--memory-accent-soft)/0.26),hsl(var(--memory-panel-elevated)/0.86))] px-6 py-6"
                    >
                      <div className="mb-3 inline-flex rounded-full bg-sky-50 px-2.5 py-1 text-xs font-medium text-sky-700">
                        {t('memory.stories.heroLabel')}
                      </div>
                      <button
                        type="button"
                        onClick={() => setDetailStory(featuredStory)}
                        className="block text-left text-[1.35rem] font-semibold leading-9 text-[hsl(var(--memory-title))] transition-colors hover:text-[hsl(var(--memory-accent))]"
                      >
                        {storyPrimaryText(featuredStory)}
                      </button>
                      {storySecondaryText(featuredStory) ? (
                        <p className="mt-4 max-w-3xl text-sm leading-7 text-[hsl(var(--memory-body))]">
                          {storySecondaryText(featuredStory)}
                        </p>
                      ) : null}
                      <div className="mt-7 flex flex-wrap items-center gap-2 text-xs text-[hsl(var(--memory-muted))]">
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

                  {focusStories.length > 0 ? (
                    <div className="overflow-hidden rounded-2xl border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-elevated)/0.72)]">
                      {focusStories.map((story, index) => (
                        <button
                          key={story.summary_id}
                          type="button"
                          onClick={() => setDetailStory(story)}
                          className="grid w-full grid-cols-[10px_minmax(0,1fr)] gap-4 border-b border-[hsl(var(--memory-divider)/0.58)] px-5 py-4 text-left last:border-b-0 hover:bg-[hsl(var(--memory-panel-subtle)/0.34)]"
                        >
                          <span
                            className={cn(
                              'mt-1 h-9 rounded-full',
                              index === 0 && 'bg-sky-500/70',
                              index === 1 && 'bg-emerald-600/70',
                              index === 2 && 'bg-amber-600/70'
                            )}
                          />
                          <span className="min-w-0">
                            <span className="block text-sm font-semibold leading-6 text-[hsl(var(--memory-title))]">
                              {storyPrimaryText(story)}
                            </span>
                            {storySecondaryText(story) ? (
                              <span className="mt-1 block text-sm leading-6 text-[hsl(var(--memory-body))]">
                                {storySecondaryText(story)}
                              </span>
                            ) : null}
                          </span>
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>

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

                {timelineStories.length > 0 ? (
                  <section data-testid="memory-stories-section-periodic" className="grid gap-3 border-t border-[hsl(var(--memory-divider)/0.62)] pt-5 md:grid-cols-2 xl:grid-cols-4">
                    {timelineStories.map((story) => (
                      <button
                        key={story.summary_id}
                        type="button"
                        onClick={() => setDetailStory(story)}
                        className="rounded-2xl border border-[hsl(var(--memory-border)/0.5)] bg-[hsl(var(--memory-panel-elevated)/0.52)] px-4 py-3 text-left transition-colors hover:bg-[hsl(var(--memory-panel-elevated)/0.82)]"
                      >
                        <span className="text-sm font-semibold text-[hsl(var(--memory-title))]">
                          {t(`memory.stories.categories.${story.summary_category}`, { defaultValue: story.summary_category })}
                        </span>
                        <span className="mt-2 block text-xs leading-5 text-[hsl(var(--memory-body))]">
                          {storyPrimaryText(story)}
                        </span>
                      </button>
                    ))}
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
