import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { memoryApi, type MemoryDashboard } from '@/api/modules/memory';
import { sensorsApi, type SensorSourceStatusResponse } from '@/api/modules/sensors';
import { memoryStoriesApi, type StoryItem } from '@/api/modules/memoryStories';
import MemoryPageFrame, { MEMORY_EMPTY_PANEL_CLASS } from './MemoryPageFrame';
import { OverviewEmptyState } from './overview/OverviewEmptyState';
import { OverviewPendingSection } from './overview/OverviewPendingSection';
import { OverviewRecentStories } from './overview/OverviewRecentStories';
import { OverviewSourceCoverage } from './overview/OverviewSourceCoverage';
import { OverviewSummary } from './overview/OverviewSummary';
import {
  buildPendingItems,
  buildRecentStories,
  buildSourceRows,
  type PendingOverviewItem,
} from './overview/overviewModel';

export const MemoryOverviewPage = () => {
  const { t } = useTranslation('app');
  const [dashboard, setDashboard] = useState<MemoryDashboard | null>(null);
  const [sensorStatus, setSensorStatus] = useState<SensorSourceStatusResponse | null>(null);
  const [stories, setStories] = useState<StoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dismissedIds, setDismissedIds] = useState<Set<string>>(() => new Set());
  const [actionBusyId, setActionBusyId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const [dashboardPayload, sensorPayload, storyPayload] = await Promise.all([
          memoryApi.getDashboard({ pending_limit: 8 }),
          sensorsApi.getStatus(),
          memoryStoriesApi.list({ limit: 12, offset: 0, surface: 'all' }),
        ]);
        if (cancelled) {
          return;
        }
        setDashboard(dashboardPayload);
        setSensorStatus(sensorPayload);
        setStories(storyPayload.items || []);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const sourceRows = useMemo(
    () => buildSourceRows(dashboard?.source_counts || [], sensorStatus, t),
    [dashboard?.source_counts, sensorStatus, t],
  );
  const pendingItems = useMemo(
    () => buildPendingItems(dashboard, stories, dismissedIds, t),
    [dashboard, stories, dismissedIds, t],
  );
  const recentStories = useMemo(
    () => buildRecentStories(stories, t),
    [stories, t],
  );
  const hasOverviewContent = (
    (dashboard?.statistics.total_memories ?? 0) > 0
    || sourceRows.length > 0
    || pendingItems.length > 0
    || recentStories.length > 0
  );

  const dismissItem = (id: string) => {
    setDismissedIds((current) => new Set([...current, id]));
  };

  const handlePendingAction = async (item: PendingOverviewItem, action: 'confirmed' | 'rejected') => {
    setActionBusyId(item.id);
    try {
      if (item.kind === 'assertion') {
        await memoryApi.submitAssertionFeedback(item.payload.assertion_id, action);
      } else {
        await memoryStoriesApi.review(item.payload.summary_id, { review_state: action });
      }
      dismissItem(item.id);
    } finally {
      setActionBusyId(null);
    }
  };

  return (
    <MemoryPageFrame title={t('memory.overview.title')} description={t('memory.overview.subtitle')} hideHeader>
      {loading ? (
        <section className={MEMORY_EMPTY_PANEL_CLASS}>
          <div className="flex items-center gap-2">
            <LoadingSpinner className="h-4 w-4" />
            <span>{t('memory.overview.empty.loading')}</span>
          </div>
        </section>
      ) : error ? (
        <section className={MEMORY_EMPTY_PANEL_CLASS}>{t('memory.overview.empty.error')}</section>
      ) : !hasOverviewContent ? (
        <OverviewEmptyState diskUsageBytes={dashboard?.statistics.disk_usage_bytes} />
      ) : (
        <div className="space-y-6">
          <OverviewSummary dashboard={dashboard} sourceCount={sourceRows.length} />
          <OverviewSourceCoverage
            rows={sourceRows}
            processingBacklog={dashboard?.processing_backlog?.total_pending ?? 0}
          />
          {pendingItems.length > 0 ? (
            <OverviewPendingSection
              items={pendingItems}
              actionBusyId={actionBusyId}
              onAction={handlePendingAction}
            />
          ) : null}
          {recentStories.length > 0 ? <OverviewRecentStories stories={recentStories} /> : null}
        </div>
      )}
    </MemoryPageFrame>
  );
};

export default MemoryOverviewPage;
