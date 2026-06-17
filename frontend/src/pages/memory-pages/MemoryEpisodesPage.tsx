import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  BookOpen,
  CalendarRange,
  Filter,
  Layers,
  Search,
  Sparkles,
  Star,
  Tags,
} from 'lucide-react';
import {
  memoryApi,
  type EpisodeReconsolidateResult,
  type L2ExperienceReviewDetail,
  type L2ExperienceWithReview,
} from '@/api/modules/memory';
import ExperienceDetail from '@/components/memory/experiences/ExperienceDetail';
import {
  formatExperienceTag,
  getExperienceDescription,
  getExperienceDisplayTitle,
  getExperienceEntityLabels,
} from '@/components/memory/experiences/ExperienceRow';
import { formatEpisodeTimeRange } from '@/components/memory/episodes/EpisodeRow';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import MemoryPageFrame, { MEMORY_EMPTY_PANEL_CLASS, MEMORY_INFO_PANEL_CLASS } from './MemoryPageFrame';

const getExperienceReviewTimestamp = (experience: L2ExperienceWithReview): number => Math.max(
  Number(experience.updated_at ?? 0),
  Number(experience.experience_review?.updated_at ?? 0),
  Number(experience.time_end ?? 0),
  Number(experience.time_start ?? 0),
  0
);

export const sortExperiencesForReview = (
  items: L2ExperienceWithReview[]
): L2ExperienceWithReview[] => [...items].sort((a, b) => {
  if (Boolean(a.user_pinned) !== Boolean(b.user_pinned)) {
    return a.user_pinned ? -1 : 1;
  }
  const updatedDiff = getExperienceReviewTimestamp(b) - getExperienceReviewTimestamp(a);
  if (updatedDiff !== 0) {
    return updatedDiff;
  }
  return Number(b.narrative_score ?? 0) - Number(a.narrative_score ?? 0);
});

const normalizeTags = (items: string[] | null | undefined): string[] => (
  Array.isArray(items)
    ? items.map(formatExperienceTag).filter((item) => Boolean(item && item.trim()))
    : []
);

const uniqueItems = (items: string[]): string[] => Array.from(new Set(items.filter(Boolean)));

const getExperienceTags = (experience: L2ExperienceWithReview, limit = 8): string[] => uniqueItems([
  ...getExperienceEntityLabels(experience),
  ...normalizeTags(experience.primary_topic_keys),
  ...normalizeTags(experience.primary_place_ids),
]).slice(0, limit);

const getExperienceSearchText = (experience: L2ExperienceWithReview, fallback: string): string => [
  getExperienceDisplayTitle(experience, fallback),
  getExperienceDescription(experience),
  ...getExperienceTags(experience, 12),
].join(' ').toLowerCase();

const getExperienceTime = (experience: L2ExperienceWithReview): number => (
  Number(experience.time_start ?? experience.time_end ?? experience.updated_at ?? 0)
);

const getMonthKey = (experience: L2ExperienceWithReview): string => {
  const time = getExperienceTime(experience);
  if (!time) {
    return 'unknown';
  }
  const date = new Date(time * 1000);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
};

const getMonthLabel = (key: string, locale: string, unknownLabel: string): string => {
  if (key === 'unknown') {
    return unknownLabel;
  }
  const [year, month] = key.split('-').map((value) => Number(value));
  return new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: 'long',
  }).format(new Date(year, month - 1, 1));
};

const groupExperiencesByMonth = (
  items: L2ExperienceWithReview[],
  locale: string,
  unknownLabel: string
): Array<{ key: string; label: string; items: L2ExperienceWithReview[] }> => {
  const groups = new Map<string, L2ExperienceWithReview[]>();
  items.forEach((experience) => {
    const key = getMonthKey(experience);
    groups.set(key, [...(groups.get(key) ?? []), experience]);
  });
  return Array.from(groups.entries()).map(([key, groupItems]) => ({
    key,
    label: getMonthLabel(key, locale, unknownLabel),
    items: groupItems,
  }));
};

