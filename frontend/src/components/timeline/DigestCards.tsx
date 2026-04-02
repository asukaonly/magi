import React, { useCallback, useEffect, useState } from 'react';
import { BookOpen, RefreshCw, Sparkles } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import { timelineApi, type TimelineDigestSummary } from '@/api/modules/timeline';

interface DigestCardsProps {
  category: string;
}

const formatPeriod = (start: number, end: number): string => {
  const s = new Date(start * 1000);
  const e = new Date(end * 1000);
  const dateOpts: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric' };
  const timeOpts: Intl.DateTimeFormatOptions = { hour: '2-digit', minute: '2-digit' };
  const sf = s.toLocaleDateString(undefined, dateOpts);
  const ef = e.toLocaleDateString(undefined, dateOpts);
  if (sf === ef) {
    return `${sf} ${s.toLocaleTimeString(undefined, timeOpts)} – ${e.toLocaleTimeString(undefined, timeOpts)}`;
  }
  return `${sf} – ${ef}`;
};

export const DigestCards: React.FC<DigestCardsProps> = ({ category }) => {
  const { t } = useTranslation('app');
  const [digests, setDigests] = useState<TimelineDigestSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);

  const loadDigests = useCallback(async () => {
    try {
      const data = await timelineApi.getDigests({ limit: 3, category });
      setDigests(data);
    } catch {
      // silent – digests are supplementary
    } finally {
      setLoading(false);
    }
  }, [category]);

  useEffect(() => {
    setLoading(true);
    void loadDigests();
  }, [loadDigests]);

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      const result = await timelineApi.triggerDigest(category);
      if (result.status === 'generated') {
        toast.success(t('timeline.digest.generated'));
        void loadDigests();
      } else {
        toast.info(t('timeline.digest.noEvents'));
      }
    } catch (error: any) {
      toast.error(t('timeline.digest.generateFailed', { message: error?.message || 'unknown' }));
    } finally {
      setGenerating(false);
    }
  };

  if (loading) return null;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <BookOpen className="h-3 w-3" />
          {t('timeline.digest.title')}
        </h3>
        <button
          className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground disabled:opacity-50"
          onClick={handleGenerate}
          disabled={generating}
        >
          {generating ? (
            <RefreshCw className="h-3 w-3 animate-spin" />
          ) : (
            <Sparkles className="h-3 w-3" />
          )}
          {t('timeline.digest.generate')}
        </button>
      </div>

      {digests.length === 0 ? (
        <p className="text-xs text-muted-foreground/60">{t('timeline.digest.empty')}</p>
      ) : (
        <div className="space-y-2">
          {digests.map((d) => (
            <article
              key={d.summary_id}
              className="rounded-lg border border-border/40 bg-card px-4 py-3 transition-colors hover:border-border"
            >
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-[11px] tabular-nums text-muted-foreground/60">
                  {formatPeriod(d.period_start, d.period_end)}
                </span>
                {d.source_event_count != null && (
                  <span className="text-[11px] tabular-nums text-muted-foreground/50">
                    {t('timeline.feed.sourceEventCount', { count: d.source_event_count })}
                  </span>
                )}
              </div>
              <p className="mt-1.5 text-sm leading-relaxed text-foreground/90">{d.content}</p>
              {d.key_topics.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {d.key_topics.slice(0, 5).map((topic) => (
                    <span
                      key={topic}
                      className="rounded-full bg-muted/50 px-2 py-0.5 text-[11px] text-muted-foreground"
                    >
                      {topic}
                    </span>
                  ))}
                </div>
              )}
            </article>
          ))}
        </div>
      )}
    </div>
  );
};

export default DigestCards;
