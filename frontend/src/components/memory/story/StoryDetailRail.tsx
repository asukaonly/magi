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
        className="flex max-h-[min(860px,calc(100vh-48px))] max-w-[min(920px,calc(100vw-32px))] flex-col overflow-hidden border-[hsl(var(--memory-border)/0.42)] bg-[hsl(var(--memory-panel-elevated)/0.99)] p-0 shadow-[0_28px_80px_hsl(var(--memory-shadow)/0.16)]"
      >
        <DialogTitle className="sr-only">
          {headerLabel}
        </DialogTitle>

        <div
          data-testid="story-detail-header"
          className="flex shrink-0 items-center justify-between gap-4 px-6 pb-3 pt-5 sm:px-8"
        >
          <DialogDescription
            data-testid="story-detail-meta"
            className="w-fit text-xs font-medium leading-5 text-[hsl(var(--memory-muted))]"
          >
            {headerLabel}
          </DialogDescription>
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            aria-label={t('memory.stories.detailRail.close')}
            className="h-8 w-8 shrink-0 text-[hsl(var(--memory-muted))] hover:text-[hsl(var(--memory-title))]"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div
          data-testid="story-detail-scroll"
          className="min-h-0 flex-1 overflow-y-auto px-6 pb-8 pt-2 text-sm leading-7 text-[hsl(var(--memory-body))] sm:px-8"
        >
          <MarkdownBlock className="mx-auto max-w-[740px] text-[0.95rem] font-normal leading-7 text-[hsl(var(--memory-body))] [&_code]:rounded-sm [&_code]:border-0 [&_code]:bg-[hsl(var(--memory-panel-subtle)/0.62)] [&_code]:font-sans [&_code]:shadow-none [&_h1]:mb-6 [&_h1]:border-0 [&_h1]:pb-0 [&_h1]:text-2xl [&_h2]:mb-3 [&_h2]:mt-8 [&_h2]:text-base [&_h2]:normal-case [&_h2]:tracking-normal [&_h2]:text-[hsl(var(--memory-title))] [&_li]:pl-0.5 [&_ol]:my-3 [&_ol]:space-y-2 [&_p]:leading-7 [&_ul]:my-3 [&_ul]:space-y-2">
            {story.content}
          </MarkdownBlock>

          <div className="mx-auto mt-8 max-w-[740px] border-t border-[hsl(var(--memory-divider)/0.42)] pt-4">
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
                      className="rounded-md bg-[hsl(var(--memory-panel-subtle)/0.52)] px-3.5 py-3"
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
