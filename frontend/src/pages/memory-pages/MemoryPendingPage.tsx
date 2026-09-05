import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import MemoryCorrectionDialog from '@/components/memory/correction/MemoryCorrectionDialog';
import type { MemoryCorrectionUiTarget } from '@/components/memory/correction/memoryCorrectionModel';
import {
  memoryApi,
  type L2Assertion,
  type L2ExperienceSeed,
  type L2PendingReview,
} from '@/api/modules/memory';
import { memoryStoriesApi, type StoryItem } from '@/api/modules/memoryStories';
import {
  listNotifications,
  resolveConflict,
  type NotificationItem,
} from '@/api/modules/notifications';
import MemoryPageFrame, { MEMORY_EMPTY_PANEL_CLASS } from './MemoryPageFrame';
import { PendingFilterTabs } from './pending/PendingFilterTabs';
import { PendingMemoryReviewEditDialog } from './pending/PendingMemoryReviewEditDialog';
import { PendingReviewGroups } from './pending/PendingReviewGroups';
import {
  buildPendingFilterOptions,
  isCurrentPlanReview,
  isOpenProfileConflict,
  type ConflictAction,
  type PendingAction,
  type PendingFilter,
  type PendingReviewAction,
} from './pending/pendingModel';
import { isMemoryUpdateStory } from './storyFilters';
import { getPendingAssertionCopy } from '@/utils/memory-assertion-copy';

type PendingSection = 'reviews' | 'assertions' | 'stories' | 'seeds' | 'conflicts';

