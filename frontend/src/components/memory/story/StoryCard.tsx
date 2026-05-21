import { useTranslation } from 'react-i18next';
import { Archive, ChevronRight } from 'lucide-react';
import type { StoryItem, StoryReviewState } from '@/api/modules/memoryStories';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

interface StoryCardProps {
  story: StoryItem;
  onArchive: () => void;
  onOpenDetail: () => void;
}

const stateToneClass = (state: StoryReviewState): string => {
  switch (state) {
    case 'pending_confirmation':
      return 'border-[hsl(var(--memory-accent)/0.4)] bg-[hsl(var(--memory-accent-soft)/0.5)]';
    case 'rejected':
    case 'archived':
      return 'opacity-60 border-[hsl(var(--memory-border)/0.35)] bg-[hsl(var(--memory-panel-elevated)/0.5)]';
    case 'confirmed':
      return 'border-[hsl(var(--memory-border)/0.55)] bg-[hsl(var(--memory-panel-elevated)/0.78)]';
    default:
      return 'border-[hsl(var(--memory-border)/0.55)] bg-[hsl(var(--memory-panel-elevated)/0.7)]';
  }
};

const formatPeriod = (start: number | null, end: number | null, locale: string): string => {
  const ts = end ?? start;
  if (!ts) return '';
  return new Date(ts * 1000).toLocaleDateString(locale);
};

const formatProvenance = (ts: number | null | undefined, locale: string): string => {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleString(locale, {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
};

export const StoryCard = ({ story, onArchive, onOpenDetail }: StoryCardProps) => {
  const { t, i18n } = useTranslation('app');
  const categoryLabel = t(`memory.stories.categories.${story.summary_category}`, { defaultValue: story.summary_category });
  const stateLabel = t(`memory.stories.states.${story.review_state}`, { defaultValue: '' });
  const period = formatPeriod(story.period_start, story.period_end, i18n.language);

  return (
    <article
      data-testid={`story-card-${story.summary_id}`}
      className={cn('rounded-2xl border px-5 py-4 transition-colors', stateToneClass(story.review_state))}
    >
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <div className="flex items-center gap-2">
            <span className="rounded-sm bg-[hsl(var(--memory-panel-subtle)/0.7)] px-2 py-0.5 text-xs text-[hsl(var(--memory-muted))]">
              {categoryLabel}
            </span>
            {stateLabel ? (
              <span className="text-xs font-medium text-[hsl(var(--memory-accent))]">{stateLabel}</span>
            ) : null}
            {period ? <span className="text-xs text-[hsl(var(--memory-muted))]">{period}</span> : null}
          </div>
          {story.title ? (
            <button
              type="button"
              onClick={onOpenDetail}
              className="text-left text-base font-semibold leading-6 text-[hsl(var(--memory-title))] hover:underline"
            >
              {story.title}
            </button>
          ) : null}
        </div>
        <Button variant="ghost" size="sm" onClick={onOpenDetail} aria-label={t('memory.stories.actions.viewEvidence')}>
          <ChevronRight className="h-4 w-4" />
        </Button>
      </header>

      <p className="mt-2 text-sm leading-6 text-[hsl(var(--memory-body))]">
        {story.content}
      </p>

      <footer className="mt-3 space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          {story.summary_type === 'insight' ? (
            <span className="text-xs text-[hsl(var(--memory-muted))]">
              {t('memory.stories.evidenceChip', { count: story.evidence_event_count })}
            </span>
          ) : <span />}
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="sm" onClick={onArchive} aria-label={t('memory.stories.actions.archive')}>
              <Archive className="h-4 w-4" />
            </Button>
          </div>
        </div>
        <div className="text-[10px] text-[hsl(var(--memory-muted)/0.8)]">
          {t('memory.stories.provenance', { timestamp: formatProvenance(story.updated_at, i18n.language) })}
        </div>
      </footer>
    </article>
  );
};

export default StoryCard;
