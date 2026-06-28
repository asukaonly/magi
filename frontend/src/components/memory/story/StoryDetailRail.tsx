import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';
import {
  memoryStoriesApi,
  type StoryEvidenceItem,
  type StoryItem,
} from '@/api/modules/memoryStories';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
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

export const StoryDetailRail = ({ story, onClose }: StoryDetailRailProps) => {
  const { t, i18n } = useTranslation('app');
  const [evidence, setEvidence] = useState<StoryEvidenceItem[] | null>(null);
  const [evidenceLoading, setEvidenceLoading] = useState(false);

  useEffect(() => {
    if (!story) {
      setEvidence(null);
      setEvidenceLoading(false);
      return;
    }
    let cancelled = false;
    setEvidenceLoading(true);
    setEvidence(null);
    memoryStoriesApi.evidence(story.summary_id, { limit: 25 })
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
  }, [story?.summary_id]);

  if (!story) return null;

  const period = story.period_end ? new Date(story.period_end * 1000).toLocaleString(i18n.language) : '';

  return (
    <Dialog open={Boolean(story)} onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent
      data-testid="story-detail-rail"
        hideClose
        className="max-h-[min(760px,calc(100vh-64px))] max-w-3xl overflow-hidden border-[hsl(var(--memory-border)/0.66)] bg-[hsl(var(--memory-panel-elevated)/0.98)] p-0"
    >
        <DialogHeader className="flex-row items-start justify-between gap-3 border-b border-[hsl(var(--memory-divider)/0.6)] px-6 py-4">
          <div className="min-w-0">
            <DialogDescription className="text-xs text-[hsl(var(--memory-muted))]">
            {t(`memory.stories.categories.${story.summary_category}`, { defaultValue: story.summary_category })}
            {period ? ` · ${period}` : ''}
            </DialogDescription>
            <DialogTitle className="mt-1 text-left text-lg font-semibold leading-7 text-[hsl(var(--memory-title))]">
              {story.title || story.content.slice(0, 80)}
            </DialogTitle>
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label={t('memory.stories.detailRail.close')}>
          <X className="h-4 w-4" />
        </Button>
        </DialogHeader>

        <div className="max-h-[calc(min(760px,100vh-64px)-96px)] space-y-4 overflow-y-auto px-6 py-4 text-sm leading-6 text-[hsl(var(--memory-body))]">
        <MarkdownBlock className="text-sm leading-6 text-[hsl(var(--memory-body))]">
          {story.content}
        </MarkdownBlock>

        <div>
          <div className="text-xs font-medium text-[hsl(var(--memory-muted))]">
            {t('memory.stories.detailRail.evidenceTitle')}
          </div>
          {evidenceLoading ? (
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
          )}
        </div>
      </div>
      </DialogContent>
    </Dialog>
  );
};

export default StoryDetailRail;
