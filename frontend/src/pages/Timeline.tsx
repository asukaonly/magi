import React, { startTransition, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';

import {
  timelineApi,
  type TimelineContextBundle,
  type TimelineViewportResponse,
} from '@/api/modules/timeline';
import { memoryApi, type EpisodeAnnotationPayload, type L2Assertion, type L2Episode } from '@/api/modules/memory';
import TimelineContextDrawer from '@/components/timeline/TimelineContextDrawer';
import TimelineToolbar from '@/components/timeline/TimelineToolbar';
import TimelineViewport from '@/components/timeline/TimelineViewport';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { useChatShellStore } from '@/stores';

type TimelineScale = 'month' | 'week' | 'day' | 'hour';

const WEEK_SECONDS = 7 * 24 * 60 * 60;

const padNumber = (value: number): string => String(value).padStart(2, '0');

const toUnixSeconds = (date: Date): number => Math.floor(date.getTime() / 1000);

const startOfLocalHour = (date: Date): Date => new Date(date.getFullYear(), date.getMonth(), date.getDate(), date.getHours());
const startOfLocalDay = (date: Date): Date => new Date(date.getFullYear(), date.getMonth(), date.getDate());
const startOfLocalMonth = (date: Date): Date => new Date(date.getFullYear(), date.getMonth(), 1);

const startOfLocalWeek = (date: Date): Date => {
  const dayStart = startOfLocalDay(date);
  const mondayOffset = (dayStart.getDay() + 6) % 7;
  dayStart.setDate(dayStart.getDate() - mondayOffset);
  return dayStart;
};

const shiftPeriodDate = (scale: TimelineScale, start: Date, amount: number): Date => {
  const next = new Date(start);
  if (scale === 'month') next.setMonth(next.getMonth() + amount);
  if (scale === 'week') next.setDate(next.getDate() + amount * 7);
  if (scale === 'day') next.setDate(next.getDate() + amount);
  if (scale === 'hour') next.setHours(next.getHours() + amount);
  return next;
};

const getLatestCompletePeriodStart = (scale: TimelineScale, now = new Date()): number => {
  if (scale === 'month') return toUnixSeconds(shiftPeriodDate(scale, startOfLocalMonth(now), -1));
  if (scale === 'week') return toUnixSeconds(shiftPeriodDate(scale, startOfLocalWeek(now), -1));
  if (scale === 'day') return toUnixSeconds(shiftPeriodDate(scale, startOfLocalDay(now), -1));
  return toUnixSeconds(shiftPeriodDate(scale, startOfLocalHour(now), -1));
};

const getPeriodEnd = (scale: TimelineScale, start: number): number =>
  toUnixSeconds(shiftPeriodDate(scale, new Date(start * 1000), 1));

const shiftPeriodStart = (scale: TimelineScale, start: number, amount: number): number =>
  toUnixSeconds(shiftPeriodDate(scale, new Date(start * 1000), amount));

const clampToLatestCompletePeriod = (scale: TimelineScale, start: number): number =>
  Math.min(start, getLatestCompletePeriodStart(scale));

const isoWeekStart = (isoYear: number, isoWeek: number): Date => {
  const januaryFourth = new Date(isoYear, 0, 4);
  const firstWeekStart = startOfLocalWeek(januaryFourth);
  firstWeekStart.setDate(firstWeekStart.getDate() + (isoWeek - 1) * 7);
  return firstWeekStart;
};

const isoWeekValue = (date: Date): string => {
  const weekStart = startOfLocalWeek(date);
  const thursday = new Date(weekStart);
  thursday.setDate(thursday.getDate() + 3);
  const isoYear = thursday.getFullYear();
  const firstWeekStart = startOfLocalWeek(new Date(isoYear, 0, 4));
  const week = Math.round((weekStart.getTime() - firstWeekStart.getTime()) / (WEEK_SECONDS * 1000)) + 1;
  return `${isoYear}-W${padNumber(week)}`;
};

const periodInputType = (scale: TimelineScale): 'month' | 'week' | 'date' | 'datetime-local' => {
  if (scale === 'month') return 'month';
  if (scale === 'week') return 'week';
  if (scale === 'hour') return 'datetime-local';
  return 'date';
};

const periodInputValue = (scale: TimelineScale, start: number): string => {
  const date = new Date(start * 1000);
  const datePart = `${date.getFullYear()}-${padNumber(date.getMonth() + 1)}-${padNumber(date.getDate())}`;
  if (scale === 'month') return `${date.getFullYear()}-${padNumber(date.getMonth() + 1)}`;
  if (scale === 'week') return isoWeekValue(date);
  if (scale === 'hour') return `${datePart}T${padNumber(date.getHours())}:00`;
  return datePart;
};

const parsePeriodInputValue = (scale: TimelineScale, value: string): number | null => {
  if (!value) return null;
  if (scale === 'month') {
    const match = /^(\d{4})-(\d{2})$/.exec(value);
    if (!match) return null;
    return toUnixSeconds(new Date(Number(match[1]), Number(match[2]) - 1, 1));
  }
  if (scale === 'week') {
    const match = /^(\d{4})-W(\d{2})$/.exec(value);
    if (!match) return null;
    return toUnixSeconds(isoWeekStart(Number(match[1]), Number(match[2])));
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  if (scale === 'day') return toUnixSeconds(startOfLocalDay(parsed));
  return toUnixSeconds(startOfLocalHour(parsed));
};

const formatWindowLabel = (scale: TimelineScale, start: number, end: number, locale: string): string => {
  const s = new Date(start * 1000);
  if (scale === 'month') {
    return s.toLocaleDateString(locale, { year: 'numeric', month: 'long' });
  }
  if (scale === 'day') {
    return s.toLocaleDateString(locale, { year: 'numeric', month: 'short', day: 'numeric', weekday: 'short' });
  }
  if (scale === 'hour') {
    const e = new Date(end * 1000);
    const day = s.toLocaleDateString(locale, { month: 'short', day: 'numeric' });
    const startTime = s.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit', hour12: false });
    const endTime = e.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit', hour12: false });
    return `${day} ${startTime}–${endTime}`;
  }
  const e = new Date(Math.max(start, end - 1) * 1000);
  const opts: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric' };
  const sf = s.toLocaleDateString(locale, opts);
  const ef = e.toLocaleDateString(locale, opts);
  return sf === ef ? sf : `${sf} – ${ef}`;
};

export const TimelinePage: React.FC = () => {
  const { t, i18n } = useTranslation('app');
  const timelineLocale = i18n.resolvedLanguage || i18n.language || 'en';
  const setActivePanel = useChatShellStore((state) => state.setActivePanel);
  const [scale, setScale] = useState<TimelineScale>('month');
  const [viewportStart, setViewportStart] = useState<number>(() => getLatestCompletePeriodStart('month'));
  const [viewport, setViewport] = useState<TimelineViewportResponse | null>(null);
  const [query, setQuery] = useState('');
  const [draftQuery, setDraftQuery] = useState('');
  const [selectedAnchorId, setSelectedAnchorId] = useState<string | null>(null);
  const [contextBundle, setContextBundle] = useState<TimelineContextBundle | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadingContext, setLoadingContext] = useState(false);
  const [feedbackPendingId, setFeedbackPendingId] = useState<string | null>(null);
  const [correctionPendingId, setCorrectionPendingId] = useState<string | null>(null);
  const [episodeAnnotationPendingId, setEpisodeAnnotationPendingId] = useState<string | null>(null);

  const viewportEnd = getPeriodEnd(scale, viewportStart);
  const latestPeriodStart = getLatestCompletePeriodStart(scale);
  const nextPeriodStart = shiftPeriodStart(scale, viewportStart, 1);
  const canGoNext = nextPeriodStart <= latestPeriodStart;

  const loadViewport = async (mode: 'initial' | 'refresh' = 'initial') => {
    if (mode === 'initial') {
      setLoading(true);
    } else {
      setRefreshing(true);
    }
    try {
      const response = await timelineApi.getViewport({
        scale,
        start: viewportStart,
        end: viewportEnd,
        query: query || undefined,
        locale: timelineLocale,
        focus: 'self',
      });
      setViewport(response);
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
    void loadViewport('initial');
  }, [scale, viewportStart, query, timelineLocale]);

  const handleOpenContext = async (anchorId: string) => {
    setSelectedAnchorId(anchorId);
    setLoadingContext(true);
    try {
      const bundle = await timelineApi.getContext(anchorId);
      setContextBundle(bundle);
    } catch (error: any) {
      toast.error(t('timeline.errors.detailFailed', { message: error?.message || 'unknown' }));
    } finally {
      setLoadingContext(false);
    }
  };

  const handleAssertionFeedback = async (assertionId: string, feedback: 'confirmed' | 'rejected') => {
    setFeedbackPendingId(assertionId);
    try {
      const updated = await memoryApi.submitAssertionFeedback(assertionId, feedback);
      setContextBundle((current) => mergeAssertionEvidence(current, assertionId, updated));
      toast.success(t(feedback === 'confirmed' ? 'timeline.feedback.confirmed' : 'timeline.feedback.rejected'));
      await loadViewport('refresh');
    } catch (error: any) {
      toast.error(t('timeline.errors.feedbackFailed', { message: error?.message || 'unknown' }));
    } finally {
      setFeedbackPendingId(null);
    }
  };

  const handleAssertionCorrection = async (assertionId: string, newValue: string) => {
    setCorrectionPendingId(assertionId);
    try {
      const updated = await memoryApi.correctAssertion(assertionId, newValue);
      setContextBundle((current) => mergeAssertionEvidence(current, assertionId, updated));
      toast.success(t('timeline.feedback.corrected'));
      await loadViewport('refresh');
    } catch (error: any) {
      toast.error(t('timeline.errors.feedbackFailed', { message: error?.message || 'unknown' }));
      throw error;
    } finally {
      setCorrectionPendingId(null);
    }
  };

  const handleEpisodeAnnotation = async (episodeId: string, payload: EpisodeAnnotationPayload) => {
    setEpisodeAnnotationPendingId(episodeId);
    try {
      const updated = await memoryApi.annotateEpisode(episodeId, payload);
      setViewport((current) => mergeEpisodeAnnotation(current, updated));
      toast.success(t('timeline.episode.annotationSaved'));
      await loadViewport('refresh');
    } catch (error: any) {
      toast.error(t('timeline.errors.feedbackFailed', { message: error?.message || 'unknown' }));
      throw error;
    } finally {
      setEpisodeAnnotationPendingId(null);
    }
  };

  const handleHideEpisode = async (episodeId: string) => {
    setEpisodeAnnotationPendingId(episodeId);
    try {
      await memoryApi.forgetEpisode(episodeId, false);
      setViewport((current) => removeEpisodeFromViewport(current, episodeId));
      toast.success(t('timeline.episode.hidden'));
      await loadViewport('refresh');
    } catch (error: any) {
      toast.error(t('timeline.errors.feedbackFailed', { message: error?.message || 'unknown' }));
      throw error;
    } finally {
      setEpisodeAnnotationPendingId(null);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-background">
      {/* Header */}
      <header className="shrink-0 border-b border-border/40 px-6 py-3">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-baseline gap-3">
            <h1 className="text-lg font-semibold text-foreground">{t('timeline.title')}</h1>
            <span className="hidden text-sm text-muted-foreground/60 sm:inline">
              {formatWindowLabel(scale, viewportStart, viewportEnd, timelineLocale)}
            </span>
          </div>
          <TimelineToolbar
            scale={scale}
            draftQuery={draftQuery}
            periodInputType={periodInputType(scale)}
            periodInputValue={periodInputValue(scale, viewportStart)}
            periodInputMax={periodInputValue(scale, latestPeriodStart)}
            canGoNext={canGoNext}
            refreshing={refreshing}
            onDraftQueryChange={setDraftQuery}
            onSubmitQuery={() => setQuery(draftQuery.trim())}
            onPeriodInputChange={(value) => {
              const parsed = parsePeriodInputValue(scale, value);
              if (parsed == null) return;
              startTransition(() => {
                setViewportStart(clampToLatestCompletePeriod(scale, parsed));
              });
            }}
            onScaleChange={(item) => {
              startTransition(() => {
                setScale(item);
                setViewportStart(getLatestCompletePeriodStart(item));
              });
            }}
            onPrevious={() => setViewportStart((v) => shiftPeriodStart(scale, v, -1))}
            onNext={() => setViewportStart((v) => clampToLatestCompletePeriod(scale, shiftPeriodStart(scale, v, 1)))}
            onRefresh={() => void loadViewport('refresh')}
          />
        </div>
      </header>

      {/* Main content */}
      <div className="grid min-h-0 flex-1 grid-cols-1 xl:grid-cols-[minmax(0,1fr)_340px]">
        <section className="min-h-0 overflow-y-auto px-6 py-5 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent">
          {loading ? (
            <div className="flex min-h-[200px] items-center justify-center gap-2 text-sm text-muted-foreground">
              <LoadingSpinner className="h-4 w-4" />
              {t('timeline.loading')}
            </div>
          ) : viewport ? (
            <TimelineViewport
              scale={scale}
              viewport={viewport}
              episodeAnnotationPendingId={episodeAnnotationPendingId}
              onOpenContext={(anchorId) => void handleOpenContext(anchorId)}
              onAnnotateEpisode={(episodeId, payload) => handleEpisodeAnnotation(episodeId, payload)}
              onHideEpisode={(episodeId) => handleHideEpisode(episodeId)}
            />
          ) : null}
        </section>

        <TimelineContextDrawer
          selectedAnchorId={selectedAnchorId}
          loading={loadingContext}
          contextBundle={contextBundle}
          feedbackPendingId={feedbackPendingId}
          correctionPendingId={correctionPendingId}
          onAssertionFeedback={(assertionId, feedback) => void handleAssertionFeedback(assertionId, feedback)}
          onAssertionCorrection={(assertionId, newValue) => handleAssertionCorrection(assertionId, newValue)}
          onClose={() => setSelectedAnchorId(null)}
        />
      </div>
    </div>
  );
};

const mergeEpisodeAnnotation = (
  viewport: TimelineViewportResponse | null,
  episode: L2Episode
): TimelineViewportResponse | null => {
  if (!viewport) return viewport;
  return {
    ...viewport,
    clusters: viewport.clusters.map((cluster) => {
      if (cluster.episode_id !== episode.episode_id) {
        return cluster;
      }
      return {
        ...cluster,
        label: episode.user_label || episode.label || cluster.label,
        summary: episode.summary || cluster.summary,
        user_label: episode.user_label ?? null,
        user_note: episode.user_note ?? null,
        user_pinned: Boolean(episode.user_pinned),
      };
    }),
  };
};

const removeEpisodeFromViewport = (
  viewport: TimelineViewportResponse | null,
  episodeId: string
): TimelineViewportResponse | null => {
  if (!viewport) return viewport;
  const clusters = viewport.clusters.filter((cluster) => cluster.episode_id !== episodeId);
  return {
    ...viewport,
    clusters,
    summary: {
      ...viewport.summary,
      cluster_count: clusters.length,
    },
  };
};

const mergeAssertionEvidence = (
  bundle: TimelineContextBundle | null,
  targetAssertionId: string,
  updated: L2Assertion
): TimelineContextBundle | null => {
  if (!bundle) return bundle;
  return {
    ...bundle,
    l2_state_evidence: bundle.l2_state_evidence.map((item) => {
      const record = item as Record<string, unknown>;
      if (record.assertion_id !== targetAssertionId && record.assertion_id !== updated.assertion_id) {
        return item;
      }
      return { ...record, ...updated };
    }),
  };
};

export default TimelinePage;
