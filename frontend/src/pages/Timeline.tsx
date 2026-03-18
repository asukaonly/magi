import React, { useEffect, useMemo, useState } from 'react';
import { CalendarRange, Filter, PenSquare, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';

import {
  timelineApi,
  type TimelineEventDetail,
  type TimelineManualEntryRequest,
  type TimelineProjectionDisplayPayload,
  type TimelineProjectionItem,
} from '@/api/modules/timeline';
import TimelineComposer from '@/components/timeline/TimelineComposer';
import TimelineFeed from '@/components/timeline/TimelineFeed';
import { Button } from '@/components/ui/button';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { cn } from '@/lib/utils';
import { useChatShellStore } from '@/stores';

type RangeOption = 'all' | '7d' | '30d';

const sortItems = (items: TimelineProjectionItem[]): TimelineProjectionItem[] =>
  [...items].sort((left, right) => right.sort_time - left.sort_time);

const fallbackSourceLabel = (source: string) =>
  source
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');

const isEventItem = (item: TimelineProjectionItem): boolean => item.item_type === 'event';

const getEventSourceType = (item: TimelineProjectionItem): string =>
  item.display_payload.source_type || 'memory';

const mergeDetailIntoProjection = (
  item: TimelineProjectionItem,
  detail: TimelineEventDetail
): TimelineProjectionItem => {
  if (!isEventItem(item) || item.primary_event_id !== detail.event_id) {
    return item;
  }

  const nextPayload: TimelineProjectionDisplayPayload = {
    ...item.display_payload,
    title: detail.title,
    summary: detail.summary,
    source_type: detail.source_type,
    source_item_id: detail.source_item_id,
    content_blocks: detail.content_blocks,
    entities: detail.entities,
    tags: detail.tags,
    retention_mode: detail.retention?.mode || detail.retention_mode,
    raw_payload_ref: detail.retention?.raw_payload_ref || detail.raw_payload_ref,
    provenance: detail.provenance,
  };

  return {
    ...item,
    display_payload: nextPayload,
  };
};

export const TimelinePage: React.FC = () => {
  const { t } = useTranslation('app');
  const setActivePanel = useChatShellStore((state) => state.setActivePanel);
  const [items, setItems] = useState<TimelineProjectionItem[]>([]);
  const [eventDetails, setEventDetails] = useState<Record<string, TimelineEventDetail | undefined>>({});
  const [selectedSource, setSelectedSource] = useState('all');
  const [selectedRange, setSelectedRange] = useState<RangeOption>('all');
  const [expandedEventId, setExpandedEventId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadingDetailId, setLoadingDetailId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [reanalyzingEventId, setReanalyzingEventId] = useState<string | null>(null);
  const [composerOpen, setComposerOpen] = useState(false);

  const eventItems = useMemo(() => items.filter(isEventItem), [items]);
  const sourceOptions = ['all', ...Array.from(new Set(eventItems.map(getEventSourceType)))];

  const getSourceLabel = (source: string) => {
    const key = `timeline.sources.${source}`;
    const translated = t(key);
    return translated === key ? fallbackSourceLabel(source) : translated;
  };

  const filteredItems = useMemo(
    () =>
      selectedSource === 'all'
        ? items
        : items.filter((item) => isEventItem(item) && getEventSourceType(item) === selectedSource),
    [items, selectedSource]
  );

  const sourceBreakdown = sourceOptions
    .filter((source) => source !== 'all')
    .map((source) => ({
      source,
      count: eventItems.filter((item) => getEventSourceType(item) === source).length,
    }))
    .filter((entry) => entry.count > 0);

  const totalDerivedEdges = Object.values(eventDetails).reduce((sum, detail) => sum + (detail?.graph_evidence.length || 0), 0);
  const sourceMixSummary = sourceBreakdown
    .slice(0, 3)
    .map((entry) => `${getSourceLabel(entry.source)} ${entry.count}`)
    .join(' · ');

  const filteredSummary = useMemo(() => {
    if (filteredItems.length === items.length) {
      return t('timeline.summary.showingAll');
    }
    return t('timeline.summary.showingFiltered', { count: filteredItems.length });
  }, [filteredItems.length, items.length, t]);

  const loadItems = async (mode: 'initial' | 'refresh' = 'initial', range: RangeOption = selectedRange) => {
    if (mode === 'initial') {
      setLoading(true);
    } else {
      setRefreshing(true);
    }
    try {
      const response = await timelineApi.listItems({ limit: 80, range });
      setItems(sortItems(response.items || []));
    } catch (error: any) {
      toast.error(t('timeline.errors.loadFailed', { message: error?.message || 'unknown' }));
    } finally {
      if (mode === 'initial') {
        setLoading(false);
      } else {
        setRefreshing(false);
      }
    }
  };

  useEffect(() => {
    setActivePanel('timeline');
  }, [setActivePanel]);

  useEffect(() => {
    void loadItems('initial', selectedRange);
  }, [selectedRange]);

  const handleToggleDetails = async (eventId: string) => {
    if (expandedEventId === eventId) {
      setExpandedEventId(null);
      return;
    }
    setExpandedEventId(eventId);
    if (eventDetails[eventId]) {
      return;
    }
    setLoadingDetailId(eventId);
    try {
      const detail = await timelineApi.getEvent(eventId);
      setEventDetails((current) => ({ ...current, [eventId]: detail }));
    } catch (error: any) {
      toast.error(t('timeline.errors.detailFailed', { message: error?.message || 'unknown' }));
    } finally {
      setLoadingDetailId(null);
    }
  };

  const handleManualEntrySubmit = async (payload: TimelineManualEntryRequest) => {
    setSubmitting(true);
    try {
      const created = await timelineApi.createManualEntry(payload);
      setExpandedEventId(created.event_id);
      setComposerOpen(false);
      await loadItems('refresh');
      toast.success(t('timeline.composer.created'));
    } catch (error: any) {
      toast.error(t('timeline.errors.createFailed', { message: error?.message || 'unknown' }));
    } finally {
      setSubmitting(false);
    }
  };

  const handleReanalyze = async (eventId: string) => {
    setReanalyzingEventId(eventId);
    try {
      const result = await timelineApi.requestReanalysis(eventId);
      const nextDetail = result.event;
      setEventDetails((current) => ({ ...current, [eventId]: nextDetail }));
      setItems((current) => sortItems(current.map((item) => mergeDetailIntoProjection(item, nextDetail))));
      toast.success(t('timeline.feed.reanalyzeQueued'));
    } catch (error: any) {
      toast.error(t('timeline.errors.reanalyzeFailed', { message: error?.message || 'unknown' }));
    } finally {
      setReanalyzingEventId(null);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-background">
      <header className="border-b border-border/60 px-6 py-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-2">
            <div className="text-[11px] uppercase tracking-[0.18em] text-primary">{t('timeline.hero.eyebrow')}</div>
            <div className="space-y-1">
              <h1 className="text-[clamp(1.75rem,2.6vw,2.2rem)] font-semibold tracking-tight text-foreground">
                {t('timeline.title')}
              </h1>
              <p className="max-w-2xl text-sm leading-6 text-muted-foreground">{t('timeline.subtitle')}</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Button
              variant={composerOpen ? 'secondary' : 'outline'}
              size="sm"
              onClick={() => setComposerOpen((current) => !current)}
              aria-label={composerOpen ? t('timeline.actions.closeEntry') : t('timeline.actions.addEntry')}
            >
              <PenSquare className="mr-2 h-4 w-4" />
              {composerOpen ? t('timeline.actions.closeEntry') : t('timeline.actions.addEntry')}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void loadItems('refresh')}
              disabled={refreshing}
              aria-label={t('timeline.actions.refresh')}
            >
              <RefreshCw className={cn('mr-2 h-4 w-4', refreshing && 'animate-spin')} />
              {t('timeline.actions.refresh')}
            </Button>
          </div>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent">
        <section className="flex min-h-0 flex-col overflow-hidden">
          <div className="space-y-4 border-b border-border/60 pb-4">
            <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm text-muted-foreground">
              <span>{eventItems.length} {t('timeline.summary.totalEvents')}</span>
              <span>{totalDerivedEdges} {t('timeline.summary.derivedEdges')}</span>
              {sourceMixSummary ? <span>{sourceMixSummary}</span> : null}
              <span>{filteredSummary}</span>
            </div>

            <div className="flex flex-wrap items-end gap-3">
              <label className="min-w-[172px] flex-1 space-y-1.5" htmlFor="timeline-source-filter">
                <span className="inline-flex items-center gap-2 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
                  <Filter className="h-3.5 w-3.5" />
                  {t('timeline.filters.source')}
                </span>
                <select
                  id="timeline-source-filter"
                  className="h-9 w-full rounded-lg border border-input bg-background px-3 text-sm"
                  value={selectedSource}
                  onChange={(event) => setSelectedSource(event.target.value)}
                >
                  <option value="all">{t('timeline.filters.allSources')}</option>
                  {sourceOptions.filter((source) => source !== 'all').map((source) => (
                    <option key={source} value={source}>
                      {getSourceLabel(source)}
                    </option>
                  ))}
                </select>
              </label>

              <label className="min-w-[156px] flex-1 space-y-1.5" htmlFor="timeline-range-filter">
                <span className="inline-flex items-center gap-2 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
                  <CalendarRange className="h-3.5 w-3.5" />
                  {t('timeline.filters.range')}
                </span>
                <select
                  id="timeline-range-filter"
                  className="h-9 w-full rounded-lg border border-input bg-background px-3 text-sm"
                  value={selectedRange}
                  onChange={(event) => setSelectedRange(event.target.value as RangeOption)}
                >
                  <option value="all">{t('timeline.filters.allTime')}</option>
                  <option value="7d">{t('timeline.filters.last7Days')}</option>
                  <option value="30d">{t('timeline.filters.last30Days')}</option>
                </select>
              </label>

              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => {
                  setSelectedSource('all');
                  setSelectedRange('all');
                }}
                aria-label={t('timeline.filters.clear')}
              >
                {t('timeline.filters.clear')}
              </Button>
            </div>
          </div>

          {composerOpen ? (
            <div className="border-b border-border/60 py-5">
              <TimelineComposer submitting={submitting} onSubmit={handleManualEntrySubmit} />
            </div>
          ) : null}

          <div className="mt-4 min-h-0 flex-1 pr-1">
            {loading ? (
              <div className="flex h-full min-h-[220px] items-center justify-center gap-3 text-sm text-muted-foreground">
                <LoadingSpinner className="h-4 w-4" />
                {t('timeline.loading')}
              </div>
            ) : (
              <TimelineFeed
                items={filteredItems}
                expandedEventId={expandedEventId}
                eventDetails={eventDetails}
                loadingDetailId={loadingDetailId}
                reanalyzingEventId={reanalyzingEventId}
                onToggleDetails={(eventId) => void handleToggleDetails(eventId)}
                onReanalyze={handleReanalyze}
              />
            )}
          </div>
        </section>
      </div>
    </div>
  );
};

export default TimelinePage;
