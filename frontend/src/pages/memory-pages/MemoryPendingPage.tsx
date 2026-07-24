import { useCallback, useEffect, useMemo, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import MemoryCorrectionDialog from '@/components/memory/correction/MemoryCorrectionDialog';
import type { MemoryCorrectionUiTarget } from '@/components/memory/correction/memoryCorrectionModel';
import {
  memoryApi,
  type L2Assertion,
  type L2ExperienceSeed,
} from '@/api/modules/memory';
import { memoryStoriesApi, type StoryItem } from '@/api/modules/memoryStories';
import {
  listNotifications,
  resolveConflict,
  type NotificationItem,
} from '@/api/modules/notifications';
import MemoryPageFrame, { MEMORY_EMPTY_PANEL_CLASS } from './MemoryPageFrame';
import { PendingFilterTabs } from './pending/PendingFilterTabs';
import { PendingReviewGroups } from './pending/PendingReviewGroups';
import {
  buildPendingFilterOptions,
  isOpenProfileConflict,
  type ConflictAction,
  type PendingAction,
  type PendingFilter,
} from './pending/pendingModel';
import { isMemoryUpdateStory } from './storyFilters';
import { getPendingAssertionCopy } from '@/utils/memory-assertion-copy';

export const MemoryPendingPage = () => {
  const { t } = useTranslation('app');
  const [assertions, setAssertions] = useState<L2Assertion[]>([]);
  const [stories, setStories] = useState<StoryItem[]>([]);
  const [seeds, setSeeds] = useState<L2ExperienceSeed[]>([]);
  const [conflicts, setConflicts] = useState<NotificationItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionId, setActionId] = useState<string | null>(null);
  const [activeFilter, setActiveFilter] = useState<PendingFilter>('all');
  const [correctionTarget, setCorrectionTarget] = useState<MemoryCorrectionUiTarget | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [dashboardPayload, storyPayload, seedPayload, notificationPayload] = await Promise.all([
        memoryApi.getDashboard({ pending_limit: 25 }),
        memoryStoriesApi.list({ limit: 50, offset: 0, surface: 'all' }),
        memoryApi.listExperienceSeeds({ status: 'candidate', limit: 50, offset: 0 }),
        listNotifications(),
      ]);
      setAssertions(dashboardPayload.pending_assertions?.items || []);
      setStories((storyPayload.items || []).filter((story) => (
        story.review_state === 'pending_confirmation' && isMemoryUpdateStory(story)
      )));
      setSeeds(seedPayload.items || []);
      setConflicts((notificationPayload.items || []).filter(isOpenProfileConflict));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const totalCount = assertions.length + stories.length + seeds.length + conflicts.length;
  const memoryCount = assertions.length + conflicts.length;
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
      className="max-w-[680px]"
      contentClassName="space-y-10 pt-4"
    >
      {loading ? (
        <section className={`${MEMORY_EMPTY_PANEL_CLASS} flex items-center gap-2`}>
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        </section>
      ) : totalCount === 0 ? (
        <section className={MEMORY_EMPTY_PANEL_CLASS}>
          <div className="font-semibold text-[hsl(var(--memory-title))]">{t('memory.pending.emptyTitle')}</div>
          <p className="mt-1 text-sm">{t('memory.pending.emptyBody')}</p>
        </section>
      ) : (
        <div className="space-y-12">
          <PendingFilterTabs
            options={filterOptions}
            activeFilter={activeFilter}
            onChange={setActiveFilter}
          />
          <PendingReviewGroups
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
            onAssertion={handleAssertion}
            onStory={handleStory}
            onSeed={handleSeed}
            onConflict={handleConflict}
          />
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
    </MemoryPageFrame>
  );
};

export default MemoryPendingPage;