export const MemoryEpisodesPage = () => {
  const { t, i18n } = useTranslation('app');
  const [experiences, setExperiences] = useState<L2ExperienceWithReview[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<L2ExperienceReviewDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [reconsolidating, setReconsolidating] = useState(false);
  const [reconsolidateResult, setReconsolidateResult] = useState<EpisodeReconsolidateResult | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [pinnedOnly, setPinnedOnly] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await memoryApi.listExperiences({ status: 'active', limit: 100, offset: 0 });
      const nextItems = payload.items;
      setExperiences(nextItems);
      setSelectedId((current) => {
        if (current && nextItems.some((item) => item.experience_id === current)) {
          return current;
        }
        return sortExperiencesForReview(nextItems)[0]?.experience_id ?? null;
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setDetailLoading(false);
      return;
    }
    let cancelled = false;
    setDetail(null);
    setDetailLoading(true);
    void memoryApi.getExperience(selectedId)
      .then((payload) => {
        if (!cancelled && payload.experience_id === selectedId) {
          setDetail(payload);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setDetailLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const sortedExperiences = useMemo(() => sortExperiencesForReview(experiences), [experiences]);

  const filteredExperiences = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return sortedExperiences.filter((experience) => {
      if (pinnedOnly && !experience.user_pinned) {
        return false;
      }
      if (!query) {
        return true;
      }
      return getExperienceSearchText(experience, t('memory.episodes.awaitingLabel')).includes(query);
    });
  }, [pinnedOnly, searchQuery, sortedExperiences, t]);

  useEffect(() => {
    if (filteredExperiences.length === 0) {
      return;
    }
    if (!selectedId || !filteredExperiences.some((experience) => experience.experience_id === selectedId)) {
      setSelectedId(filteredExperiences[0].experience_id);
    }
  }, [filteredExperiences, selectedId]);

  const groupedExperiences = useMemo(
    () => groupExperiencesByMonth(filteredExperiences, i18n.language, t('memory.episodes.unknownMonth')),
    [filteredExperiences, i18n.language, t]
  );

  const selectedListExperience = useMemo(
    () => experiences.find((experience) => experience.experience_id === selectedId) ?? null,
    [experiences, selectedId]
  );
  const selectedExperience = detail ?? selectedListExperience;
  const featuredExperience = selectedListExperience ?? filteredExperiences[0] ?? sortedExperiences[0] ?? null;
  const selectedTitle = selectedExperience
    ? getExperienceDisplayTitle(selectedExperience, t('memory.episodes.awaitingLabel'))
    : '';

  const applyExperienceUpdate = useCallback((updated: L2ExperienceReviewDetail) => {
    setExperiences((prev) => prev.map((item) => (
      item.experience_id === updated.experience_id
        ? { ...item, ...updated }
        : item
    )));
    setDetail((prev) => (
      prev && prev.experience_id === updated.experience_id
        ? { ...prev, ...updated }
        : prev
    ));
  }, []);

  const openExperience = (experienceId: string) => {
    setSelectedId(experienceId);
  };

  const renameSelectedExperience = async (title: string) => {
    if (!selectedExperience) {
      return;
    }
    const updated = await memoryApi.annotateExperience(selectedExperience.experience_id, {
      user_label: title,
    });
    applyExperienceUpdate({
      ...updated,
      display_title: updated.user_label || title,
    });
  };

  const editSelectedDescription = async (description: string) => {
    if (!selectedExperience) {
      return;
    }
    const updated = await memoryApi.annotateExperience(selectedExperience.experience_id, {
      user_note: description,
    });
    applyExperienceUpdate({
      ...updated,
      display_description: updated.user_note || description,
    });
  };

  const regenerateSelectedDescription = async () => {
    if (!selectedExperience) {
      return;
    }
    const updated = await memoryApi.regenerateExperienceReview(selectedExperience.experience_id);
    applyExperienceUpdate(updated);
  };

  const hideSelectedExperience = async () => {
    if (!selectedExperience) {
      return;
    }
    const hiddenId = selectedExperience.experience_id;
    await memoryApi.hideExperience(hiddenId);
    const nextItems = experiences.filter((item) => item.experience_id !== hiddenId);
    setExperiences(nextItems);
    setDetail(null);
    setSelectedId(sortExperiencesForReview(nextItems)[0]?.experience_id ?? null);
  };

  const reconsolidateEpisodes = async () => {
    setReconsolidating(true);
    try {
      const result = await memoryApi.reconsolidateEpisodes();
      setReconsolidateResult(result);
      await refresh();
    } finally {
      setReconsolidating(false);
    }
  };

  return (
    <MemoryPageFrame
      title={t('memory.episodes.title')}
      description={t('memory.episodes.subtitle')}
      hideHeader
      className="max-w-[1540px] gap-5 px-6 py-7"
      contentClassName="pb-8"
    >
      <header className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <h1 className="text-[2.55rem] font-semibold leading-tight tracking-normal text-[hsl(var(--memory-title))]">
            {t('memory.episodes.title')}
          </h1>
          <p className="mt-2 max-w-3xl text-base leading-7 text-[hsl(var(--memory-body))]">
            {t('memory.episodes.subtitle')}
          </p>
        </div>

        <div className="flex w-full flex-col gap-2 sm:flex-row lg:w-auto lg:items-center lg:justify-end">
          <label className="relative min-w-0 flex-1 lg:w-[340px] lg:flex-none">
            <span className="sr-only">{t('memory.episodes.searchLabel')}</span>
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[hsl(var(--memory-muted))]" aria-hidden="true" />
            <Input
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder={t('memory.episodes.searchPlaceholder')}
              className="h-10 rounded-lg border-[hsl(var(--memory-input-border)/0.74)] bg-[hsl(var(--memory-panel-elevated)/0.88)] pl-9 text-sm shadow-sm focus-visible:ring-[hsl(var(--memory-accent)/0.18)]"
            />
          </label>
          <Button
            type="button"
            variant={pinnedOnly ? 'secondary' : 'outline'}
            onClick={() => setPinnedOnly((value) => !value)}
            aria-pressed={pinnedOnly}
            className="h-10 rounded-lg border-[hsl(var(--memory-input-border)/0.72)] px-4"
          >
            <Filter className="h-4 w-4" aria-hidden="true" />
            {pinnedOnly ? t('memory.episodes.filterPinnedActive') : t('memory.episodes.filterPinned')}
          </Button>
          <Button
            type="button"
            onClick={reconsolidateEpisodes}
            disabled={reconsolidating}
            className="h-10 rounded-lg bg-[#3f8184] px-4 text-white hover:bg-[#356f72]"
          >
            <Sparkles className="h-4 w-4" aria-hidden="true" />
            {reconsolidating
              ? t('memory.episodes.actions.reconsolidating')
              : t('memory.episodes.actions.reconsolidate')}
          </Button>
        </div>
      </header>

      {reconsolidateResult ? (
        <div className="text-right text-xs text-[hsl(var(--memory-muted))]">
          {t('memory.episodes.reconsolidateResult', {
            promoted: reconsolidateResult.promoted,
            standouts: reconsolidateResult.standouts,
            summaries: reconsolidateResult.summaries_generated,
          })}
        </div>
      ) : null}

      {loading ? (
        <div className={MEMORY_INFO_PANEL_CLASS}>{t('common.loading')}</div>
      ) : experiences.length === 0 ? (
        <div className={MEMORY_EMPTY_PANEL_CLASS}>
          <div className="font-semibold text-[hsl(var(--memory-title))]">{t('memory.episodes.emptyTitle')}</div>
          <p className="mt-1 text-sm">{t('memory.episodes.emptyBody')}</p>
        </div>
      ) : (
        <div className="grid min-h-0 gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(360px,500px)]">
          <main className="min-w-0 space-y-6">
            {featuredExperience ? (
              <FeaturedExperienceCard
                experience={featuredExperience}
                selected={featuredExperience.experience_id === selectedId}
                onOpen={() => openExperience(featuredExperience.experience_id)}
              />
            ) : null}

            <section className="min-w-0 space-y-4">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                <div className="min-w-0">
                  <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">
                    {t('memory.episodes.sections.all')}
                  </h2>
                  <p className="mt-1 text-xs text-[hsl(var(--memory-muted))]">
                    {t('memory.episodes.sortNote')}
                  </p>
                </div>
                <Badge variant="outline" className="w-fit rounded-full border-[hsl(var(--memory-tag-border))] bg-[hsl(var(--memory-tag-bg)/0.78)] text-[hsl(var(--memory-muted))]">
                  {t('memory.episodes.count', { count: filteredExperiences.length })}
                </Badge>
              </div>

              {filteredExperiences.length === 0 ? (
                <div className={MEMORY_EMPTY_PANEL_CLASS}>{t('memory.episodes.noSearchResults')}</div>
              ) : (
                <ExperienceTimeline
                  groups={groupedExperiences}
                  selectedId={selectedId}
                  onSelect={openExperience}
                />
              )}
            </section>
          </main>

          <aside className="min-w-0 xl:sticky xl:top-0 xl:self-start">
            {selectedExperience ? (
              <ExperienceDetail
                experience={selectedExperience}
                title={selectedTitle}
                detailLoading={detailLoading}
                onRenameTitle={renameSelectedExperience}
                onEditDescription={editSelectedDescription}
                onRegenerate={regenerateSelectedDescription}
                onHide={hideSelectedExperience}
                variant="inline"
              />
            ) : (
              <div className={MEMORY_INFO_PANEL_CLASS}>
                {t('memory.episodes.detailEmptyBody')}
              </div>
            )}
          </aside>
        </div>
      )}
    </MemoryPageFrame>
  );
};

function FeaturedExperienceCard({
  experience,
  selected,
  onOpen,
}: {
  experience: L2ExperienceWithReview;
  selected: boolean;
  onOpen: () => void;
}) {
  const { t, i18n } = useTranslation('app');
  const title = getExperienceDisplayTitle(experience, t('memory.episodes.awaitingLabel'));
  const description = getExperienceDescription(experience) || t('memory.episodes.noRecap');
  const range = formatEpisodeTimeRange(experience.time_start, experience.time_end, i18n.language);
  const tags = getExperienceTags(experience, 7);

  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label={`${t('memory.episodes.featuredLabel')}: ${title}`}
      className={cn(
        'group w-full overflow-hidden rounded-lg border bg-[hsl(var(--memory-panel-elevated)/0.82)] px-6 py-6 text-left shadow-sm transition-colors duration-200',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--memory-accent)/0.24)]',
        selected
          ? 'border-[hsl(var(--memory-accent)/0.44)]'
          : 'border-[hsl(var(--memory-border)/0.58)] hover:border-[hsl(var(--memory-accent)/0.28)]'
      )}
    >
      <div className="flex min-h-[260px] flex-col justify-between">
        <div className="min-w-0">
          <div className="inline-flex items-center gap-2 rounded-full bg-[hsl(var(--memory-accent-soft)/0.62)] px-3 py-1 text-xs font-medium text-[hsl(var(--memory-title))]">
            <Star className="h-4 w-4 fill-current text-[hsl(var(--memory-accent))]" aria-hidden="true" />
            {t('memory.episodes.featuredLabel')}
          </div>
          <h2 className="mt-5 break-words text-[1.6rem] font-semibold leading-tight tracking-normal text-[hsl(var(--memory-title))] sm:text-[1.9rem]">
            {title}
          </h2>
          <p className="mt-4 line-clamp-4 whitespace-pre-wrap text-base leading-7 text-[hsl(var(--memory-body))]">
            {description}
          </p>
        </div>

        <div className="mt-7 space-y-4 border-t border-[hsl(var(--memory-divider)/0.62)] pt-4">
          {tags.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {tags.map((tag) => (
                <span key={tag} className="rounded-md bg-[hsl(var(--memory-panel-subtle)/0.84)] px-3 py-1 text-xs text-[hsl(var(--memory-body))]">
                  {tag}
                </span>
              ))}
            </div>
          ) : null}
          <div className="flex flex-wrap items-center gap-4 text-sm text-[hsl(var(--memory-muted))]">
            {range ? (
              <span className="inline-flex items-center gap-2">
                <CalendarRange className="h-4 w-4" aria-hidden="true" />
                {range}
              </span>
            ) : null}
            <span className="inline-flex items-center gap-2">
              <Layers className="h-4 w-4" aria-hidden="true" />
              {t('memory.episodes.episodeCount', { count: experience.source_episode_count ?? 0 })}
            </span>
          </div>
        </div>
      </div>
    </button>
  );
}

