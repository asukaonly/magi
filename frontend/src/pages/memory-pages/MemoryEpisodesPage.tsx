import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';
import {
  ArrowLeft,
  BookOpen,
  CalendarRange,
  CheckCircle2,
  CircleSlash2,
  Layers,
  Loader2,
  Sparkles,
  Star,
  Tags,
} from 'lucide-react';
import {
  memoryApi,
  type L2ExperienceSeed,
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
  const [experienceSeeds, setExperienceSeeds] = useState<L2ExperienceSeed[]>([]);
  const [loading, setLoading] = useState(true);
  const [seedActionId, setSeedActionId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [experiencePayload, seedPayload] = await Promise.all([
        memoryApi.listExperiences({ status: 'active', limit: 100, offset: 0 }),
        memoryApi.listExperienceSeeds({ status: 'candidate', limit: 6, offset: 0 }),
      ]);
      setExperiences(experiencePayload.items);
      setExperienceSeeds(seedPayload.items);
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

  const promoteSeed = async (seedId: string) => {
    setSeedActionId(`${seedId}:promote`);
    try {
      await memoryApi.promoteExperienceSeed(seedId);
      await refresh();
    } finally {
      setSeedActionId(null);
    }
  };

  const rejectSeed = async (seedId: string) => {
    setSeedActionId(`${seedId}:reject`);
    try {
      await memoryApi.rejectExperienceSeed(seedId);
      setExperienceSeeds((items) => items.filter((item) => item.seed_id !== seedId));
    } finally {
      setSeedActionId(null);
    }
  };

  return (
    <MemoryPageFrame
      title={t('memory.episodes.title')}
      description={t('memory.episodes.subtitle')}
      hideHeader
      className="max-w-[1180px] gap-5 px-4 py-5"
      contentClassName="pb-8"
    >
      {loading ? (
        <div className={MEMORY_INFO_PANEL_CLASS}>{t('common.loading')}</div>
      ) : (
        <section className="min-w-0 space-y-7">
          {experienceSeeds.length > 0 ? (
            <PendingExperienceShelf
              seeds={experienceSeeds}
              actionId={seedActionId}
              onPromote={promoteSeed}
              onReject={rejectSeed}
            />
          ) : null}

          {experiences.length === 0 ? (
            <div className={MEMORY_EMPTY_PANEL_CLASS}>
              <div className="font-semibold text-[hsl(var(--memory-title))]">{t('memory.episodes.emptyTitle')}</div>
              <p className="mt-1 text-sm">{t('memory.episodes.emptyBody')}</p>
            </div>
          ) : (
            <div className="space-y-4">
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
            </div>
          )}
        </section>
      )}
    </MemoryPageFrame>
  );
};

const getSeedTags = (seed: L2ExperienceSeed, limit = 3): string[] => uniqueItems([
  ...(seed.display_tags || []).map(formatExperienceTag),
  ...normalizeTags(seed.anchor_entity_ids),
  ...normalizeTags(seed.anchor_place_ids),
  ...normalizeTags(seed.anchor_topic_keys),
]).slice(0, limit);

const getSeedTitle = (seed: L2ExperienceSeed, fallback: string): string => (
  String(seed.display_title || seed.title || '').trim() || fallback
);

const getSeedDescription = (
  seed: L2ExperienceSeed,
  tags: string[],
  fallback: string,
  genericFallback: string
): string => {
  const description = String(seed.display_description || seed.description || '').trim();
  if (description) {
    return description;
  }
  if (tags.length > 0) {
    return fallback.replace('{{tags}}', tags.join('、'));
  }
  return genericFallback;
};

function PendingExperienceShelf({
  seeds,
  actionId,
  onPromote,
  onReject,
}: {
  seeds: L2ExperienceSeed[];
  actionId: string | null;
  onPromote: (seedId: string) => Promise<void>;
  onReject: (seedId: string) => Promise<void>;
}) {
  const { t } = useTranslation('app');

  return (
    <section className="space-y-3">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">
            {t('memory.episodes.pending.title')}
          </h2>
          <p className="mt-1 text-xs text-[hsl(var(--memory-muted))]">
            {t('memory.episodes.pending.subtitle')}
          </p>
        </div>
        <Badge variant="outline" className="w-fit rounded-full border-[hsl(var(--memory-tag-border))] bg-[hsl(var(--memory-tag-bg)/0.78)] text-[hsl(var(--memory-muted))]">
          {t('memory.episodes.pending.count', { count: seeds.length })}
        </Badge>
      </div>
      <div className="grid gap-3 lg:grid-cols-3">
        {seeds.slice(0, 3).map((seed) => (
          <PendingExperienceCard
            key={seed.seed_id}
            seed={seed}
            actionId={actionId}
            onPromote={onPromote}
            onReject={onReject}
          />
        ))}
      </div>
    </section>
  );
}

function PendingExperienceCard({
  seed,
  actionId,
  onPromote,
  onReject,
}: {
  seed: L2ExperienceSeed;
  actionId: string | null;
  onPromote: (seedId: string) => Promise<void>;
  onReject: (seedId: string) => Promise<void>;
}) {
  const { t, i18n } = useTranslation('app');
  const tags = getSeedTags(seed, 3);
  const title = getSeedTitle(seed, t('memory.episodes.pending.fallbackTitle'));
  const description = getSeedDescription(
    seed,
    tags,
    t('memory.episodes.pending.fallbackDescription'),
    t('memory.episodes.pending.fallbackDescriptionGeneric')
  );
  const range = formatEpisodeTimeRange(seed.time_start, seed.time_end, i18n.language);
  const promoting = actionId === `${seed.seed_id}:promote`;
  const rejecting = actionId === `${seed.seed_id}:reject`;
  const busy = promoting || rejecting;

  return (
    <article className="flex min-h-[176px] flex-col justify-between rounded-lg border border-[hsl(var(--memory-border)/0.58)] bg-[hsl(var(--memory-panel-elevated)/0.82)] p-4 shadow-[0_10px_28px_hsl(var(--memory-shadow)/0.04)]">
      <div className="min-w-0">
        <div className="flex items-center gap-2 text-xs text-[hsl(var(--memory-muted))]">
          <Sparkles className="h-3.5 w-3.5 text-[hsl(var(--memory-accent))]" aria-hidden="true" />
          <span>{t('memory.episodes.pending.clearSignal')}</span>
        </div>
        <h3 className="mt-2 line-clamp-2 text-base font-semibold leading-6 text-[hsl(var(--memory-title))]">
          {title}
        </h3>
        <p className="mt-2 line-clamp-2 text-sm leading-6 text-[hsl(var(--memory-body))]">
          {description}
        </p>
      </div>

      <div className="mt-4 space-y-3">
        <div className="flex min-w-0 flex-wrap items-center gap-2 text-xs text-[hsl(var(--memory-muted))]">
          {range ? (
            <span className="inline-flex min-w-0 items-center gap-1">
              <CalendarRange className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              <span className="truncate">{range}</span>
            </span>
          ) : null}
          <span className="inline-flex items-center gap-1">
            <Layers className="h-3.5 w-3.5" aria-hidden="true" />
            {t('memory.episodes.pending.evidenceCount', { count: seed.evidence_count ?? 0 })}
          </span>
        </div>
        {tags.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {tags.map((tag) => (
              <span key={tag} className="rounded-md bg-[hsl(var(--memory-panel-subtle)/0.82)] px-2 py-1 text-xs text-[hsl(var(--memory-body))]">
                {tag}
              </span>
            ))}
          </div>
        ) : null}
        <div className="flex flex-wrap gap-2 pt-1">
          <Button
            type="button"
            size="sm"
            className="h-8 rounded-lg bg-[hsl(var(--memory-accent))] px-3 text-xs text-[hsl(var(--memory-accent-foreground))] hover:bg-[hsl(var(--memory-accent)/0.9)]"
            disabled={busy}
            onClick={() => { void onPromote(seed.seed_id); }}
          >
            {promoting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
            )}
            {t('memory.episodes.pending.actions.promote')}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8 rounded-lg px-3 text-xs"
            disabled={busy}
            onClick={() => { void onReject(seed.seed_id); }}
          >
            {rejecting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <CircleSlash2 className="h-3.5 w-3.5" aria-hidden="true" />
            )}
            {t('memory.episodes.pending.actions.reject')}
          </Button>
        </div>
      </div>
    </article>
  );
}

