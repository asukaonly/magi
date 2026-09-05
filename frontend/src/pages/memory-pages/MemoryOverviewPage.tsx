import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import MemoryCorrectionDialog from '@/components/memory/correction/MemoryCorrectionDialog';
import type { MemoryCorrectionUiTarget } from '@/components/memory/correction/memoryCorrectionModel';
import {
  memoryApi,
  type L2PendingReview,
  type MemoryDashboard,
} from '@/api/modules/memory';
import { sensorsApi, type SensorSourceStatusResponse } from '@/api/modules/sensors';
import { memoryStoriesApi, type StoryItem } from '@/api/modules/memoryStories';
import MemoryPageFrame, { MEMORY_EMPTY_PANEL_CLASS } from './MemoryPageFrame';
import { OverviewEmptyState } from './overview/OverviewEmptyState';
import { OverviewPendingSection } from './overview/OverviewPendingSection';
import { OverviewRecentStories } from './overview/OverviewRecentStories';
import { OverviewSourceCoverage } from './overview/OverviewSourceCoverage';
import { OverviewSummary } from './overview/OverviewSummary';
import { PendingMemoryReviewEditDialog } from './pending/PendingMemoryReviewEditDialog';
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
  const [reviews, setReviews] = useState<L2PendingReview[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dismissedIds, setDismissedIds] = useState<Set<string>>(() => new Set());
  const [actionBusyId, setActionBusyId] = useState<string | null>(null);
  const [correctionTarget, setCorrectionTarget] = useState<MemoryCorrectionUiTarget | null>(null);
  const [editingReview, setEditingReview] = useState<L2PendingReview | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const [reviewPayload, dashboardPayload, sensorPayload, storyPayload] = await Promise.all([
          memoryApi.listPendingReviews(8),
          memoryApi.getDashboard({ pending_limit: 8 }),
          sensorsApi.getStatus(),
          memoryStoriesApi.list({ limit: 12, offset: 0, surface: 'all' }),
        ]);
        if (cancelled) {
          return;
        }
        setReviews(reviewPayload.items || []);
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
  }, [reloadToken]);

  const sourceRows = useMemo(
    () => buildSourceRows(dashboard?.source_counts || [], sensorStatus, t),
    [dashboard?.source_counts, sensorStatus, t],
  );
  const pendingItems = useMemo(
    () => buildPendingItems(dashboard, stories, reviews, dismissedIds, t),
    [dashboard, stories, reviews, dismissedIds, t],
  );
  const recentStories = useMemo(
    () => buildRecentStories(stories, t),
    [stories, t],
  );
  const hasOverviewContent = (
    (dashboard?.statistics.stored_records ?? 0) > 0
    || sourceRows.length > 0
    || pendingItems.length > 0
    || recentStories.length > 0
  );

  const dismissItem = (id: string) => {
    setDismissedIds((current) => new Set([...current, id]));
  };

  const handlePendingAction = async (
    item: PendingOverviewItem,
    action: 'confirmed' | 'rejected' | 'edit',
  ) => {
    if (item.kind === 'review' && action === 'edit') {
      setEditingReview(item.payload);
      return;
    }
    if (action === 'edit') return;
    if (item.kind === 'assertion' && action === 'rejected') {
      setCorrectionTarget({
        kind: 'assertion',
        id: item.payload.assertion_id,
        displaySentence: item.title,
        editableValue: item.payload.trait_value,
        expectedUpdatedAt: item.payload.updated_at ?? undefined,
      });
      return;
    }
    setActionBusyId(item.id);
    try {
      if (item.kind === 'review') {
        await memoryApi.resolvePendingReview(item.payload.review_id, {
          action: action === 'confirmed' ? 'confirm' : 'reject',
          expected_version: item.payload.version,
        });
      } else if (item.kind === 'assertion') {
        await memoryApi.submitAssertionFeedback(item.payload.assertion_id, 'confirmed');
      } else {
        await memoryStoriesApi.review(item.payload.summary_id, { review_state: action });
      }
      dismissItem(item.id);
    } finally {
      setActionBusyId(null);
    }
  };

  const handleReviewEdit = async (edit: { trait_value: string; natural_summary?: string }) => {
    if (!editingReview) return;
    const review = editingReview;
    const id = `review:${review.review_id}`;
    setActionBusyId(id);
    try {
      await memoryApi.resolvePendingReview(review.review_id, {
        action: 'confirm_with_edit',
        expected_version: review.version,
        edit,
      });
      dismissItem(id);
      setEditingReview(null);
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
      <MemoryCorrectionDialog
        open={correctionTarget !== null}
        target={correctionTarget}
        initialRecordErrorAction="remove"
        onOpenChange={(open) => {
          if (!open) setCorrectionTarget(null);
        }}
        onSaved={() => setReloadToken((current) => current + 1)}
        onConflict={() => setReloadToken((current) => current + 1)}
      />
      <PendingMemoryReviewEditDialog
        review={editingReview}
        busy={Boolean(editingReview && actionBusyId === `review:${editingReview.review_id}`)}
        onOpenChange={(open) => {
          if (!open && !actionBusyId) setEditingReview(null);
        }}
        onSubmit={handleReviewEdit}
      />
    </MemoryPageFrame>
  );
};

export default MemoryOverviewPage;
