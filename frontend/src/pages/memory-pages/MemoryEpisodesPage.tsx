import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';
import {
  ArrowLeft,
  BookOpen,
  Layers,
  Tags,
} from 'lucide-react';
import {
  memoryApi,
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
  const navigate = useNavigate();
  const [experiences, setExperiences] = useState<L2ExperienceWithReview[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await memoryApi.listExperiences({ status: 'active', limit: 100, offset: 0 });
      setExperiences(payload.items);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const sortedExperiences = useMemo(() => sortExperiencesForReview(experiences), [experiences]);
  const groupedExperiences = useMemo(
    () => groupExperiencesByMonth(sortedExperiences, i18n.language, t('memory.episodes.unknownMonth')),
    [sortedExperiences, i18n.language, t]
  );

  const openExperience = (experienceId: string) => {
    navigate(`/memory/episodes/${experienceId}`);
  };

  return (
    <MemoryPageFrame
      title={t('memory.episodes.title')}
      description={t('memory.episodes.subtitle')}
      hideHeader
      className="max-w-[1180px] gap-6 px-6 py-7"
      contentClassName="pb-8"
    >
      <header className="max-w-3xl">
        <div className="min-w-0">
          <h1 className="text-3xl font-semibold leading-tight tracking-normal text-[hsl(var(--memory-title))]">
            {t('memory.episodes.title')}
          </h1>
          <p className="mt-2 text-sm leading-6 text-[hsl(var(--memory-body))]">
            {t('memory.episodes.subtitle')}
          </p>
        </div>
      </header>

      {loading ? (
        <div className={MEMORY_INFO_PANEL_CLASS}>{t('common.loading')}</div>
      ) : experiences.length === 0 ? (
        <div className={MEMORY_EMPTY_PANEL_CLASS}>
          <div className="font-semibold text-[hsl(var(--memory-title))]">{t('memory.episodes.emptyTitle')}</div>
          <p className="mt-1 text-sm">{t('memory.episodes.emptyBody')}</p>
        </div>
      ) : (
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
              {t('memory.episodes.count', { count: sortedExperiences.length })}
            </Badge>
          </div>

          <ExperienceTimeline
            groups={groupedExperiences}
            onSelect={openExperience}
          />
        </section>
      )}
    </MemoryPageFrame>
  );
};

function ExperienceTimeline({
  groups,
  onSelect,
}: {
  groups: Array<{ key: string; label: string; items: L2ExperienceWithReview[] }>;
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
  onSelect,
}: {
  experience: L2ExperienceWithReview;
  onSelect: () => void;
}) {
  const { t, i18n } = useTranslation('app');
  const title = getExperienceDisplayTitle(experience, t('memory.episodes.awaitingLabel'), i18n.language);
  const description = getExperienceDescription(experience);
  const range = formatEpisodeTimeRange(experience.time_start, experience.time_end, i18n.language);
  const tags = getExperienceTags(experience, 3);

  return (
    <button
      type="button"
      onClick={onSelect}
      aria-label={`${t('memory.episodes.actions.open')}: ${title}`}
      className={cn(
        'relative flex w-full flex-col gap-3 rounded-lg border px-5 py-4 text-left transition-colors duration-200',
        'before:absolute before:-left-[28px] before:top-6 before:h-3 before:w-3 before:rounded-full before:border before:border-[hsl(var(--memory-divider))] before:bg-[hsl(var(--memory-panel-elevated))]',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--memory-accent)/0.24)]',
        'border-[hsl(var(--memory-border)/0.54)] bg-[hsl(var(--memory-panel-elevated)/0.72)] hover:border-[hsl(var(--memory-accent)/0.28)] hover:bg-[hsl(var(--memory-panel-elevated)/0.9)]'
      )}
    >
      <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <BookOpen className="h-4 w-4 shrink-0 text-[hsl(var(--memory-accent))]" aria-hidden="true" />
            <h3 className="break-words text-base font-semibold leading-6 text-[hsl(var(--memory-title))]">
              {title}
            </h3>
          </div>
          {description ? (
            <p className="mt-2 line-clamp-2 max-w-3xl whitespace-pre-wrap text-sm leading-6 text-[hsl(var(--memory-body))]">
              {description}
            </p>
          ) : null}
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-3 text-xs text-[hsl(var(--memory-muted))] sm:justify-end">
          {range ? <span>{range}</span> : null}
          <span>{t('memory.episodes.eventCount', { count: experience.source_event_count ?? 0 })}</span>
        </div>
      </div>
      <div className="flex min-w-0 flex-wrap items-center gap-3">
        {tags.length > 0 ? (
          <div className="flex flex-wrap items-center gap-2">
            <Tags className="h-3.5 w-3.5 text-[hsl(var(--memory-muted))]" aria-hidden="true" />
            {tags.map((tag) => (
              <span key={tag} className="rounded-md bg-[hsl(var(--memory-panel-subtle)/0.82)] px-2 py-1 text-xs text-[hsl(var(--memory-body))]">
                {tag}
              </span>
            ))}
          </div>
        ) : null}
        <span className="inline-flex items-center gap-1 text-xs text-[hsl(var(--memory-muted))]">
          <Layers className="h-3.5 w-3.5" aria-hidden="true" />
          {t('memory.episodes.episodeCount', { count: experience.source_episode_count ?? 0 })}
        </span>
      </div>
    </button>
  );
}

