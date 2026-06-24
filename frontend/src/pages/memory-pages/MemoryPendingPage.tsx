import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { BookOpen, Check, FileText, Loader2, UserRound, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  memoryApi,
  type L2Assertion,
  type L2ExperienceSeed,
} from '@/api/modules/memory';
import { memoryStoriesApi, type StoryItem } from '@/api/modules/memoryStories';
import MemoryPageFrame, {
  MEMORY_ACTION_BUTTON_CLASS,
  MEMORY_EMPTY_PANEL_CLASS,
} from './MemoryPageFrame';
import { isMemoryUpdateStory } from './storyFilters';

type PendingAction = 'confirmed' | 'rejected';

const assertionTitle = (assertion: L2Assertion): string => (
  String(assertion.trait_name || assertion.assertion_id || '').trim()
);

const assertionBody = (assertion: L2Assertion): string => (
  String(assertion.trait_value || '').trim()
);

const storyTitle = (story: StoryItem, fallback: string): string => (
  String(story.title || '').trim() || fallback
);

const seedTitle = (seed: L2ExperienceSeed, fallback: string): string => (
  String(seed.display_title || seed.title || '').trim() || fallback
);

const seedBody = (seed: L2ExperienceSeed): string => (
  String(seed.display_description || seed.description || '').trim()
);

export const MemoryPendingPage = () => {
  const { t } = useTranslation('app');
  const [assertions, setAssertions] = useState<L2Assertion[]>([]);
  const [stories, setStories] = useState<StoryItem[]>([]);
  const [seeds, setSeeds] = useState<L2ExperienceSeed[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionId, setActionId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [dashboardPayload, storyPayload, seedPayload] = await Promise.all([
        memoryApi.getDashboard({ pending_limit: 25 }),
        memoryStoriesApi.list({ limit: 50, offset: 0 }),
        memoryApi.listExperienceSeeds({ status: 'candidate', limit: 50, offset: 0 }),
      ]);
      setAssertions(dashboardPayload.pending_assertions?.items || []);
      setStories((storyPayload.items || []).filter((story) => (
        story.review_state === 'pending_confirmation' && isMemoryUpdateStory(story)
      )));
      setSeeds(seedPayload.items || []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const totalCount = assertions.length + stories.length + seeds.length;

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

  const sections = useMemo(() => [
    {
      key: 'profile',
      title: t('memory.pending.sections.profile'),
      items: assertions,
      icon: <UserRound className="h-4 w-4" aria-hidden="true" />,
    },
    {
      key: 'summaries',
      title: t('memory.pending.sections.summaries'),
      items: stories,
      icon: <FileText className="h-4 w-4" aria-hidden="true" />,
    },
    {
      key: 'experiences',
      title: t('memory.pending.sections.experiences'),
      items: seeds,
      icon: <BookOpen className="h-4 w-4" aria-hidden="true" />,
    },
  ], [assertions, seeds, stories, t]);

  return (
    <MemoryPageFrame title={t('memory.pending.title')} description={t('memory.pending.subtitle')}>
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
        <div className="space-y-4">
          <PendingSection title={sections[0].title} icon={sections[0].icon} count={assertions.length}>
            {assertions.map((assertion) => {
              const busy = actionId === `assertion:${assertion.assertion_id}`;
              return (
                <PendingCard
                  key={assertion.assertion_id}
                  testId={`pending-assertion-${assertion.assertion_id}`}
                  label={t('memory.pending.meta.assertion')}
                  title={assertionTitle(assertion)}
                  body={assertionBody(assertion)}
                  meta={t('memory.pending.evidenceCount', { count: assertion.evidence_events?.length ?? 0 })}
                  actions={(
                    <ReviewActions
                      busy={busy}
                      onConfirm={() => void handleAssertion(assertion, 'confirmed')}
                      onReject={() => void handleAssertion(assertion, 'rejected')}
                    />
                  )}
                />
              );
            })}
          </PendingSection>

          <PendingSection title={sections[1].title} icon={sections[1].icon} count={stories.length}>
            {stories.map((story) => {
              const busy = actionId === `story:${story.summary_id}`;
              return (
                <PendingCard
                  key={story.summary_id}
                  testId={`pending-story-${story.summary_id}`}
                  label={t('memory.pending.meta.summary')}
                  title={storyTitle(story, t('memory.pending.fallbackMemoryUpdateTitle'))}
                  body={story.content}
                  meta={t('memory.pending.evidenceCount', { count: story.evidence_event_count })}
                  actions={(
                    <ReviewActions
                      busy={busy}
                      onConfirm={() => void handleStory(story, 'confirmed')}
                      onReject={() => void handleStory(story, 'rejected')}
                    />
                  )}
                />
              );
            })}
          </PendingSection>

          <PendingSection title={sections[2].title} icon={sections[2].icon} count={seeds.length}>
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
        </div>
      )}
    </MemoryPageFrame>
  );
};

function PendingSection({
  title,
  icon,
  count,
  children,
}: {
  title: string;
  icon: ReactNode;
  count: number;
  children: ReactNode;
}) {
  if (count === 0) {
    return null;
  }
  return (
    <section className="space-y-2.5">
      <div className="flex items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-[hsl(var(--memory-title))]">
          <span className="text-[hsl(var(--memory-accent))]">{icon}</span>
          {title}
        </h2>
        <span className="text-xs text-[hsl(var(--memory-muted))]">{count}</span>
      </div>
      <div className="mt-3 space-y-2">{children}</div>
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
  label: string;
  title: string;
  body: string;
  meta: string;
  actions: ReactNode;
}) {
  return (
    <article
      data-testid={testId}
      className="grid gap-3 rounded-lg border border-[hsl(var(--memory-border)/0.52)] bg-[hsl(var(--memory-panel-elevated)/0.68)] px-4 py-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-center"
    >
      <div className="min-w-0">
        <div className="text-xs text-[hsl(var(--memory-muted))]">{label}</div>
        <h3 className="mt-1 break-words text-sm font-semibold text-[hsl(var(--memory-title))]">{title}</h3>
        {body ? <p className="mt-1 line-clamp-2 text-sm leading-6 text-[hsl(var(--memory-body))]">{body}</p> : null}
        {meta ? <div className="mt-1 text-xs text-[hsl(var(--memory-muted))]">{meta}</div> : null}
      </div>
      {actions}
    </article>
  );
}

function ReviewActions({
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
        {t('memory.pending.actions.confirm')}
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
        {t('memory.pending.actions.reject')}
      </Button>
    </div>
  );
}

export default MemoryPendingPage;
