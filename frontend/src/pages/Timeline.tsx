import React, { startTransition, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';

import {
  timelineApi,
  type TimelineContextBundle,
  type TimelineViewportResponse,
} from '@/api/modules/timeline';
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

export const TimelinePage: React.FC = () => {
  const { t } = useTranslation('app');
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
            onPrevious={() => setViewportStart((value) => value - windowSecondsByScale[scale])}
            onNext={() => setViewportStart((value) => value + windowSecondsByScale[scale])}
            onRefresh={() => void loadViewport('refresh')}
          />
        </div>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-1 xl:grid-cols-[minmax(0,1fr)_360px]">
        <section className="min-h-0 overflow-y-auto px-6 py-5 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent">
          <div className="mt-4 space-y-4">
            {loading ? (
              <div className="flex h-full min-h-[220px] items-center justify-center gap-3 text-sm text-muted-foreground">
                <LoadingSpinner className="h-4 w-4" />
                {t('timeline.loading')}
              </div>
            ) : viewport ? (
              <TimelineViewport scale={scale} viewport={viewport} onOpenContext={(anchorId) => void handleOpenContext(anchorId)} />
            ) : null}
          </div>
        </section>

        <TimelineContextDrawer selectedAnchorId={selectedAnchorId} loading={loadingContext} contextBundle={contextBundle} />
      </div>
    </div>
  );
};

export default TimelinePage;
