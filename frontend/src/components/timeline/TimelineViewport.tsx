import React, { useMemo } from 'react';
import { useTranslation } from 'react-i18next';

import type { TimelineViewportResponse } from '@/api/modules/timeline';
import DayClusterLane from '@/components/timeline/DayClusterLane';
import HourDetailLane from '@/components/timeline/HourDetailLane';
import MonthOverviewLane from '@/components/timeline/MonthOverviewLane';
import StateBandOverlay from '@/components/timeline/StateBandOverlay';

interface TimelineViewportProps {
  scale: 'month' | 'week' | 'day' | 'hour';
  viewport: TimelineViewportResponse;
  onOpenContext: (anchorId: string) => void;
}

const hasViewportContent = (viewport: TimelineViewportResponse): boolean =>
  viewport.summary.event_count > 0
  || viewport.clusters.length > 0
  || viewport.reflections.length > 0
  || viewport.raw_events.length > 0
  || viewport.state_bands.length > 0
  || viewport.state_markers.length > 0;

const buildOverview = (
  viewport: TimelineViewportResponse,
  scale: TimelineViewportProps['scale'],
  t: (key: string, params?: Record<string, unknown>) => string,
) => {
  const topReflection = viewport.reflections[0];
  const topCluster = [...viewport.clusters].sort((a, b) => b.event_count - a.event_count)[0];
  const topEvent = viewport.raw_events[0];
  const title = t(`timeline.overview.${scale}`);

  const summary = topReflection
    ? t('timeline.overview.reflectionSummary', { count: viewport.reflections.length })
    : topCluster?.summary
    || topEvent?.summary
    || t('timeline.overview.fallback');

  const takeaways = [
    viewport.summary.dominant_modes[0]
      ? t('timeline.overview.primaryMode', { mode: viewport.summary.dominant_modes[0] })
      : null,
    viewport.state_markers[0]?.summary || null,
    viewport.summary.event_count > 0
      ? t('timeline.overview.eventCount', { count: viewport.summary.event_count })
      : null,
  ].filter(Boolean) as string[];

  return { title, summary, takeaways: takeaways.slice(0, 3) };
};

const EmptyViewport: React.FC = () => {
  const { t } = useTranslation('app');

  return (
    <div className="rounded-lg border border-dashed border-border/60 px-5 py-8 text-sm text-muted-foreground">
      <h2 className="text-base font-medium text-foreground">{t('timeline.feed.emptyTitle')}</h2>
      <p className="mt-2 max-w-2xl leading-relaxed">{t('timeline.feed.emptyBody')}</p>
    </div>
  );
};

export const TimelineViewport: React.FC<TimelineViewportProps> = ({ scale, viewport, onOpenContext }) => {
  const { t } = useTranslation('app');

  const overview = useMemo(
    () => buildOverview(viewport, scale, t),
    [scale, t, viewport],
  );

  if (!hasViewportContent(viewport)) {
    return <EmptyViewport />;
  }

  return (
    <div className="space-y-6">
      <section className="space-y-3 border-b border-border/40 pb-5">
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span className="font-medium text-foreground">{overview.title}</span>
            <span>
              <span className="font-medium tabular-nums text-foreground">{viewport.summary.event_count}</span>{' '}
              {t('timeline.summary.totalEvents')}
            </span>
            <span>
              <span className="font-medium tabular-nums text-foreground">{viewport.summary.cluster_count}</span>{' '}
              {t('timeline.summary.clusterCount')}
            </span>
          </div>
          <p className="max-w-4xl text-sm leading-7 text-muted-foreground">
            {overview.summary}
          </p>
        </div>
        {overview.takeaways.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {overview.takeaways.map((takeaway) => (
              <span key={takeaway} className="rounded-md bg-secondary/70 px-2 py-1 text-xs text-secondary-foreground">
                {takeaway}
              </span>
            ))}
          </div>
        )}
      </section>

      <StateBandOverlay bands={viewport.state_bands} markers={viewport.state_markers} scale={scale} />

      {scale === 'month' && (
        <MonthOverviewLane
          reflections={viewport.reflections}
          stateBands={viewport.state_bands}
          clusters={viewport.clusters}
          sourceMix={viewport.source_mix}
        />
      )}
      {(scale === 'week' || scale === 'day') && (
        <section className="space-y-3">
          <h3 className="text-xs font-medium text-muted-foreground">
            {t(scale === 'week' ? 'timeline.week.periods' : 'timeline.day.periods')}
          </h3>
          {viewport.clusters.length > 0 ? (
            <DayClusterLane scale={scale} clusters={viewport.clusters} onOpenContext={onOpenContext} />
          ) : (
            <div className="rounded-lg border border-dashed border-border/60 px-4 py-6 text-sm text-muted-foreground">
              {t('timeline.empty.window')}
            </div>
          )}
        </section>
      )}
      {scale === 'hour' && (
        viewport.raw_events.length > 0 ? (
          <HourDetailLane rawEvents={viewport.raw_events} />
        ) : (
          <div className="rounded-lg border border-dashed border-border/60 px-4 py-6 text-sm text-muted-foreground">
            {t('timeline.empty.window')}
          </div>
        )
      )}
    </div>
  );
};

export default TimelineViewport;
