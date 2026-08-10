import { Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { L2Assertion, L2ExperienceSeed, L2PendingReview } from '@/api/modules/memory';
import type { StoryItem } from '@/api/modules/memoryStories';
import type { NotificationItem } from '@/api/modules/notifications';
import { Button } from '@/components/ui/button';
import { getPendingAssertionCopy } from '@/utils/memory-assertion-copy';
import { MEMORY_GHOST_ACTION_CLASS, MEMORY_PRIMARY_ACTION_CLASS } from '../MemoryPageFrame';
import {
  ConflictActions,
  PendingCard,
  PendingSection,
  ReviewActions,
} from './PendingPrimitives';
import {
  conflictBody,
  conflictTitle,
  pendingReviewSummary,
  pendingReviewValue,
  isCurrentPlanReview,
  seedBody,
  seedTitle,
  storyTitle,
  type ConflictAction,
  type PendingAction,
  type PendingReviewAction,
} from './pendingModel';

export function PendingReviewGroups({
  reviews,
  assertions,
  stories,
  seeds,
  conflicts,
  actionId,
  memoryCount,
  experienceCount,
  observationCount,
  showMemory,
  showExperiences,
  showObservations,
  onReview,
  selectedPlanReviewIds,
  onPlanReviewSelection,
  onSelectAllPlanReviews,
  onBatchConfirmPlans,
  onAssertion,
  onStory,
  onSeed,
  onConflict,
}: {
  reviews: L2PendingReview[];
  assertions: L2Assertion[];
  stories: StoryItem[];
  seeds: L2ExperienceSeed[];
  conflicts: NotificationItem[];
  actionId: string | null;
  memoryCount: number;
  experienceCount: number;
  observationCount: number;
  showMemory: boolean;
  showExperiences: boolean;
  showObservations: boolean;
  onReview: (review: L2PendingReview, action: PendingReviewAction) => void;
  selectedPlanReviewIds: ReadonlySet<string>;
  onPlanReviewSelection: (reviewId: string, selected: boolean) => void;
  onSelectAllPlanReviews: (selected: boolean) => void;
  onBatchConfirmPlans: () => void;
  onAssertion: (assertion: L2Assertion, action: PendingAction) => void;
  onStory: (story: StoryItem, action: PendingAction) => void;
  onSeed: (seed: L2ExperienceSeed, action: 'promote' | 'reject') => void;
  onConflict: (notification: NotificationItem, action: ConflictAction) => void;
}) {
  const { t } = useTranslation('app');
  const planReviews = reviews.filter(isCurrentPlanReview);
  const batchBusy = actionId === 'review-batch';
  const allPlanReviewsSelected = planReviews.length > 0
    && planReviews.every((review) => selectedPlanReviewIds.has(review.review_id));

  return (
    <>
      {showMemory ? (
        <PendingSection
          title={t('memory.pending.groups.memory.title')}
          description={t('memory.pending.groups.memory.description')}
          count={memoryCount}
          tone="amber"
        >
          {planReviews.length > 1 ? (
            <div className="mt-5 flex flex-col gap-3 rounded-lg bg-[hsl(var(--memory-panel-subtle)/0.56)] px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <h3 className="text-sm font-semibold text-[hsl(var(--memory-title))]">
                  {t('memory.pending.planBatch.title')}
                </h3>
                <p className="mt-1 text-xs leading-5 text-[hsl(var(--memory-muted))]">
                  {t('memory.pending.planBatch.body')}
                </p>
              </div>
              <div className="flex shrink-0 flex-wrap items-center gap-1.5">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className={MEMORY_GHOST_ACTION_CLASS}
                  disabled={batchBusy}
                  onClick={() => onSelectAllPlanReviews(!allPlanReviewsSelected)}
                >
                  {t(allPlanReviewsSelected
                    ? 'memory.pending.planBatch.clearSelection'
                    : 'memory.pending.planBatch.selectAll')}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className={MEMORY_PRIMARY_ACTION_CLASS}
                  disabled={batchBusy || selectedPlanReviewIds.size === 0}
                  onClick={onBatchConfirmPlans}
                >
                  {batchBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                  {t('memory.pending.planBatch.confirmSelected', { count: selectedPlanReviewIds.size })}
                </Button>
              </div>
            </div>
          ) : null}
          {reviews.map((review) => {
            const busy = batchBusy || actionId === `review:${review.review_id}`;
            const value = pendingReviewValue(review, t('memory.pending.reviews.unknownValue'));
            const selectablePlan = isCurrentPlanReview(review) && planReviews.length > 1;
            return (
              <PendingCard
                key={review.review_id}
                testId={`pending-review-${review.review_id}`}
                label={t('memory.pending.meta.preMaterializationReview')}
                title={t('memory.pending.reviews.title', { value })}
                body={pendingReviewSummary(review, t('memory.pending.reviews.body'))}
                meta={t('memory.pending.claimCount', { count: review.claim_ids.length })}
                selection={selectablePlan ? (
                  <input
                    type="checkbox"
                    className="h-4 w-4 rounded border-[hsl(var(--memory-input-border))] accent-[hsl(var(--memory-accent))]"
                    aria-label={t('memory.pending.planBatch.selectLabel', { value })}
                    checked={selectedPlanReviewIds.has(review.review_id)}
                    disabled={batchBusy}
                    onChange={(event) => onPlanReviewSelection(review.review_id, event.target.checked)}
                  />
                ) : undefined}
                actions={(
                  <div className="flex flex-wrap items-center gap-1">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className={MEMORY_PRIMARY_ACTION_CLASS}
                      disabled={busy}
                      onClick={() => onReview(review, 'confirm')}
                    >
                      {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                      {t('memory.pending.actions.confirmReview')}
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className={MEMORY_GHOST_ACTION_CLASS}
                      disabled={busy}
                      onClick={() => onReview(review, 'edit')}
                    >
                      {t('memory.pending.actions.editReview')}
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className={MEMORY_GHOST_ACTION_CLASS}
                      disabled={busy}
                      onClick={() => onReview(review, 'reject')}
                    >
                      {t('memory.pending.actions.reject')}
                    </Button>
                  </div>
                )}
              />
            );
          })}
          {assertions.map((assertion) => {
            const busy = actionId === `assertion:${assertion.assertion_id}`;
            const copy = getPendingAssertionCopy(assertion, t);
            return (
              <PendingCard
                key={assertion.assertion_id}
                testId={`pending-assertion-${assertion.assertion_id}`}
                label={t('memory.pending.meta.assertion')}
                title={copy.title}
                body={copy.body}
                meta={t('memory.pending.evidenceCount', { count: assertion.evidence_events?.length ?? 0 })}
                actions={(
                  <ReviewActions
                    busy={busy}
                    confirmLabel={t('memory.pending.actions.confirmJudgment')}
                    rejectLabel={t('memory.pending.actions.reject')}
                    onConfirm={() => onAssertion(assertion, 'confirmed')}
                    onReject={() => onAssertion(assertion, 'rejected')}
                  />
                )}
              />
            );
          })}
          {conflicts.map((conflict) => {
            const busy = actionId === `conflict:${conflict.id}`;
            return (
              <PendingCard
                key={conflict.id}
                testId={`pending-conflict-${conflict.id}`}
                label={t('memory.pending.meta.conflict')}
                title={conflictBody(conflict) || conflictTitle(conflict, t('memory.pending.fallbackConflictTitle'))}
                body=""
                meta={t('memory.pending.conflictMeta')}
                actions={(
                  <ConflictActions
                    busy={busy}
                    onConfirm={() => onConflict(conflict, 'confirm')}
                    onReject={() => onConflict(conflict, 'reject')}
                  />
                )}
              />
            );
          })}
        </PendingSection>
      ) : null}

      {showExperiences ? (
        <PendingSection
          title={t('memory.pending.groups.experiences.title')}
          description={t('memory.pending.groups.experiences.description')}
          count={experienceCount}
          tone="green"
        >
          {seeds.map((seed) => {
            const busy = actionId === `seed:${seed.seed_id}`;
            return (
              <PendingCard
                key={seed.seed_id}
                testId={`pending-experience-${seed.seed_id}`}
                label={t('memory.pending.meta.experienceSeed')}
                title={seedTitle(seed, t('memory.episodes.pending.fallbackTitle'))}
                body={seedBody(seed)}
                meta={t('memory.pending.fragmentCount', { count: seed.evidence_count ?? 0 })}
                actions={(
                  <div className="flex flex-wrap items-center gap-1">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className={MEMORY_PRIMARY_ACTION_CLASS}
                      disabled={busy}
                      onClick={() => onSeed(seed, 'promote')}
                    >
                      {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                      {t('memory.pending.actions.promoteExperience')}
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className={MEMORY_GHOST_ACTION_CLASS}
                      disabled={busy}
                      onClick={() => onSeed(seed, 'reject')}
                    >
                      {t('memory.pending.actions.rejectExperience')}
                    </Button>
                  </div>
                )}
              />
            );
          })}
        </PendingSection>
      ) : null}

      {showObservations ? (
        <PendingSection
          title={t('memory.pending.groups.observations.title')}
          description={t('memory.pending.groups.observations.description')}
          count={observationCount}
          tone="blue"
        >
          {stories.map((story) => {
            const busy = actionId === `story:${story.summary_id}`;
            const title = storyTitle(story, t('memory.pending.fallbackMemoryUpdateTitle'));
            const body = String(story.detail_lead_text || story.content || '').trim();
            return (
              <PendingCard
                key={story.summary_id}
                testId={`pending-story-${story.summary_id}`}
                title={title}
                body={body}
                meta={t('memory.pending.evidenceCount', { count: story.evidence_event_count })}
                actions={(
                  <ReviewActions
                    busy={busy}
                    confirmLabel={t('memory.pending.actions.confirmObservation')}
                    rejectLabel={t('memory.pending.actions.rejectObservation')}
                    onConfirm={() => onStory(story, 'confirmed')}
                    onReject={() => onStory(story, 'rejected')}
                  />
                )}
              />
            );
          })}
        </PendingSection>
      ) : null}
    </>
  );
}
