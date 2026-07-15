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
    case 'rejected':
    case 'archived':
      return 'opacity-60';
    default:
      return '';
  }
};

const storyTimestamp = (story: StoryItem): number | null => (
  story.display_timestamp || null
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
  const primaryText = String(story.preview_text || story.title || story.content).trim();
  const dateLabel = formatStoryDate(story, i18n.language);
  const evidenceLabel = story.evidence_event_count > 0
    ? t('memory.stories.evidenceChip', { count: story.evidence_event_count })
    : null;

  return (
    <article
      data-testid={`story-card-${story.summary_id}`}
      className={cn(
        'group grid gap-3 rounded-lg px-3 py-5 transition-colors duration-200 hover:bg-[hsl(var(--memory-panel-subtle)/0.42)] md:grid-cols-[120px_minmax(0,1fr)_72px] md:items-center md:gap-5',
        stateToneClass(story.review_state)
      )}
    >
      <div className="flex flex-row items-center gap-2 text-xs md:flex-col md:items-start md:gap-1.5">
        <span className="font-medium text-[hsl(var(--memory-accent))]">
          {categoryLabel}
        </span>
        {dateLabel ? <span className="text-[hsl(var(--memory-muted))]">{dateLabel}</span> : null}
      </div>

      <div className="min-w-0">
        <button
          type="button"
          onClick={onOpenDetail}
          className="block w-full rounded-sm text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--memory-accent)/0.18)]"
        >
          <p className="line-clamp-3 whitespace-pre-wrap text-[0.95rem] font-normal leading-7 text-[hsl(var(--memory-title))] transition-colors group-hover:text-[hsl(var(--memory-accent))]">
            {primaryText}
          </p>
        </button>
        {evidenceLabel ? (
          <span className="mt-2 block text-xs text-[hsl(var(--memory-muted))]">
            {evidenceLabel}
          </span>
        ) : null}
      </div>

      <div className="flex items-center justify-end gap-1 self-center">
        <Button
          variant="ghost"
          size="icon"
          onClick={onArchive}
          aria-label={t('memory.stories.actions.archive')}
          className="h-8 w-8 text-[hsl(var(--memory-muted))] opacity-60 transition-[color,opacity] hover:text-[hsl(var(--memory-title))] md:opacity-0 md:group-hover:opacity-100 md:focus-visible:opacity-100"
        >
          <Archive className="h-4 w-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={onOpenDetail}
          aria-label={t('memory.stories.actions.readFull')}
          className="h-8 w-8 text-[hsl(var(--memory-muted))] transition-colors hover:text-[hsl(var(--memory-accent))]"
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    </article>
  );
};

export default StoryCard;