function ExperienceTimeline({
  groups,
  selectedId,
  onSelect,
}: {
  groups: Array<{ key: string; label: string; items: L2ExperienceWithReview[] }>;
  selectedId: string | null;
  onSelect: (experienceId: string) => void;
}) {
  return (
    <div className="space-y-6">
      {groups.map((group) => (
        <section key={group.key} className="grid gap-3 md:grid-cols-[86px_minmax(0,1fr)]">
          <div className="relative text-sm font-semibold text-[hsl(var(--memory-title))]">
            <span className="md:sticky md:top-4">{group.label}</span>
          </div>
          <div className="relative space-y-3 border-l border-[hsl(var(--memory-divider)/0.78)] pl-5">
            {group.items.map((experience) => (
              <TimelineExperienceItem
                key={experience.experience_id}
                experience={experience}
                selected={experience.experience_id === selectedId}
                onSelect={() => onSelect(experience.experience_id)}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function TimelineExperienceItem({
  experience,
  selected,
  onSelect,
}: {
  experience: L2ExperienceWithReview;
  selected: boolean;
  onSelect: () => void;
}) {
  const { t, i18n } = useTranslation('app');
  const title = getExperienceDisplayTitle(experience, t('memory.episodes.awaitingLabel'));
  const range = formatEpisodeTimeRange(experience.time_start, experience.time_end, i18n.language);
  const tags = getExperienceTags(experience, 3);

  return (
    <button
      type="button"
      onClick={onSelect}
      aria-label={`${t('memory.episodes.actions.open')}: ${title}`}
      className={cn(
        'relative flex w-full flex-col gap-3 rounded-lg border px-5 py-4 text-left transition-colors duration-200 sm:flex-row sm:items-start sm:justify-between',
        'before:absolute before:-left-[28px] before:top-6 before:h-3 before:w-3 before:rounded-full before:border before:border-[hsl(var(--memory-divider))] before:bg-[hsl(var(--memory-panel-elevated))]',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--memory-accent)/0.24)]',
        selected
          ? 'border-[hsl(var(--memory-accent)/0.42)] bg-[hsl(var(--memory-accent-soft)/0.48)] before:border-[hsl(var(--memory-accent))]'
          : 'border-[hsl(var(--memory-border)/0.54)] bg-[hsl(var(--memory-panel-elevated)/0.72)] hover:border-[hsl(var(--memory-accent)/0.28)] hover:bg-[hsl(var(--memory-panel-elevated)/0.9)]'
      )}
    >
      <div className="min-w-0">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <BookOpen className="h-4 w-4 shrink-0 text-[hsl(var(--memory-accent))]" aria-hidden="true" />
          <h3 className="break-words text-base font-semibold leading-6 text-[hsl(var(--memory-title))]">
            {title}
          </h3>
        </div>
        {tags.length > 0 ? (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Tags className="h-3.5 w-3.5 text-[hsl(var(--memory-muted))]" aria-hidden="true" />
            {tags.map((tag) => (
              <span key={tag} className="rounded-md bg-[hsl(var(--memory-panel-subtle)/0.82)] px-2 py-1 text-xs text-[hsl(var(--memory-body))]">
                {tag}
              </span>
            ))}
          </div>
        ) : null}
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-3 text-xs text-[hsl(var(--memory-muted))] sm:justify-end">
        {range ? <span>{range}</span> : null}
        <span>{t('memory.episodes.eventCount', { count: experience.source_event_count ?? 0 })}</span>
      </div>
    </button>
  );
}

export default MemoryEpisodesPage;
