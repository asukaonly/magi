import { useTranslation } from 'react-i18next';
import {
  BookOpen,
  Layers,
  Star,
  Tags,
} from 'lucide-react';
import type { L2ExperienceWithReview } from '@/api/modules/memory';
import {
  getExperienceDescription,
  getExperienceDisplayTitle,
} from '@/components/memory/experiences/ExperienceRow';
import { formatMemoryTimeRange } from '@/utils/memory-time';
import { cn } from '@/lib/utils';
import { getExperienceTags, type ExperienceMonthGroup } from './experienceIndexModel';

export function ExperienceTimeline({
  groups,
  onSelect,
}: {
  groups: ExperienceMonthGroup[];
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
  const range = formatMemoryTimeRange(experience.time_start, experience.time_end, i18n.language);
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