function ExperienceTimeline({
  groups,
  onSelect,
}: {
  groups: Array<{ key: string; label: string; items: L2ExperienceWithReview[] }>;
  onSelect: (experienceId: string) => void;
}) {
  const { t } = useTranslation('app');

  return (
    <div className="space-y-7">
      {groups.map((group) => (
        <section key={group.key} className="space-y-3">
          <div className="flex items-baseline justify-between border-b border-[hsl(var(--memory-divider)/0.56)] pb-2">
            <h3 className="text-base font-semibold text-[hsl(var(--memory-title))]">{group.label}</h3>
            <span className="text-xs text-[hsl(var(--memory-muted))]">
              {t('memory.episodes.count', { count: group.items.length })}
            </span>
          </div>
          <div className="space-y-3">
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
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--memory-accent)/0.24)]',
        'border-[hsl(var(--memory-border)/0.54)] bg-[hsl(var(--memory-panel-elevated)/0.72)] hover:border-[hsl(var(--memory-accent)/0.28)] hover:bg-[hsl(var(--memory-panel-elevated)/0.9)]'
      )}
    >
      <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <BookOpen className="h-4 w-4 shrink-0 text-[hsl(var(--memory-accent))]" aria-hidden="true" />
            {experience.user_pinned ? (
              <span className="inline-flex items-center gap-1 rounded-md bg-[hsl(var(--memory-accent-soft)/0.7)] px-2 py-0.5 text-xs text-[hsl(var(--memory-title))]">
                <Star className="h-3.5 w-3.5" aria-hidden="true" />
                {t('memory.episodes.sections.featured')}
              </span>
            ) : null}
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

  const changeCover = async (file: File) => {
    if (!experience) {
      return;
    }
    const updated = await memoryApi.uploadExperienceCover(experience.experience_id, file);
    applyExperienceUpdate(updated);
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
  const backButton = (
    <Button
      type="button"
      variant="ghost"
      className="-ml-2 h-8 rounded-md px-2 text-xs font-medium text-[hsl(var(--memory-muted))] hover:bg-[hsl(var(--memory-panel-subtle)/0.82)] hover:text-[hsl(var(--memory-title))]"
      onClick={() => navigate('/memory/episodes')}
    >
      <ArrowLeft className="h-4 w-4" aria-hidden="true" />
      {t('memory.episodes.actions.backToList')}
    </Button>
  );

  return (
    <MemoryPageFrame
      title={title || t('memory.episodes.title')}
      description={t('memory.episodes.subtitle')}
      hideHeader
      className="max-w-[1180px] gap-3 px-4 pb-5 pt-3"
      contentClassName="pb-8"
    >
      {loading ? (
        <>
          <div>{backButton}</div>
          <div className={MEMORY_INFO_PANEL_CLASS}>{t('common.loading')}</div>
        </>
      ) : notFound || !experience ? (
        <>
          <div>{backButton}</div>
          <div className={MEMORY_EMPTY_PANEL_CLASS}>{t('memory.episodes.detailNotFound')}</div>
        </>
      ) : (
        <ExperienceDetail
          experience={experience}
          title={title}
          detailLoading={false}
          onRenameTitle={renameExperience}
          onEditDescription={editDescription}
          onChangeCover={changeCover}
          onRegenerate={regenerateDescription}
          onHide={hideExperience}
          toolbarStart={backButton}
          variant="sheet"
        />
      )}
    </MemoryPageFrame>
  );
};

export default MemoryEpisodesPage;
