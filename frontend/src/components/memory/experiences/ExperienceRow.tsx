import { BookOpen, CalendarRange, Layers, Pin, Tags } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { L2Experience, L2ExperienceWithReview } from '@/api/modules/memory';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { formatEpisodeTimeRange } from '../episodes/EpisodeRow';

interface ExperienceRowProps {
  experience: L2ExperienceWithReview;
  selected: boolean;
  onOpen: () => void;
}

type ExperienceReviewLike = L2Experience | L2ExperienceWithReview;

const MACHINE_ID_PATTERN = /^[0-9a-f]{10,}$|^[0-9A-HJKMNP-TV-Z]{12,}$/i;

export const formatExperienceTag = (value: string): string => {
  const raw = String(value || '').trim();
  if (!raw || raw === 'user' || raw === 'user:local_user' || raw === 'local_user') {
    return '';
  }
  const [, suffix = raw] = raw.match(/^[^:]+:(.+)$/) || [];
  const cleaned = suffix.trim();
  if (!cleaned || MACHINE_ID_PATTERN.test(cleaned)) {
    return '';
  }
  return cleaned.replace(/[-_]+/g, ' ');
};

export const getExperienceDisplayTitle = (experience: ExperienceReviewLike, fallback: string): string => {
  const values = [
    experience.user_label,
    (experience as L2ExperienceWithReview).display_title,
    (experience as L2ExperienceWithReview).experience_review?.label,
    experience.title,
    experience.intent,
    experience.magi_interpretation,
    experience.experience_id,
  ];
  return values.find((value) => typeof value === 'string' && value.trim())?.trim() ?? fallback;
};

export const getExperienceDescription = (experience: ExperienceReviewLike): string => (
  String(
    experience.user_note ||
    (experience as L2ExperienceWithReview).display_description ||
    (experience as L2ExperienceWithReview).experience_review?.content ||
    experience.magi_interpretation ||
    experience.outcome ||
    experience.intent ||
    ''
  ).trim()
);

const getExperienceSummary = (experience: ExperienceReviewLike): string => {
  const summary = getExperienceDescription(experience);
  return summary.length > 180 ? `${summary.slice(0, 177)}...` : summary;
};

export const getExperienceEntityLabels = (experience: ExperienceReviewLike): string[] => {
  const entities = Array.isArray(experience.primary_entities) ? experience.primary_entities : [];
  const names = entities
    .map((entity) => String(entity.name || '').trim())
    .filter(Boolean);
  if (names.length > 0) {
    return names.slice(0, 3);
  }
  return (experience.primary_entity_ids || [])
    .map(formatExperienceTag)
    .filter(Boolean)
    .slice(0, 3);
};

export function ExperienceRow({ experience, selected, onOpen }: ExperienceRowProps) {
  const { t, i18n } = useTranslation('app');
  const title = getExperienceDisplayTitle(experience, t('memory.episodes.awaitingLabel'));
  const summary = getExperienceSummary(experience);
  const range = formatEpisodeTimeRange(experience.time_start, experience.time_end, i18n.language);
  const entityLabels = getExperienceEntityLabels(experience);
  const typeLabel = t(`memory.episodes.filters.${experience.experience_type || 'activity'}`, {
    defaultValue: experience.experience_type || '',
  });

  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label={`${t('memory.episodes.actions.open')}: ${title}`}
      className={cn(
        'group relative flex min-h-[264px] w-full overflow-hidden rounded-lg border px-5 py-5 text-left transition-colors duration-200',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--memory-accent)/0.24)]',
        selected
          ? 'border-[hsl(var(--memory-accent)/0.46)] bg-[hsl(var(--memory-accent-soft)/0.64)]'
          : 'border-[hsl(var(--memory-border)/0.54)] bg-[hsl(var(--memory-panel-elevated)/0.72)] hover:border-[hsl(var(--memory-accent)/0.26)] hover:bg-[hsl(var(--memory-panel-elevated)/0.9)]'
      )}
    >
      <span
        className={cn(
          'absolute inset-y-0 left-0 w-1',
          selected ? 'bg-[hsl(var(--memory-accent))]' : 'bg-[hsl(var(--memory-accent)/0.34)]'
        )}
        aria-hidden="true"
      />
      <div className="flex min-w-0 flex-1 flex-col justify-between pl-1">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 text-xs text-[hsl(var(--memory-muted))]">
            <BookOpen className="h-4 w-4 shrink-0 text-[hsl(var(--memory-accent))]" aria-hidden="true" />
            {typeLabel ? <span>{typeLabel}</span> : null}
            {experience.user_pinned ? (
              <span className="inline-flex items-center gap-1 rounded-md bg-[hsl(var(--memory-accent-soft)/0.62)] px-2 py-0.5 text-[hsl(var(--memory-title))]">
                <Pin className="h-3.5 w-3.5" aria-hidden="true" />
                {t('memory.episodes.fields.pinned')}
              </span>
            ) : null}
          </div>
          <h3 className="mt-3 break-words text-lg font-semibold leading-7 text-[hsl(var(--memory-title))]">
            {title}
          </h3>
          <p className="mt-4 line-clamp-5 whitespace-pre-wrap text-[0.95rem] leading-7 text-[hsl(var(--memory-body))]">
            {summary || t('memory.episodes.noRecap')}
          </p>
        </div>
        <div className="mt-6 space-y-3 border-t border-[hsl(var(--memory-divider)/0.62)] pt-4">
          {entityLabels.length > 0 ? (
            <div className="flex flex-wrap items-center gap-2">
              <Tags className="h-3.5 w-3.5 text-[hsl(var(--memory-muted))]" aria-hidden="true" />
              {entityLabels.map((label) => (
                <span
                  key={label}
                  className="rounded-md bg-[hsl(var(--memory-panel-subtle)/0.76)] px-2 py-1 text-xs text-[hsl(var(--memory-body))]"
                >
                  {label}
                </span>
              ))}
            </div>
          ) : null}
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-[hsl(var(--memory-muted))]">
            <div className="flex min-w-0 flex-wrap items-center gap-3">
              {range ? (
                <span className="inline-flex min-w-0 items-center gap-1">
                  <CalendarRange className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                  <span className="truncate">{range}</span>
                </span>
              ) : null}
              <span className="inline-flex items-center gap-1 tabular-nums">
                <Layers className="h-3.5 w-3.5" aria-hidden="true" />
                {t('memory.episodes.episodeCount', { count: experience.source_episode_count ?? 0 })}
              </span>
            </div>
            <Badge variant="outline" className="shrink-0 rounded-md border-[hsl(var(--memory-tag-border))] bg-[hsl(var(--memory-tag-bg)/0.74)] font-normal text-[hsl(var(--memory-body))]">
              {t('memory.episodes.eventCount', { count: experience.source_event_count ?? 0 })}
            </Badge>
          </div>
        </div>
      </div>
    </button>
  );
}

export default ExperienceRow;
