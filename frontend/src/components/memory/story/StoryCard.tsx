import { useTranslation } from 'react-i18next';
import { Archive, ChevronRight } from 'lucide-react';
import type { StoryItem, StoryReviewState } from '@/api/modules/memoryStories';
import { Button } from '@/components/ui/button';
import { MarkdownBlock } from '@/components/ui/markdown-block';
import { cn } from '@/lib/utils';

interface StoryCardProps {
  story: StoryItem;
  onArchive: () => void;
  onOpenDetail: () => void;
}

const stateToneClass = (state: StoryReviewState): string => {
  switch (state) {
    case 'rejected':
    case 'archived':
      return 'opacity-60';
    default:
      return '';
  }
};

const categoryToneClass = (category: string): string => {
  switch (category) {
    case 'trend_shift':
    case 'preference_emergence':
      return 'bg-emerald-50 text-emerald-700 border-emerald-100';
    case 'day':
    case 'week':
    case 'month':
    case 'quarter':
    case 'year':
      return 'bg-sky-50 text-sky-700 border-sky-100';
    case 'task_reflection':
    case 'goal_refinement':
    case 'milestone_review':
      return 'bg-amber-50 text-amber-700 border-amber-100';
    case 'conflict_resolution':
    case 'risk_escalation':
      return 'bg-rose-50 text-rose-700 border-rose-100';
    default:
      return 'bg-[hsl(var(--memory-panel-subtle)/0.76)] text-[hsl(var(--memory-body))] border-[hsl(var(--memory-border)/0.35)]';
  }
};

const storyTimestamp = (story: StoryItem): number | null => (
  story.period_end || story.updated_at || story.period_start || null
);

const formatStoryDate = (story: StoryItem, locale: string): string => {
  const timestamp = storyTimestamp(story);
  if (!timestamp) return '';
  return new Intl.DateTimeFormat(locale, {
    month: 'numeric',
    day: 'numeric',
  }).format(new Date(timestamp * 1000));
};

export const StoryCard = ({ story, onArchive, onOpenDetail }: StoryCardProps) => {
  const { t, i18n } = useTranslation('app');
  const categoryLabel = t(`memory.stories.categories.${story.summary_category}`, { defaultValue: story.summary_category });
  const primaryText = story.title || story.content;
  const secondaryText = story.title ? story.content : '';
  const dateLabel = formatStoryDate(story, i18n.language);
  const evidenceLabel = story.evidence_event_count > 0
    ? t('memory.stories.evidenceChip', { count: story.evidence_event_count })
    : null;
  const sourceLabel = story.summary_type === 'insight'
    ? t('memory.stories.meta.insight')
    : t('memory.stories.meta.periodic');

  return (
    <article
      data-testid={`story-card-${story.summary_id}`}
      className={cn(
        'group grid gap-4 border-b border-[hsl(var(--memory-divider)/0.58)] px-5 py-5 transition-colors last:border-b-0 hover:bg-[hsl(var(--memory-panel-subtle)/0.28)] md:grid-cols-[150px_minmax(0,1fr)_76px]',
        stateToneClass(story.review_state)
      )}
    >
      <div className="flex flex-row items-center gap-3 md:flex-col md:items-start md:gap-2">
        <span className={cn('inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium', categoryToneClass(story.summary_category))}>
          {categoryLabel}
        </span>
        {dateLabel ? <span className="text-xs font-medium text-[hsl(var(--memory-muted))]">{dateLabel}</span> : null}
      </div>

      <div className="min-w-0">
        {story.title ? (
          <button
            type="button"
            onClick={onOpenDetail}
            className="block text-left text-base font-semibold leading-7 text-[hsl(var(--memory-title))] transition-colors hover:text-[hsl(var(--memory-accent))]"
          >
            {primaryText}
          </button>
        ) : (
          <div
            role="button"
            tabIndex={0}
            onClick={onOpenDetail}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                onOpenDetail();
              }
            }}
            className="cursor-pointer text-left transition-colors hover:text-[hsl(var(--memory-accent))] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--memory-accent)/0.3)]"
          >
            <MarkdownBlock className="text-base font-semibold leading-7 text-[hsl(var(--memory-title))] [&_h1]:mb-2 [&_h1]:border-0 [&_h1]:pb-0 [&_h1]:text-base [&_h2]:mb-2 [&_h2]:mt-2 [&_h2]:text-base [&_h2]:normal-case [&_h2]:tracking-normal [&_h2]:text-[hsl(var(--memory-title))] [&_li]:text-base [&_p]:text-base [&_p]:leading-7">
              {primaryText}
            </MarkdownBlock>
          </div>
        )}
        {secondaryText ? (
          <MarkdownBlock className="mt-1.5 text-sm leading-6 text-[hsl(var(--memory-body))]">
            {secondaryText}
          </MarkdownBlock>
        ) : null}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {evidenceLabel ? (
            <span className="rounded-full border border-[hsl(var(--memory-border)/0.42)] bg-[hsl(var(--memory-panel-elevated)/0.68)] px-2.5 py-1 text-xs text-[hsl(var(--memory-muted))]">
              {evidenceLabel}
            </span>
          ) : null}
          <span className="rounded-full border border-[hsl(var(--memory-border)/0.42)] bg-[hsl(var(--memory-panel-elevated)/0.68)] px-2.5 py-1 text-xs text-[hsl(var(--memory-muted))]">
            {sourceLabel}
          </span>
        </div>
      </div>

      <div className="flex items-center justify-end gap-1 self-center">
        <Button
          variant="ghost"
          size="icon"
          onClick={onArchive}
          aria-label={t('memory.stories.actions.archive')}
          className="h-8 w-8 opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
        >
          <Archive className="h-4 w-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={onOpenDetail}
          aria-label={t('memory.stories.actions.viewEvidence')}
          className="h-8 w-8 text-[hsl(var(--memory-body))]"
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    </article>
  );
};

export default StoryCard;
