import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, X } from 'lucide-react';
import {
  memoryStoriesApi,
  type StoryEvidenceItem,
  type StoryItem,
} from '@/api/modules/memoryStories';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from '@/components/ui/dialog';
import { MarkdownBlock } from '@/components/ui/markdown-block';

interface StoryDetailRailProps {
  story: StoryItem | null;
  onClose: () => void;
}

const formatEvidenceTimestamp = (ts: number | null, locale: string): string => {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleString(locale, {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
};

const formatDateOnly = (date: Date, locale: string): string => (
  new Intl.DateTimeFormat(locale, {
    month: 'numeric',
    day: 'numeric',
  }).format(date)
);

const displayPeriodEndDate = (periodStart: number, periodEnd: number): Date => {
  const endDate = new Date(periodEnd * 1000);
  if (
    periodEnd > periodStart
    && endDate.getHours() === 0
    && endDate.getMinutes() === 0
    && endDate.getSeconds() === 0
    && endDate.getMilliseconds() === 0
  ) {
    return new Date(endDate.getTime() - 1000);
  }
  return endDate;
};

const formatStoryPeriod = (story: StoryItem, locale: string): string => {
  if (story.period_start != null && story.period_end != null) {
    const startDate = new Date(story.period_start * 1000);
    const endDate = displayPeriodEndDate(story.period_start, story.period_end);
    const startText = formatDateOnly(startDate, locale);
    const endText = formatDateOnly(endDate, locale);
    return startText === endText ? startText : `${startText} - ${endText}`;
  }
  if (!story.display_timestamp) return '';
  return formatDateOnly(new Date(story.display_timestamp * 1000), locale);
};

export const StoryDetailRail = ({ story, onClose }: StoryDetailRailProps) => {
  const { t, i18n } = useTranslation('app');
  const [evidence, setEvidence] = useState<StoryEvidenceItem[] | null>(null);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidenceTargetId, setEvidenceTargetId] = useState<string | null>(null);

  useEffect(() => {
    setEvidenceOpen(false);
    setEvidence(null);
    setEvidenceLoading(false);
    setEvidenceTargetId(story?.summary_id ?? null);
  }, [story?.summary_id]);

  useEffect(() => {
    const summaryId = story?.summary_id;
    if (!summaryId || !evidenceOpen || evidence !== null || evidenceTargetId !== summaryId) return;
    let cancelled = false;
    setEvidenceLoading(true);
    memoryStoriesApi.evidence(summaryId, { limit: 25 })
      .then((payload) => {
        if (cancelled) return;
        setEvidence(payload.items);
      })
      .catch(() => {
        if (cancelled) return;
        setEvidence([]);
      })
      .finally(() => {
        if (cancelled) return;
        setEvidenceLoading(false);
      });
    return () => { cancelled = true; };
  }, [story?.summary_id, evidenceOpen, evidenceTargetId]);

  if (!story) return null;

  const categoryLabel = t(`memory.stories.categories.${story.summary_category}`, { defaultValue: story.summary_category });
  const period = formatStoryPeriod(story, i18n.language);
  const headerLabel = period ? `${categoryLabel} · ${period}` : categoryLabel;

  return (
    <Dialog open={Boolean(story)} onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent
        data-testid="story-detail-rail"
        hideClose
        className="relative flex max-h-[min(760px,calc(100vh-64px))] max-w-3xl flex-col overflow-hidden border-[hsl(var(--memory-border)/0.66)] bg-[hsl(var(--memory-panel-elevated)/0.98)] p-0"
      >
        <DialogTitle className="sr-only">
          {headerLabel}
        </DialogTitle>
        <Button
          variant="ghost"
          size="icon"
          onClick={onClose}
          aria-label={t('memory.stories.detailRail.close')}
          className="absolute right-4 top-4 z-10 h-8 w-8"
        >
          <X className="h-4 w-4" />
        </Button>

        <div
          data-testid="story-detail-scroll"
          className="min-h-0 flex-1 space-y-4 overflow-y-auto px-6 pb-6 pt-5 text-sm leading-6 text-[hsl(var(--memory-body))]"
        >
          <DialogDescription
            data-testid="story-detail-meta"
            className="w-fit pr-10 text-xs leading-5 text-[hsl(var(--memory-muted))]"
          >
            {headerLabel}
          </DialogDescription>

          <MarkdownBlock className="text-sm leading-6 text-[hsl(var(--memory-body))]">
            {story.content}
          </MarkdownBlock>

          <div className="border-t border-[hsl(var(--memory-divider)/0.55)] pt-3">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              aria-expanded={evidenceOpen}
              onClick={() => setEvidenceOpen((open) => !open)}
              className="h-8 gap-1 px-0 text-xs font-medium text-[hsl(var(--memory-muted))] hover:bg-transparent hover:text-[hsl(var(--memory-title))]"
            >
              <ChevronDown
                className={cn(
                  'h-3.5 w-3.5 transition-transform',
                  evidenceOpen ? 'rotate-180' : ''
                )}
              />
              {t('memory.stories.detailRail.evidenceToggle', { count: story.evidence_event_count })}
            </Button>
            {evidenceOpen ? (
              evidenceLoading ? (
                <div className="mt-2 text-xs text-[hsl(var(--memory-muted))]">
                  {t('memory.stories.detailRail.evidenceLoading')}
                </div>
              ) : evidence && evidence.length > 0 ? (
                <ul className="mt-2 space-y-2">
                  {evidence.map((item) => (
                    <li
                      key={item.event_id}
                      className="rounded-md border border-[hsl(var(--memory-border)/0.4)] bg-[hsl(var(--memory-panel-subtle)/0.5)] px-3 py-2"
                    >
                      <div className="flex flex-wrap items-center gap-2 text-[10px] text-[hsl(var(--memory-muted))]">
                        <span>{formatEvidenceTimestamp(item.timestamp, i18n.language)}</span>
                        {item.source ? <span>· {item.source}</span> : null}
                        {item.event_type ? <span>· {item.event_type}</span> : null}
                      </div>
                      <div className="mt-1 text-xs leading-5 text-[hsl(var(--memory-body))]">
                        {item.content || '—'}
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="mt-2 text-xs text-[hsl(var(--memory-muted))]">
                  {t('memory.stories.detailRail.evidenceEmpty')}
                </div>
              )
            ) : null}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default StoryDetailRail;
