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

const windowSecondsByScale: Record<TimelineScale, number> = {
  month: 30 * 24 * 60 * 60,
  week: 7 * 24 * 60 * 60,
  day: 24 * 60 * 60,
  hour: 60 * 60,
};

const formatWindowLabel = (start: number, end: number): string => {
  const s = new Date(start * 1000);
  const e = new Date(end * 1000);
  const opts: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric' };
  const sf = s.toLocaleDateString(undefined, opts);
  const ef = e.toLocaleDateString(undefined, opts);
  return sf === ef ? sf : `${sf} – ${ef}`;
};

export const TimelinePage: React.FC = () => {
  const { t, i18n } = useTranslation('app');
  const setActivePanel = useChatShellStore((state) => state.setActivePanel);
  const [scale, setScale] = useState<TimelineScale>('month');
  const [viewportStart, setViewportStart] = useState<number>(() => Math.floor(Date.now() / 1000) - windowSecondsByScale.month);
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

  const viewportEnd = viewportStart + windowSecondsByScale[scale];

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
        locale: i18n.language,
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
  }, [scale, viewportStart, query]);

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
              {formatWindowLabel(viewportStart, viewportEnd)}
            </span>
          </div>
          <TimelineToolbar
            scale={scale}
            draftQuery={draftQuery}
            refreshing={refreshing}
            onDraftQueryChange={setDraftQuery}
            onSubmitQuery={() => setQuery(draftQuery.trim())}
            onScaleChange={(item) => {
              startTransition(() => {
                setScale(item);
                setViewportStart(Math.floor(Date.now() / 1000) - windowSecondsByScale[item]);
              });
            }}
            onPrevious={() => setViewportStart((v) => v - windowSecondsByScale[scale])}
            onNext={() => setViewportStart((v) => v + windowSecondsByScale[scale])}
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
