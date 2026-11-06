import { ChevronRight, Feather, Image } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { TimelineReviewPeriod, TimelineStandoutItem, TimelineViewportResponse } from '@/api/modules/timeline';
import { ProtectedImage } from '@/components/media/ProtectedImage';
import { cn } from '@/lib/utils';
import { readableText } from './scene-presentation';
import { SourceIcon, labelForSource } from './SourceIcon';
import { ReviewDatePicker } from './ReviewDatePicker';

interface Props {
  viewport: TimelineViewportResponse;
  scale: 'week' | 'month';
  dateLabel: string;
  onSelectPeriod?: (period: TimelineReviewPeriod) => void;
  onAddNote?: () => void;
  onOpenCover?: () => void;
  coverUrl?: string | null;
  standoutItems?: TimelineStandoutItem[];
  onSelectStandout?: (item: TimelineStandoutItem) => void;
  selectedTopic: string;
  onSelectTopic: (topic: string) => void;
}

export function PeriodReviewReader({ viewport, scale, dateLabel, onSelectPeriod, onAddNote, onOpenCover, coverUrl, standoutItems = [], onSelectStandout, selectedTopic, onSelectTopic }: Props) {
  const { t, i18n } = useTranslation('app');
  const locale = i18n.resolvedLanguage || i18n.language;
  const review = viewport.period_review;
  const topics = review?.topics ?? [];
  const selected = topics.find(topic => topic.topic_id === selectedTopic);
  const periods = (review?.periods ?? []).filter(period => !selected || selected.period_starts.includes(period.start));
  const date = (timestamp: number, weekday = false) => new Date(timestamp * 1000).toLocaleDateString(locale, { month: 'numeric', day: 'numeric', ...(weekday ? { weekday: 'short' } : {}) });
  const summary = readableText(viewport.overview.essence_prose || viewport.overview.summary);
  return <div className="mx-auto w-full max-w-[1180px] px-5 py-7 text-foreground sm:px-8 lg:px-10" data-testid="period-review">
    <header className="mb-7">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <ReviewDatePicker dateLabel={dateLabel} />
        <div className="flex items-center gap-2 text-muted-foreground">
          {onAddNote ? <button type="button" onClick={onAddNote} className="inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-[13px] hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"><Feather className="h-4 w-4" />{t('timeline.review.addNote')}</button> : null}
          {onOpenCover ? <button type="button" onClick={onOpenCover} aria-label={t('timeline.cover.open')} className="flex h-8 w-8 items-center justify-center overflow-hidden rounded-md hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring">{coverUrl ? <ProtectedImage data-testid="timeline-period-cover" src={coverUrl} alt="" className="h-full w-full object-cover" /> : <Image className="h-4 w-4" />}</button> : null}
        </div>
      </div>
      {summary ? <p className="mt-3 line-clamp-2 max-w-[860px] text-[14px] leading-6 text-muted-foreground">{summary}</p> : null}
      {review?.summary_status !== 'ready' ? <p className="mt-2 text-[12px] leading-5 text-muted-foreground">{t(viewport.summary.event_count ? 'timeline.period.partial' : 'timeline.period.empty')}</p> : null}
    </header>
    {topics.length > 0 ? <section className="mb-7" aria-label={t('timeline.period.topics')}>
      <h2 className="mb-3 text-[13px] font-medium text-muted-foreground">{t(scale === 'week' ? 'timeline.period.weekTopics' : 'timeline.period.topics')}</h2>
      <div className="grid gap-4 sm:grid-cols-3">
        {topics.map(topic => <button key={topic.topic_id} type="button" aria-pressed={selected?.topic_id === topic.topic_id}
          onClick={() => onSelectTopic(selected?.topic_id === topic.topic_id ? '' : topic.topic_id)}
          className={cn('min-w-0 border-t-2 px-1 py-3 text-left transition-colors hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring', selected?.topic_id === topic.topic_id ? 'border-primary/65 bg-muted/40' : 'border-border/65')}>
          <span className="block text-[16px] font-medium leading-6 wrap-anywhere">{topic.title}</span>
          {topic.summary ? <span className="mt-1.5 line-clamp-2 text-[13px] leading-5 text-muted-foreground">{topic.summary}</span> : null}
          <span className="mt-3 flex gap-1.5"><Sources sources={topic.source_types} /></span>
        </button>)}
      </div>
    </section> : null}
    <section aria-label={t(scale === 'month' ? 'timeline.period.weeks' : 'timeline.period.days')}>
      <div className="mb-2 flex items-center justify-between gap-3">
        <h2 className="text-[13px] font-medium text-muted-foreground">{selected ? `${selected.title} · ` : ''}{t(scale === 'month' ? 'timeline.period.weeks' : 'timeline.period.days')}</h2>
        {selected ? <button type="button" onClick={() => onSelectTopic('')} className="text-[12px] text-muted-foreground underline underline-offset-4">{t('timeline.period.showAll')}</button> : null}
      </div>
      <div className="divide-y divide-border/55 border-y border-border/55">
        {periods.map(period => <button key={period.start} id={`review-period-${period.target_start}`} type="button" onClick={() => onSelectPeriod?.(period)}
          className="grid w-full grid-cols-[90px_minmax(0,1fr)_14px] items-center gap-3 rounded-md py-3.5 text-left hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring sm:grid-cols-[118px_minmax(0,1fr)_72px_14px]">
          <span className="text-[12px] leading-5 tabular-nums text-muted-foreground">{scale === 'week' ? date(period.start, true) : `${date(period.start)}–${date(period.end - 1)}`}</span>
          <span className={cn('line-clamp-2 text-[14px] leading-6 wrap-anywhere', !period.event_count && 'text-muted-foreground')}>
            {period.summary || (period.event_count ? t('timeline.period.recordedSources', { sources: period.source_types.slice(0, 3).map(source => labelForSource(source, t)).join('、') }) : t('timeline.period.noRecords'))}
          </span>
          <span className="hidden justify-end gap-1.5 sm:flex"><Sources sources={period.source_types.slice(0, 3)} /></span>
          <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
        </button>)}
      </div>
    </section>
    {!selected && standoutItems.length > 0 ? <section className="mt-7" aria-label={t('timeline.period.highlights')}>
      <h2 className="mb-2 text-[13px] font-medium text-muted-foreground">{t('timeline.period.highlights')}</h2>
      <div className="divide-y divide-border/55 border-y border-border/55">{standoutItems.slice(0, 3).map(item => <button key={item.episode_id} type="button" onClick={() => onSelectStandout?.(item)}
        className="flex w-full items-center gap-4 py-3 text-left hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring">
        <span className="w-[90px] shrink-0 text-[12px] tabular-nums text-muted-foreground sm:w-[118px]">{date(item.start)}</span>
        <span className="min-w-0 flex-1 text-[14px] leading-6">{readableText(item.title)}</span><ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      </button>)}</div>
    </section> : null}
  </div>;
}

function Sources({ sources }: { sources: string[] }) {
  return <>{sources.map(source => <SourceIcon key={source} sourceType={source} className="h-[18px] w-[18px] shrink-0" />)}</>;
}
