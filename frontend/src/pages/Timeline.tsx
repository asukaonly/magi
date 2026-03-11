import React, { useEffect, useState } from 'react';
import { CalendarRange, Filter, LayoutList, RefreshCw, ScrollText, Sparkles } from 'lucide-react';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';

import { timelineApi, type TimelineEventDetail, type TimelineEventRecord, type TimelineManualEntryRequest } from '@/api/modules/timeline';
import TimelineComposer from '@/components/timeline/TimelineComposer';
import TimelineFeed from '@/components/timeline/TimelineFeed';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
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
        sortEvents(
          current.map((event) => (event.event_id === eventId ? { ...event, ...nextDetail } : event))
        )
      );
      toast.success(t('timeline.feed.reanalyzeQueued'));
    } catch (error: any) {
      toast.error(t('timeline.errors.reanalyzeFailed', { message: error?.message || 'unknown' }));
    } finally {
      setReanalyzingEventId(null);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-[radial-gradient(circle_at_top_left,_rgba(245,158,11,0.08),_transparent_32%),radial-gradient(circle_at_top_right,_rgba(14,165,233,0.08),_transparent_28%)]">
      <div className="border-b border-border/30 px-6 py-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/5 px-3 py-1 text-xs text-primary">
              <Sparkles className="h-3.5 w-3.5" />
              {t('timeline.hero.eyebrow')}
            </div>
            <h1 className="mt-3 text-3xl font-semibold tracking-tight text-foreground">{t('timeline.title')}</h1>
            <p className="mt-2 max-w-3xl text-sm leading-7 text-muted-foreground">{t('timeline.subtitle')}</p>
          </div>
          <Button variant="outline" onClick={() => void loadEvents('refresh')} disabled={refreshing} aria-label={t('timeline.actions.refresh')}>
            <RefreshCw className={refreshing ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} />
            {t('timeline.actions.refresh')}
          </Button>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 gap-6 overflow-hidden px-6 py-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <section className="flex min-h-0 flex-col overflow-hidden">
          <Card className="border-border/35 bg-card/70 shadow-sm">
            <CardContent className="flex flex-wrap items-end gap-3 p-5">
              <label className="min-w-[180px] flex-1 space-y-2" htmlFor="timeline-source-filter">
                <span className="inline-flex items-center gap-2 text-sm font-medium text-foreground">
                  <Filter className="h-4 w-4 text-primary" />
                  {t('timeline.filters.source')}
                </span>
                <select
                  id="timeline-source-filter"
                  className="h-10 w-full rounded-xl border border-input bg-background px-3 text-sm"
                  value={selectedSource}
                  onChange={(event) => setSelectedSource(event.target.value)}
                >
                  <option value="all">{t('timeline.filters.allSources')}</option>
                  {sourceOptions.filter((source) => source !== 'all').map((source) => (
                    <option key={source} value={source}>
                      {t(`timeline.sources.${source}`)}
                    </option>
                  ))}
                </select>
              </label>

              <label className="min-w-[160px] flex-1 space-y-2" htmlFor="timeline-range-filter">
                <span className="inline-flex items-center gap-2 text-sm font-medium text-foreground">
                  <CalendarRange className="h-4 w-4 text-primary" />
                  {t('timeline.filters.range')}
                </span>
                <select
                  id="timeline-range-filter"
                  className="h-10 w-full rounded-xl border border-input bg-background px-3 text-sm"
                  value={selectedRange}
                  onChange={(event) => setSelectedRange(event.target.value as RangeOption)}
                >
                  <option value="all">{t('timeline.filters.allTime')}</option>
                  <option value="7d">{t('timeline.filters.last7Days')}</option>
                  <option value="30d">{t('timeline.filters.last30Days')}</option>
                </select>
              </label>

              <label className="min-w-[160px] flex-1 space-y-2" htmlFor="timeline-view-mode">
                <span className="inline-flex items-center gap-2 text-sm font-medium text-foreground">
                  <LayoutList className="h-4 w-4 text-primary" />
                  {t('timeline.filters.viewMode')}
                </span>
                <select
                  id="timeline-view-mode"
                  className="h-10 w-full rounded-xl border border-input bg-background px-3 text-sm"
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
                onClick={() => {
                  setSelectedSource('all');
                  setSelectedRange('all');
                  setViewMode('comfortable');
                }}
                aria-label={t('timeline.filters.clear')}
              >
                {t('timeline.filters.clear')}
              </Button>
            </CardContent>
          </Card>

          <div className="mt-5 min-h-0 flex-1 overflow-y-auto pr-1 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent">
            {loading ? (
              <div className="flex h-full min-h-[280px] items-center justify-center gap-3 text-sm text-muted-foreground">
                <LoadingSpinner className="h-5 w-5" />
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

        <aside className="min-h-0 overflow-y-auto pr-1 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent">
          <div className="space-y-5">
            <Card className="border-border/35 bg-card/75 shadow-sm">
              <CardHeader className="pb-4">
                <CardTitle>{t('timeline.summary.title')}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-2xl border border-border/40 bg-background/70 p-4">
                    <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">{t('timeline.summary.totalEvents')}</p>
                    <p className="mt-2 text-2xl font-semibold text-foreground">{events.length}</p>
                  </div>
                  <div className="rounded-2xl border border-border/40 bg-background/70 p-4">
                    <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">{t('timeline.summary.derivedEdges')}</p>
                    <p className="mt-2 text-2xl font-semibold text-foreground">{totalDerivedEdges}</p>
                  </div>
                </div>

                <div>
                  <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">{t('timeline.summary.sourceMix')}</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {sourceBreakdown.length > 0 ? sourceBreakdown.map((entry) => (
                      <Badge key={entry.source} variant="secondary" className="rounded-full px-3 py-1">
                        {t(`timeline.sources.${entry.source}`)} · {entry.count}
                      </Badge>
                    )) : (
                      <span className="text-sm text-muted-foreground">{t('timeline.summary.noSources')}</span>
                    )}
                  </div>
                </div>

                <div className="rounded-3xl border border-border/40 bg-background/75 p-4">
                  <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                    <ScrollText className="h-4 w-4 text-primary" />
                    {t('timeline.summary.feedState')}
                  </div>
                  <p className="mt-2 text-sm leading-7 text-muted-foreground">
                    {filteredEvents.length === events.length
                      ? t('timeline.summary.showingAll')
                      : t('timeline.summary.showingFiltered', { count: filteredEvents.length })}
                  </p>
                </div>
              </CardContent>
            </Card>

            <TimelineComposer submitting={submitting} onSubmit={handleManualEntrySubmit} />
          </div>
        </aside>
      </div>
    </div>
  );
};

export default TimelinePage;
