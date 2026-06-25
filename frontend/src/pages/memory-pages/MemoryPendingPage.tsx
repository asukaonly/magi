import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { BookOpen, Check, FileText, Loader2, UserRound, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
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
import MemoryPageFrame, {
  MEMORY_ACTION_BUTTON_CLASS,
  MEMORY_EMPTY_PANEL_CLASS,
} from './MemoryPageFrame';
import { isMemoryUpdateStory } from './storyFilters';

type PendingAction = 'confirmed' | 'rejected';
type ConflictAction = 'confirm' | 'reject';
type PendingFilter = 'all' | 'memory' | 'experiences' | 'observations';
type TranslationFn = (key: string, options?: Record<string, unknown>) => string;

const MEMORY_REVIEW_BUTTON_CLASS = cn(
  MEMORY_ACTION_BUTTON_CLASS,
  'bg-[hsl(var(--memory-panel-elevated))] text-[hsl(var(--memory-title))]',
  'shadow-[inset_0_0_0_1px_hsl(var(--memory-border)/0.62)]',
  'hover:bg-[hsl(var(--memory-panel-subtle)/0.72)] hover:text-[hsl(var(--memory-title))]',
  'hover:shadow-[inset_0_0_0_1px_hsl(var(--memory-border)/0.78)]'
);

const assertionTitle = (assertion: L2Assertion): string => (
  String(assertion.trait_name || assertion.assertion_id || '').trim()
);

const assertionBody = (assertion: L2Assertion): string => (
  String(assertion.trait_value || '').trim()
);

const isInternalTraitName = (value: string): boolean => {
  const text = value.trim();
  if (!text) {
    return false;
  }
  return (
    text.startsWith('interest.') ||
    /^[a-z0-9_-]+(\.[a-z0-9_-]+)+$/i.test(text)
  );
};

const readableTraitName = (assertion: L2Assertion, displayedValue: string): string => {
  const traitName = assertionTitle(assertion);
  if (!traitName || traitName === displayedValue || traitName === assertion.assertion_id) {
    return '';
  }
  return isInternalTraitName(traitName) ? '' : traitName;
};

const assertionDisplayValue = (assertion: L2Assertion, t: TranslationFn): string => {
  const value = assertionBody(assertion);
  if (value) {
    return value;
  }
  const title = assertionTitle(assertion);
  if (title && title !== assertion.assertion_id && !isInternalTraitName(title)) {
    return title;
  }
  return t('memory.pending.assertions.unknownValue');
};

const readableConflictValue = (value: unknown): string => {
  const text = String(value || '').trim();
  return text && !isInternalTraitName(text) ? text : '';
};

const assertionCardCopy = (
  assertion: L2Assertion,
  t: TranslationFn,
): { title: string; body: string } => {
  const value = assertionDisplayValue(assertion, t);
  const context = assertion.conflict_context;
  const oldValue = readableConflictValue(context?.previous_value) || value;
  const newValue = readableConflictValue(context?.current_value);
  if (newValue && oldValue !== newValue) {
    return {
      title: t('memory.pending.assertions.conflictPairTitle', { oldValue, newValue }),
      body: t('memory.pending.assertions.conflictPairBody', { oldValue, newValue }),
    };
  }
  const state = String(assertion.validation_state || assertion.status || '').trim().toLowerCase();
  if (state === 'contradicted') {
    return {
      title: t('memory.pending.assertions.uncertainTitle', { value }),
      body: t('memory.pending.assertions.uncertainBody'),
    };
  }
  const traitName = readableTraitName(assertion, value);
  return {
    title: t('memory.pending.assertions.tentativeTitle', { value }),
    body: traitName
      ? t('memory.pending.assertions.traitBody', { trait: traitName })
      : t('memory.pending.assertions.tentativeBody'),
  };
};

const storyTitle = (story: StoryItem, fallback: string): string => (
  String(story.title || '').trim() || fallback
);

const seedTitle = (seed: L2ExperienceSeed, fallback: string): string => (
  String(seed.display_title || seed.title || '').trim() || fallback
);

const seedBody = (seed: L2ExperienceSeed): string => (
  String(seed.display_description || seed.description || '').trim()
);

const conflictTitle = (notification: NotificationItem, fallback: string): string => (
  String(notification.title || notification.payload.trait_name || '').trim() || fallback
);

const conflictBody = (notification: NotificationItem): string => (
  String(notification.body || notification.payload.inferred_value || '').trim()
);

const isOpenProfileConflict = (notification: NotificationItem): boolean => (
  notification.payload?.conflict_type === 'profile_conflict' &&
  (notification.status === 'unread' || notification.status === 'read')
);

export const MemoryPendingPage = () => {
  const { t } = useTranslation('app');
  const [assertions, setAssertions] = useState<L2Assertion[]>([]);
  const [stories, setStories] = useState<StoryItem[]>([]);
  const [seeds, setSeeds] = useState<L2ExperienceSeed[]>([]);
  const [conflicts, setConflicts] = useState<NotificationItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionId, setActionId] = useState<string | null>(null);
  const [activeFilter, setActiveFilter] = useState<PendingFilter>('all');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [dashboardPayload, storyPayload, seedPayload, notificationPayload] = await Promise.all([
        memoryApi.getDashboard({ pending_limit: 25 }),
        memoryStoriesApi.list({ limit: 50, offset: 0 }),
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
    const id = `assertion:${assertion.assertion_id}`;
    setActionId(id);
    try {
      await memoryApi.submitAssertionFeedback(assertion.assertion_id, action);
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

  const filterOptions = useMemo(() => [
    {
      key: 'all' as const,
      label: t('memory.pending.filters.all'),
      count: totalCount,
    },
    {
      key: 'memory' as const,
      label: t('memory.pending.filters.memory'),
      count: memoryCount,
    },
    {
      key: 'experiences' as const,
      label: t('memory.pending.filters.experiences'),
      count: experienceCount,
    },
    {
      key: 'observations' as const,
      label: t('memory.pending.filters.observations'),
      count: observationCount,
    },
  ], [experienceCount, memoryCount, observationCount, t, totalCount]);

  const showMemory = activeFilter === 'all' || activeFilter === 'memory';
  const showExperiences = activeFilter === 'all' || activeFilter === 'experiences';
  const showObservations = activeFilter === 'all' || activeFilter === 'observations';

  return (
    <MemoryPageFrame
      title=""
      description=""
      hideHeader
      className="max-w-[900px]"
      contentClassName="space-y-3"
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
        <div className="space-y-3">
          <div className="flex">
            <div className="inline-flex w-fit max-w-full flex-wrap gap-0.5 rounded-lg border border-[hsl(var(--memory-border)/0.58)] bg-[hsl(var(--memory-panel-elevated)/0.72)] p-0.5">
              {filterOptions.map((option) => {
                const selected = activeFilter === option.key;
                return (
                  <button
                    key={option.key}
                    type="button"
                    aria-pressed={selected}
                    className={cn(
                      'inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-sm font-medium transition-colors',
                      selected
                        ? 'bg-[hsl(var(--memory-title))] text-[hsl(var(--memory-panel-elevated))] shadow-sm'
                        : 'text-[hsl(var(--memory-body))] hover:bg-[hsl(var(--memory-panel-subtle)/0.72)]'
                    )}
                    onClick={() => setActiveFilter(option.key)}
                  >
                    <span>{option.label}</span>
                    <span className={cn(
                      'text-xs',
                      selected ? 'text-[hsl(var(--memory-panel-elevated)/0.82)]' : 'text-[hsl(var(--memory-muted))]'
                    )}>
                      {option.count}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {showMemory ? (
            <PendingSection
              title={t('memory.pending.groups.memory.title')}
              description={t('memory.pending.groups.memory.description')}
              icon={<UserRound className="h-4 w-4" aria-hidden="true" />}
              count={memoryCount}
              tone="amber"
            >
              {assertions.map((assertion) => {
                const busy = actionId === `assertion:${assertion.assertion_id}`;
                const copy = assertionCardCopy(assertion, t);
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
                        onConfirm={() => void handleAssertion(assertion, 'confirmed')}
                        onReject={() => void handleAssertion(assertion, 'rejected')}
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
                        onConfirm={() => void handleConflict(conflict, 'confirm')}
                        onReject={() => void handleConflict(conflict, 'reject')}
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
              icon={<BookOpen className="h-4 w-4" aria-hidden="true" />}
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
                      <div className="flex flex-wrap items-center gap-2">
                        <Button
                          type="button"
                          size="sm"
                          className={MEMORY_ACTION_BUTTON_CLASS}
                          disabled={busy}
                          onClick={() => void handleSeed(seed, 'promote')}
                        >
                          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                          {t('memory.pending.actions.promoteExperience')}
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className={MEMORY_ACTION_BUTTON_CLASS}
                          disabled={busy}
                          onClick={() => void handleSeed(seed, 'reject')}
                        >
                          <X className="h-3.5 w-3.5" />
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
              icon={<FileText className="h-4 w-4" aria-hidden="true" />}
              count={observationCount}
              tone="blue"
            >
              {stories.map((story) => {
                const busy = actionId === `story:${story.summary_id}`;
                const title = String(story.content || '').trim() || storyTitle(story, t('memory.pending.fallbackMemoryUpdateTitle'));
                const body = String(story.content || '').trim() ? storyTitle(story, '') : '';
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
                        onConfirm={() => void handleStory(story, 'confirmed')}
                        onReject={() => void handleStory(story, 'rejected')}
                      />
                    )}
                  />
                );
              })}
            </PendingSection>
          ) : null}
        </div>
      )}
    </MemoryPageFrame>
  );
};

function PendingSection({
  title,
  description,
  icon,
  count,
  tone,
  children,
}: {
  title: string;
  description: string;
  icon: ReactNode;
  count: number;
  tone: 'amber' | 'green' | 'blue';
  children: ReactNode;
}) {
  if (count === 0) {
    return null;
  }
  return (
    <section className="overflow-hidden rounded-xl border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-elevated)/0.7)]">
      <div className="flex items-center justify-between gap-4 border-b border-[hsl(var(--memory-divider)/0.56)] px-4 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <span
            className={cn(
              'flex h-8 w-8 shrink-0 items-center justify-center rounded-lg',
              tone === 'amber' && 'bg-amber-100/70 text-amber-700',
              tone === 'green' && 'bg-emerald-100/70 text-emerald-700',
              tone === 'blue' && 'bg-sky-100/75 text-sky-700'
            )}
          >
            {icon}
          </span>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-[hsl(var(--memory-title))]">{title}</h2>
            <p className="mt-0.5 truncate text-xs text-[hsl(var(--memory-muted))]">{description}</p>
          </div>
        </div>
        <span className="shrink-0 text-xs text-[hsl(var(--memory-muted))]">{count}</span>
      </div>
      <div className="divide-y divide-[hsl(var(--memory-divider)/0.54)]">{children}</div>
    </section>
  );
}

function PendingCard({
  testId,
  label,
  title,
  body,
  meta,
  actions,
}: {
  testId: string;
  label?: string;
  title: string;
  body: string;
  meta: string;
  actions: ReactNode;
}) {
  return (
    <article
      data-testid={testId}
      className="grid gap-3 px-4 py-3.5 md:grid-cols-[minmax(0,1fr)_auto] md:items-center"
    >
      <div className="min-w-0">
        {(label || meta) ? (
          <div className="mb-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-[hsl(var(--memory-muted))]">
            {label ? <span className="font-medium text-[hsl(var(--memory-body))]">{label}</span> : null}
            {label && meta ? <span aria-hidden="true">·</span> : null}
            {meta ? <span>{meta}</span> : null}
          </div>
        ) : null}
        <h3 className="break-words text-sm font-semibold leading-6 text-[hsl(var(--memory-title))]">{title}</h3>
        {body ? <p className="mt-1 line-clamp-2 text-sm leading-6 text-[hsl(var(--memory-body))]">{body}</p> : null}
      </div>
      <div className="md:justify-self-end">{actions}</div>
    </article>
  );
}

function ReviewActions({
  busy,
  confirmLabel,
  rejectLabel,
  onConfirm,
  onReject,
}: {
  busy: boolean;
  confirmLabel: string;
  rejectLabel: string;
  onConfirm: () => void;
  onReject: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        type="button"
        variant="outline"
        size="sm"
        className={MEMORY_REVIEW_BUTTON_CLASS}
        disabled={busy}
        onClick={onConfirm}
      >
        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
        {confirmLabel}
      </Button>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className={MEMORY_REVIEW_BUTTON_CLASS}
        disabled={busy}
        onClick={onReject}
      >
        <X className="h-3.5 w-3.5" />
        {rejectLabel}
      </Button>
    </div>
  );
}

function ConflictActions({
  busy,
  onConfirm,
  onReject,
}: {
  busy: boolean;
  onConfirm: () => void;
  onReject: () => void;
}) {
  const { t } = useTranslation('app');
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        type="button"
        size="sm"
        className={MEMORY_ACTION_BUTTON_CLASS}
        disabled={busy}
        onClick={onConfirm}
      >
        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
        {t('memory.pending.actions.acceptConflict')}
      </Button>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className={MEMORY_ACTION_BUTTON_CLASS}
        disabled={busy}
        onClick={onReject}
      >
        <X className="h-3.5 w-3.5" />
        {t('memory.pending.actions.keepExisting')}
      </Button>
    </div>
  );
}

export default MemoryPendingPage;