export const MemoryExperienceDetailPage = () => {
  const { t, i18n } = useTranslation('app');
  const { experienceId } = useParams<{ experienceId: string }>();
  const navigate = useNavigate();
  const [experience, setExperience] = useState<L2ExperienceReviewDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  const loadExperience = useCallback(async () => {
    if (!experienceId) {
      setExperience(null);
      setNotFound(true);
      setLoading(false);
      return;
    }
    setLoading(true);
    setNotFound(false);
    try {
      const payload = await memoryApi.getExperience(experienceId);
      setExperience(payload);
    } catch {
      setExperience(null);
      setNotFound(true);
    } finally {
      setLoading(false);
    }
  }, [experienceId]);

  useEffect(() => {
    void loadExperience();
  }, [loadExperience]);

  const applyExperienceUpdate = useCallback((updated: L2ExperienceReviewDetail) => {
    setExperience((current) => (
      current && current.experience_id === updated.experience_id
        ? { ...current, ...updated }
        : updated
    ));
  }, []);

  const renameExperience = async (title: string) => {
    if (!experience) {
      return;
    }
    const updated = await memoryApi.annotateExperience(experience.experience_id, {
      user_label: title,
    });
    applyExperienceUpdate({
      ...updated,
      display_title: updated.user_label || title,
    });
  };

  const editDescription = async (description: string) => {
    if (!experience) {
      return;
    }
    const updated = await memoryApi.annotateExperience(experience.experience_id, {
      user_note: description,
    });
    applyExperienceUpdate({
      ...updated,
      display_description: updated.user_note || description,
    });
  };

  const regenerateDescription = async () => {
    if (!experience) {
      return;
    }
    const updated = await memoryApi.regenerateExperienceReview(experience.experience_id);
    applyExperienceUpdate(updated);
  };

  const hideExperience = async () => {
    if (!experience) {
      return;
    }
    await memoryApi.hideExperience(experience.experience_id);
    navigate('/memory/episodes');
  };

  const title = experience
    ? getExperienceDisplayTitle(experience, t('memory.episodes.awaitingLabel'), i18n.language)
    : '';

  return (
    <MemoryPageFrame
      title={title || t('memory.episodes.title')}
      description={t('memory.episodes.subtitle')}
      hideHeader
      className="max-w-[1180px] gap-5 px-6 py-7"
      contentClassName="pb-8"
    >
      <div>
        <Button
          type="button"
          variant="ghost"
          className="-ml-2 h-9 rounded-lg px-2 text-[hsl(var(--memory-muted))] hover:text-[hsl(var(--memory-title))]"
          onClick={() => navigate('/memory/episodes')}
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          {t('memory.episodes.actions.backToList')}
        </Button>
      </div>

      {loading ? (
        <div className={MEMORY_INFO_PANEL_CLASS}>{t('common.loading')}</div>
      ) : notFound || !experience ? (
        <div className={MEMORY_EMPTY_PANEL_CLASS}>{t('memory.episodes.detailNotFound')}</div>
      ) : (
        <ExperienceDetail
          experience={experience}
          title={title}
          detailLoading={false}
          onRenameTitle={renameExperience}
          onEditDescription={editDescription}
          onRegenerate={regenerateDescription}
          onHide={hideExperience}
          variant="sheet"
        />
      )}
    </MemoryPageFrame>
  );
};

export default MemoryEpisodesPage;
