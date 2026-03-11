import React, { useEffect, useMemo, useState } from 'react';
import { CalendarRange, Filter, LayoutList, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';

import {
  timelineApi,
  type TimelineEventDetail,
  type TimelineEventRecord,
  type TimelineManualEntryRequest,
} from '@/api/modules/timeline';
import TimelineComposer from '@/components/timeline/TimelineComposer';
import TimelineFeed from '@/components/timeline/TimelineFeed';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { cn } from '@/lib/utils';
import { useChatShellStore } from '@/stores';

type RangeOption = 'all' | '7d' | '30d';
type ViewMode = 'comfortable' | 'compact';

const sortEvents = (events: TimelineEventRecord[]): TimelineEventRecord[] =>
  [...events].sort((left, right) => right.occurred_at - left.occurred_at);

const filterEventsByRange = (events: TimelineEventRecord[], range: RangeOption): TimelineEventRecord[] => {
  if (range === 'all') {
    return events;
  }
  const now = Date.now() / 1000;
  const days = range === '7d' ? 7 : 30;
  const cutoff = now - days * 24 * 60 * 60;
  return events.filter((event) => event.occurred_at >= cutoff);
};

const fallbackSourceLabel = (source: string) =>
  source
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');

export const TimelinePage: React.FC = () => {
  const { t } = useTranslation('app');
  const setActivePanel = useChatShellStore((state) => state.setActivePanel);
  const [events, setEvents] = useState<TimelineEventRecord[]>([]);
  const [eventDetails, setEventDetails] = useState<Record<string, TimelineEventDetail | undefined>>({});
  const [selectedSource, setSelectedSource] = useState('all');
  const [selectedRange, setSelectedRange] = useState<RangeOption>('all');
  const [viewMode, setViewMode] = useState<ViewMode>('comfortable');
  const [expandedEventId, setExpandedEventId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadingDetailId, setLoadingDetailId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [reanalyzingEventId, setReanalyzingEventId] = useState<string | null>(null);

  const sourceOptions = ['all', ...Array.from(new Set(events.map((event) => event.source_type)))];

  const getSourceLabel = (source: string) => {
    const key = `timeline.sources.${source}`;
    const translated = t(key);
    return translated === key ? fallbackSourceLabel(source) : translated;
  };

  const filteredEvents = filterEventsByRange(
    selectedSource === 'all' ? events : events.filter((event) => event.source_type === selectedSource),
    selectedRange
  );

  const sourceBreakdown = sourceOptions
    .filter((source) => source !== 'all')
    .map((source) => ({
      source,
      count: events.filter((event) => event.source_type === source).length,
    }))
    .filter((entry) => entry.count > 0);

  const totalDerivedEdges = Object.values(eventDetails).reduce((sum, detail) => sum + (detail?.graph_evidence.length || 0), 0);

  const filteredSummary = useMemo(() => {
    if (filteredEvents.length === events.length) {
      return t('timeline.summary.showingAll');
    }
    return t('timeline.summary.showingFiltered', { count: filteredEvents.length });
  }, [events.length, filteredEvents.length, t]);

  const loadEvents = async (mode: 'initial' | 'refresh' = 'initial') => {
    if (mode === 'initial') {
      setLoading(true);
    } else {
      setRefreshing(true);
    }
    try {
      const response = await timelineApi.listEvents({ limit: 80 });
      setEvents(sortEvents(response.events || []));
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
    void loadEvents();
  }, [setActivePanel]);

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
      setEvents((current) => sortEvents([created, ...current]));
      setExpandedEventId(created.event_id);
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
      setEvents((current) =>
        sortEvents(current.map((event) => (event.event_id === eventId ? { ...event, ...nextDetail } : event)))
      );
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
            <Badge variant="outline" className="rounded-full px-3 py-1 text-xs">
              {events.length} {t('timeline.summary.totalEvents')}
            </Badge>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void loadEvents('refresh')}
              disabled={refreshing}
              aria-label={t('timeline.actions.refresh')}
            >
              <RefreshCw className={cn('mr-2 h-4 w-4', refreshing && 'animate-spin')} />
              {t('timeline.actions.refresh')}
            </Button>
          </div>
        </div>
      </header>

      <div className="grid min-h-0 flex-1 gap-8 overflow-hidden px-6 py-5 xl:grid-cols-[minmax(0,1fr)_320px]">
        <section className="flex min-h-0 flex-col overflow-hidden">
          <div className="border-b border-border/60 pb-4">
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

              <label className="min-w-[156px] flex-1 space-y-1.5" htmlFor="timeline-view-mode">
                <span className="inline-flex items-center gap-2 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
                  <LayoutList className="h-3.5 w-3.5" />
                  {t('timeline.filters.viewMode')}
                </span>
                <select
                  id="timeline-view-mode"
                  className="h-9 w-full rounded-lg border border-input bg-background px-3 text-sm"
                  value={viewMode}
                  onChange={(event) => setViewMode(event.target.value as ViewMode)}
                >
                  <option value="comfortable">{t('timeline.filters.comfortable')}</option>
                  <option value="compact">{t('timeline.filters.compact')}</option>
                </select>
              </label>

              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => {
                  setSelectedSource('all');
                  setSelectedRange('all');
                  setViewMode('comfortable');
                }}
                aria-label={t('timeline.filters.clear')}
              >
                {t('timeline.filters.clear')}
              </Button>
            </div>
          </div>

          <div className="mt-4 min-h-0 flex-1 overflow-y-auto pr-1 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent">
            {loading ? (
              <div className="flex h-full min-h-[220px] items-center justify-center gap-3 text-sm text-muted-foreground">
                <LoadingSpinner className="h-4 w-4" />
                {t('timeline.loading')}
              </div>
            ) : (
              <TimelineFeed
                events={filteredEvents}
                expandedEventId={expandedEventId}
                eventDetails={eventDetails}
                loadingDetailId={loadingDetailId}
                reanalyzingEventId={reanalyzingEventId}
                viewMode={viewMode}
                onToggleDetails={(eventId) => void handleToggleDetails(eventId)}
                onReanalyze={handleReanalyze}
              />
            )}
          </div>
        </section>

        <aside className="min-h-0 overflow-y-auto border-l border-border/60 pl-6 pr-1 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent">
          <div className="space-y-8">
            <section className="space-y-4">
              <div className="space-y-1">
                <h2 className="text-sm font-semibold text-foreground">{t('timeline.summary.title')}</h2>
                <p className="text-sm text-muted-foreground">{filteredSummary}</p>
              </div>

              <dl className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
                <div className="flex items-baseline justify-between border-b border-border/60 pb-2">
                  <dt className="text-sm text-muted-foreground">{t('timeline.summary.totalEvents')}</dt>
                  <dd className="text-lg font-semibold text-foreground">{events.length}</dd>
                </div>
                <div className="flex items-baseline justify-between border-b border-border/60 pb-2">
                  <dt className="text-sm text-muted-foreground">{t('timeline.summary.derivedEdges')}</dt>
                  <dd className="text-lg font-semibold text-foreground">{totalDerivedEdges}</dd>
                </div>
              </dl>

              <div className="space-y-2">
                <div className="text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground">
                  {t('timeline.summary.sourceMix')}
                </div>
                <div className="flex flex-wrap gap-2">
                  {sourceBreakdown.length > 0 ? (
                    sourceBreakdown.map((entry) => (
                      <Badge key={entry.source} variant="secondary" className="rounded-full px-2.5 py-1 text-xs">
                        {getSourceLabel(entry.source)} · {entry.count}
                      </Badge>
                    ))
                  ) : (
                    <span className="text-sm text-muted-foreground">{t('timeline.summary.noSources')}</span>
                  )}
                </div>
              </div>
            </section>

            <TimelineComposer submitting={submitting} onSubmit={handleManualEntrySubmit} />
          </div>
        </aside>
      </div>
    </div>
  );
};

export default TimelinePage;