export const MemoryPendingPage = () => {
  const { t } = useTranslation('app');
  const [reviews, setReviews] = useState<L2PendingReview[]>([]);
  const [assertions, setAssertions] = useState<L2Assertion[]>([]);
  const [stories, setStories] = useState<StoryItem[]>([]);
  const [seeds, setSeeds] = useState<L2ExperienceSeed[]>([]);
  const [conflicts, setConflicts] = useState<NotificationItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [failedSections, setFailedSections] = useState<PendingSection[]>([]);
  const [retryingSection, setRetryingSection] = useState<PendingSection | null>(null);
  const loadVersion = useRef(0);
  const requestVersions = useRef<Partial<Record<PendingSection, number>>>({});
  const [actionId, setActionId] = useState<string | null>(null);
  const [activeFilter, setActiveFilter] = useState<PendingFilter>('all');
  const [editingReview, setEditingReview] = useState<L2PendingReview | null>(null);
  const [correctionTarget, setCorrectionTarget] = useState<MemoryCorrectionUiTarget | null>(null);
  const [selectedPlanReviewIds, setSelectedPlanReviewIds] = useState<Set<string>>(new Set());

  const load = useCallback(async (onlySection?: PendingSection) => {
    const version = onlySection ? loadVersion.current : ++loadVersion.current;
    if (onlySection) setRetryingSection(onlySection);
    else setLoading(true);
    const loadSection = async <T,>(section: PendingSection, request: () => Promise<T>, apply: (payload: T) => void) => {
      if (onlySection && onlySection !== section) return;
      const version = (requestVersions.current[section] ?? 0) + 1;
      requestVersions.current[section] = version;
      try {
        const payload = await request();
        if (requestVersions.current[section] !== version) return;
        apply(payload);
        setFailedSections((items) => items.filter((item) => item !== section));
      } catch {
        if (requestVersions.current[section] !== version) return;
        setFailedSections((items) => items.includes(section) ? items : [...items, section]);
      }
    };
    await Promise.all([
      loadSection('reviews', () => memoryApi.listPendingReviews(100), (payload) => setReviews(payload.items || [])),
      loadSection('assertions', () => memoryApi.getDashboard({ pending_limit: 25 }), (payload) => setAssertions(payload.pending_assertions?.items || [])),
      loadSection('stories', () => memoryStoriesApi.list({ limit: 50, offset: 0, surface: 'all' }), (payload) => setStories((payload.items || []).filter((story) => story.review_state === 'pending_confirmation' && isMemoryUpdateStory(story)))),
      loadSection('seeds', () => memoryApi.listExperienceSeeds({ status: 'candidate', limit: 50, offset: 0 }), (payload) => setSeeds(payload.items || [])),
      loadSection('conflicts', () => listNotifications(), (payload) => setConflicts((payload.items || []).filter(isOpenProfileConflict))),
    ]);
    if (onlySection) setRetryingSection(null);
    else if (loadVersion.current === version) setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const totalCount = reviews.length + assertions.length + stories.length + seeds.length + conflicts.length;
  const memoryCount = reviews.length + assertions.length + conflicts.length;
  const experienceCount = seeds.length;
  const observationCount = stories.length;

  const handleAssertion = async (assertion: L2Assertion, action: PendingAction) => {
    if (action === 'rejected') {
      setCorrectionTarget({
        kind: 'assertion',
        id: assertion.assertion_id,
        displaySentence: getPendingAssertionCopy(assertion, t).title,
        editableValue: assertion.trait_value,
        expectedUpdatedAt: assertion.updated_at ?? undefined,
      });
      return;
    }
    const id = `assertion:${assertion.assertion_id}`;
    setActionId(id);
    try {
      await memoryApi.submitAssertionFeedback(assertion.assertion_id, 'confirmed');
      setAssertions((items) => items.filter((item) => item.assertion_id !== assertion.assertion_id));
    } catch {
      toast.error(t('memory.pending.actionFailed'));
    } finally {
      setActionId(null);
    }
  };

  const handleReview = async (review: L2PendingReview, action: PendingReviewAction) => {
    if (action === 'edit') {
      setEditingReview(review);
      return;
    }
    const id = `review:${review.review_id}`;
    setActionId(id);
    try {
      await memoryApi.resolvePendingReview(review.review_id, {
        action,
        expected_version: review.version,
      });
      setReviews((items) => items.filter((item) => item.review_id !== review.review_id));
      setSelectedPlanReviewIds((items) => {
        const next = new Set(items);
        next.delete(review.review_id);
        return next;
      });
    } catch {
      toast.error(t('memory.pending.actionFailed'));
    } finally {
      setActionId(null);
    }
  };

  const currentPlanReviews = useMemo(() => reviews.filter(isCurrentPlanReview), [reviews]);

  const handlePlanReviewSelection = (reviewId: string, selected: boolean) => {
    setSelectedPlanReviewIds((items) => {
      const next = new Set(items);
      if (selected) next.add(reviewId);
      else next.delete(reviewId);
      return next;
    });
  };

  const handleSelectAllPlanReviews = (selected: boolean) => {
    setSelectedPlanReviewIds(selected
      ? new Set(currentPlanReviews.map((review) => review.review_id))
      : new Set());
  };

  const handleBatchConfirmPlans = async () => {
    const selectedReviews = currentPlanReviews.filter((review) => selectedPlanReviewIds.has(review.review_id));
    if (selectedReviews.length === 0) return;
    setActionId('review-batch');
    try {
      const results = await Promise.allSettled(selectedReviews.map((review) => (
        memoryApi.resolvePendingReview(review.review_id, {
          action: 'confirm',
          expected_version: review.version,
        })
      )));
      const confirmedIds = new Set(selectedReviews
        .filter((_, index) => results[index].status === 'fulfilled')
        .map((review) => review.review_id));
      setReviews((items) => items.filter((item) => !confirmedIds.has(item.review_id)));
      setSelectedPlanReviewIds((items) => new Set(
        Array.from(items).filter((reviewId) => !confirmedIds.has(reviewId)),
      ));
      const failedCount = selectedReviews.length - confirmedIds.size;
      if (failedCount === 0) {
        toast.success(t('memory.pending.planBatch.confirmed', { count: confirmedIds.size }));
      } else if (confirmedIds.size > 0) {
        toast.warning(t('memory.pending.planBatch.partialFailure', {
          confirmed: confirmedIds.size,
          failed: failedCount,
        }));
      } else {
        toast.error(t('memory.pending.planBatch.failed'));
      }
    } catch {
      toast.error(t('memory.pending.actionFailed'));
    } finally {
      setActionId(null);
    }
  };

  const handleReviewEdit = async (edit: { trait_value: string; natural_summary?: string }) => {
    if (!editingReview) return;
    const review = editingReview;
    const id = `review:${review.review_id}`;
    setActionId(id);
    try {
      await memoryApi.resolvePendingReview(review.review_id, {
        action: 'confirm_with_edit',
        expected_version: review.version,
        edit,
      });
      setReviews((items) => items.filter((item) => item.review_id !== review.review_id));
      setEditingReview(null);
    } catch {
      toast.error(t('memory.pending.actionFailed'));
    } finally {
      setActionId(null);
    }
  };

  const handleStory = async (story: StoryItem, action: PendingAction) => {
    const id = `story:${story.summary_id}`;
    setActionId(id);
    try {
      await memoryStoriesApi.review(story.summary_id, { review_state: action });
      setStories((items) => items.filter((item) => item.summary_id !== story.summary_id));
    } catch {
      toast.error(t('memory.pending.actionFailed'));
    } finally {
      setActionId(null);
    }
  };

  const handleSeed = async (seed: L2ExperienceSeed, action: 'promote' | 'reject') => {
    const id = `seed:${seed.seed_id}`;
    setActionId(id);
    try {
      if (action === 'promote') {
        await memoryApi.promoteExperienceSeed(seed.seed_id);
      } else {
        await memoryApi.rejectExperienceSeed(seed.seed_id);
      }
      setSeeds((items) => items.filter((item) => item.seed_id !== seed.seed_id));
    } catch {
      toast.error(t('memory.pending.actionFailed'));
    } finally {
      setActionId(null);
    }
  };

  const handleConflict = async (notification: NotificationItem, action: ConflictAction) => {
    const id = `conflict:${notification.id}`;
    setActionId(id);
    try {
      await resolveConflict(notification.id, action);
      setConflicts((items) => items.filter((item) => item.id !== notification.id));
    } catch {
      toast.error(t('memory.pending.actionFailed'));
    } finally {
      setActionId(null);
    }
  };

  const filterOptions = useMemo(() => buildPendingFilterOptions({
    totalCount,
    memoryCount,
    experienceCount,
    observationCount,
  }), [experienceCount, memoryCount, observationCount, totalCount]);
  const showMemory = activeFilter === 'all' || activeFilter === 'memory';
  const showExperiences = activeFilter === 'all' || activeFilter === 'experiences';
  const showObservations = activeFilter === 'all' || activeFilter === 'observations';

  return (
    <MemoryPageFrame
      title=""
      description=""
      hideHeader
      className="max-w-[1040px] gap-3 px-5 pb-5 pt-3"
      contentClassName="pb-6"
    >
      {failedSections.map((section) => (
        <section key={section} role="alert" className={`${MEMORY_EMPTY_PANEL_CLASS} flex flex-wrap items-center justify-between gap-3`}>
          <p>{t('memory.pending.loadFailed', { section: t(`memory.pending.loadSections.${section}`) })}</p>
          <Button variant="outline" size="sm" disabled={retryingSection !== null || loading} onClick={() => void load(section)}>
            {retryingSection === section ? <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" /> : null}
            {t('memory.pending.retry')}
          </Button>
        </section>
      ))}
      {loading ? (
        <section className={`${MEMORY_EMPTY_PANEL_CLASS} flex items-center gap-2`}>
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        </section>
      ) : totalCount === 0 && failedSections.length === 0 ? (
        <section className={MEMORY_EMPTY_PANEL_CLASS}>
          <div className="font-semibold text-[hsl(var(--memory-title))]">{t('memory.pending.emptyTitle')}</div>
          <p className="mt-1 text-sm">{t('memory.pending.emptyBody')}</p>
        </section>
      ) : (
        <div>
          <div className="border-b border-[hsl(var(--memory-divider)/0.5)]">
            <PendingFilterTabs
              options={filterOptions}
              activeFilter={activeFilter}
              onChange={setActiveFilter}
            />
          </div>
          <div className="mt-6 [&>section+section]:mt-10 [&>section+section]:border-t [&>section+section]:border-[hsl(var(--memory-divider)/0.5)] [&>section+section]:pt-10">
            <PendingReviewGroups
              reviews={reviews}
              assertions={assertions}
              stories={stories}
              seeds={seeds}
              conflicts={conflicts}
              actionId={actionId}
              memoryCount={memoryCount}
              experienceCount={experienceCount}
              observationCount={observationCount}
              showMemory={showMemory}
              showExperiences={showExperiences}
              showObservations={showObservations}
              onReview={handleReview}
              selectedPlanReviewIds={selectedPlanReviewIds}
              onPlanReviewSelection={handlePlanReviewSelection}
              onSelectAllPlanReviews={handleSelectAllPlanReviews}
              onBatchConfirmPlans={handleBatchConfirmPlans}
              onAssertion={handleAssertion}
              onStory={handleStory}
              onSeed={handleSeed}
              onConflict={handleConflict}
            />
          </div>
        </div>
      )}
      <MemoryCorrectionDialog
        open={correctionTarget !== null}
        target={correctionTarget}
        initialRecordErrorAction="remove"
        onOpenChange={(open) => {
          if (!open) setCorrectionTarget(null);
        }}
        onSaved={load}
        onConflict={load}
      />
      <PendingMemoryReviewEditDialog
        review={editingReview}
        busy={Boolean(editingReview && actionId === `review:${editingReview.review_id}`)}
        onOpenChange={(open) => {
          if (!open && !actionId) setEditingReview(null);
        }}
        onSubmit={handleReviewEdit}
      />
    </MemoryPageFrame>
  );
};

export default MemoryPendingPage;
