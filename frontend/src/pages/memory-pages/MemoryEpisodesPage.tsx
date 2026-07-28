import { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowRight, Loader2, Plus, SearchX, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router';
import {
  memoryApi,
  type ExperienceDraft,
  type ExperienceDraftChoice,
  type L2ExperienceSeed,
  type L2ExperienceWithReview,
} from '@/api/modules/memory';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import MemoryPageFrame, { MEMORY_INFO_PANEL_CLASS } from './MemoryPageFrame';
import { ExperienceTimeline } from './episodes/ExperienceTimeline';
import { PendingExperienceShelf } from './episodes/PendingExperienceShelf';
import { groupExperiencesByMonth, sortExperiencesForReview } from './episodes/experienceIndexModel';

export { sortExperiencesForReview } from './episodes/experienceIndexModel';
export { MemoryExperienceDetailPage } from './episodes/MemoryExperienceDetailPage';
export { MemoryExperienceDraftPage } from './episodes/MemoryExperienceDraftPage';

const CREATE_EXAMPLE_KEYS = [
  'memory.episodes.create.examples.travel',
  'memory.episodes.create.examples.project',
  'memory.episodes.create.examples.decision',
] as const;

export const MemoryEpisodesPage = () => {
  const { t, i18n } = useTranslation('app');
  const navigate = useNavigate();
  const [experiences, setExperiences] = useState<L2ExperienceWithReview[]>([]);
  const [experienceSeeds, setExperienceSeeds] = useState<L2ExperienceSeed[]>([]);
  const [experienceDrafts, setExperienceDrafts] = useState<ExperienceDraft[]>([]);
  const [loading, setLoading] = useState(true);
  const [seedActionId, setSeedActionId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [createPrompt, setCreatePrompt] = useState('');
  const [organizeChoices, setOrganizeChoices] = useState<ExperienceDraftChoice[]>([]);
  const [createSaving, setCreateSaving] = useState(false);
  const [createNotice, setCreateNotice] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [experiencePayload, seedPayload, draftPayload] = await Promise.all([
        memoryApi.listExperiences({ status: 'active', limit: 100, offset: 0 }),
        memoryApi.listExperienceSeeds({ status: 'candidate', limit: 6, offset: 0 }),
        memoryApi.listExperienceDrafts({ status: 'editing', limit: 20, offset: 0 }),
      ]);
      setExperiences(experiencePayload.items);
      setExperienceSeeds(seedPayload.items);
      setExperienceDrafts(draftPayload.items);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const sortedExperiences = useMemo(() => sortExperiencesForReview(experiences), [experiences]);
  const groupedExperiences = useMemo(
    () => groupExperiencesByMonth(sortedExperiences, i18n.language, t('memory.episodes.unknownMonth')),
    [sortedExperiences, i18n.language, t]
  );
  const isCompletelyEmpty = experiences.length === 0
    && experienceSeeds.length === 0
    && experienceDrafts.length === 0;

  const openExperience = (experienceId: string) => {
    navigate(`/memory/episodes/${experienceId}`);
  };

  const openCreateExperience = () => {
    setCreateOpen(true);
    setCreateNotice(null);
    setCreateError(null);
    setCreatePrompt('');
    setOrganizeChoices([]);
  };

  const updateCreatePrompt = (value: string) => {
    setCreatePrompt(value);
    setOrganizeChoices([]);
    setCreateNotice(null);
    setCreateError(null);
  };

  const organizeExperience = async (choice?: ExperienceDraftChoice) => {
    if (!createPrompt.trim()) return;
    setCreateSaving(true);
    setCreateNotice(null);
    setCreateError(null);
    try {
      const response = await memoryApi.organizeExperienceDraft({
        query_text: createPrompt.trim(),
        ...(choice ? { time_start: choice.time_start, time_end: choice.time_end } : {}),
      });
      if (response.status === 'ambiguous') {
        setOrganizeChoices(response.choices || []);
        return;
      }
      if (response.status !== 'draft' || !response.draft) {
        setCreateNotice(t('memory.episodes.create.insufficient'));
        return;
      }
      setCreateOpen(false);
      navigate(`/memory/episode-drafts/${response.draft.draft_id}`);
    } catch {
      setCreateError(t('memory.episodes.create.error'));
    } finally {
      setCreateSaving(false);
    }
  };

  const promoteSeed = async (seedId: string) => {
    setSeedActionId(`${seedId}:promote`);
    try {
      await memoryApi.promoteExperienceSeed(seedId);
      await refresh();
    } finally {
      setSeedActionId(null);
    }
  };

  const rejectSeed = async (seedId: string) => {
    setSeedActionId(`${seedId}:reject`);
    try {
      await memoryApi.rejectExperienceSeed(seedId);
      setExperienceSeeds((items) => items.filter((item) => item.seed_id !== seedId));
    } finally {
      setSeedActionId(null);
    }
  };

  return (
    <MemoryPageFrame
      title={t('memory.episodes.title')}
      description={t('memory.episodes.subtitle')}
      hideHeader
      className="max-w-[1180px] gap-5 px-4 py-5"
      contentClassName="pb-8"
    >
      {loading ? (
        <div className={MEMORY_INFO_PANEL_CLASS}>{t('common.loading')}</div>
      ) : (
        <section className="min-w-0 space-y-7">
          {!isCompletelyEmpty ? (
            <div className="flex justify-end">
              <Button
                type="button"
                className="h-9 rounded-lg px-4 text-sm active:translate-y-px"
                onClick={openCreateExperience}
              >
                <Plus className="h-4 w-4" aria-hidden="true" />
                {t('memory.episodes.actions.createExperience')}
              </Button>
            </div>
          ) : null}
          {experienceDrafts.length > 0 ? (
            <button
              type="button"
              className="flex w-full items-center justify-between gap-4 rounded-lg border border-[hsl(var(--memory-border)/0.58)] bg-[hsl(var(--memory-panel-elevated)/0.72)] px-4 py-3 text-left hover:bg-[hsl(var(--memory-panel-subtle)/0.6)]"
              onClick={() => navigate(`/memory/episode-drafts/${experienceDrafts[0].draft_id}`)}
            >
              <span className="min-w-0">
                <span className="block text-xs text-[hsl(var(--memory-muted))]">{t('memory.episodes.draft.continue')}</span>
                <span className="mt-1 block truncate text-sm font-semibold text-[hsl(var(--memory-title))]">
                  {experienceDrafts[0].title}
                </span>
              </span>
              <span className="shrink-0 text-xs text-[hsl(var(--memory-accent))]">{t('memory.episodes.draft.open')}</span>
            </button>
          ) : null}
          {experienceSeeds.length > 0 ? (
            <PendingExperienceShelf
              seeds={experienceSeeds}
              actionId={seedActionId}
              onPromote={promoteSeed}
              onReject={rejectSeed}
            />
          ) : null}

          {experiences.length === 0 ? (
            isCompletelyEmpty ? (
              <div
                data-testid="experience-empty-state"
                className="mx-auto flex min-h-[440px] w-full max-w-[680px] items-center px-5 motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-bottom-2 motion-safe:duration-500"
              >
                <div className="relative w-full pl-10 sm:pl-12">
                  <span
                    aria-hidden="true"
                    className="absolute left-0 top-1.5 h-3 w-3 rounded-full bg-[hsl(var(--memory-accent))] shadow-[0_0_0_6px_hsl(var(--memory-accent-soft)/0.48)]"
                  />
                  <span
                    aria-hidden="true"
                    className="absolute bottom-1 left-[5px] top-7 w-px bg-[hsl(var(--memory-divider)/0.72)]"
                  />
                  <p className="text-xs font-medium tracking-[0.08em] text-[hsl(var(--memory-accent))]">
                    {t('memory.episodes.emptyEyebrow')}
                  </p>
                  <h2 className="mt-3 text-[clamp(1.75rem,3vw,2.35rem)] font-semibold tracking-[-0.035em] text-[hsl(var(--memory-title))]">
                    {t('memory.episodes.emptyTitle')}
                  </h2>
                  <p className="mt-4 max-w-[560px] text-[0.98rem] leading-7 text-[hsl(var(--memory-body))]">
                    {t('memory.episodes.emptyBody')}
                  </p>
                  <Button
                    type="button"
                    className="group mt-7 h-10 rounded-lg px-5 text-sm active:translate-y-px"
                    onClick={openCreateExperience}
                  >
                    {t('memory.episodes.actions.createExperience')}
                    <ArrowRight
                      className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-0.5 motion-reduce:transition-none"
                      aria-hidden="true"
                    />
                  </Button>
                </div>
              </div>
            ) : null
          ) : (
            <div className="space-y-4">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                <div className="min-w-0">
                  <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">
                    {t('memory.episodes.sections.all')}
                  </h2>
                  <p className="mt-1 text-xs text-[hsl(var(--memory-muted))]">
                    {t('memory.episodes.sortNote')}
                  </p>
                </div>
                <Badge variant="outline" className="w-fit rounded-full border-[hsl(var(--memory-tag-border))] bg-[hsl(var(--memory-tag-bg)/0.78)] text-[hsl(var(--memory-muted))]">
                  {t('memory.episodes.count', { count: sortedExperiences.length })}
                </Badge>
              </div>

              <ExperienceTimeline
                groups={groupedExperiences}
                onSelect={openExperience}
              />
            </div>
          )}

          <Dialog open={createOpen} onOpenChange={setCreateOpen}>
            <DialogContent
              hideClose
              className="w-[calc(100%-2rem)] max-w-[560px] overflow-hidden rounded-xl border-[hsl(var(--memory-border)/0.4)] bg-[hsl(var(--memory-panel-elevated)/0.99)] p-0 shadow-[0_30px_90px_hsl(var(--memory-shadow)/0.18)] duration-200 ease-[cubic-bezier(0.22,1,0.36,1)] data-[state=closed]:scale-[0.985] data-[state=open]:scale-100 motion-reduce:duration-0"
            >
              <DialogHeader className="relative px-7 pb-0 pt-7 pr-16">
                <DialogTitle className="text-xl font-semibold leading-7 tracking-[-0.02em] text-[hsl(var(--memory-title))]">
                  {t('memory.episodes.create.title')}
                </DialogTitle>
                <DialogDescription className="max-w-[430px] pt-1 text-sm leading-6 text-[hsl(var(--memory-body))]">
                  {t('memory.episodes.create.description')}
                </DialogDescription>
                <DialogClose asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    aria-label={t('memory.episodes.create.close')}
                    className="absolute right-5 top-5 h-8 w-8 text-[hsl(var(--memory-muted))] hover:text-[hsl(var(--memory-title))]"
                  >
                    <X className="h-4 w-4" aria-hidden="true" />
                  </Button>
                </DialogClose>
              </DialogHeader>
              <div className="space-y-5 px-7 pb-7 pt-5">
                <label className="block">
                  <span className="sr-only">{t('memory.episodes.create.promptLabel')}</span>
                  <Textarea
                    aria-label={t('memory.episodes.create.promptLabel')}
                    placeholder={t('memory.episodes.create.promptPlaceholder')}
                    value={createPrompt}
                    onChange={(event) => updateCreatePrompt(event.target.value)}
                    className="min-h-24 resize-none rounded-lg border-[hsl(var(--memory-input-border)/0.52)] bg-[hsl(var(--memory-input-bg))] px-4 py-3 text-[0.95rem] leading-7 text-[hsl(var(--memory-title))] shadow-none transition-[border-color,box-shadow] duration-200 placeholder:text-[hsl(var(--memory-input-placeholder))] focus-visible:border-[hsl(var(--memory-accent)/0.4)] focus-visible:ring-2 focus-visible:ring-[hsl(var(--memory-accent-soft)/0.58)] focus-visible:ring-offset-0"
                  />
                </label>
                <div className="space-y-2.5">
                  <p className="text-xs leading-5 text-[hsl(var(--memory-muted))]">
                    {t('memory.episodes.create.promptHint')}
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {CREATE_EXAMPLE_KEYS.map((key) => {
                      const example = t(key);
                      return (
                        <button
                          key={key}
                          type="button"
                          className="rounded-md bg-[hsl(var(--memory-panel-subtle)/0.62)] px-3 py-1.5 text-xs text-[hsl(var(--memory-body))] transition-colors duration-200 hover:bg-[hsl(var(--memory-accent-soft)/0.72)] hover:text-[hsl(var(--memory-title))] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--memory-accent)/0.18)]"
                          onClick={() => updateCreatePrompt(example)}
                        >
                          {example}
                        </button>
                      );
                    })}
                  </div>
                </div>
                {createSaving ? (
                  <div className={MEMORY_INFO_PANEL_CLASS}>
                    <Loader2 className="mr-2 inline h-4 w-4 animate-spin" aria-hidden="true" />
                    {t('memory.episodes.create.organizing')}
                  </div>
                ) : null}
                {organizeChoices.length > 0 ? (
                  <div className="space-y-2">
                    <div className="text-sm font-medium">{t('memory.episodes.create.choosePeriod')}</div>
                    {organizeChoices.map((choice) => (
                      <button
                        key={choice.choice_id}
                        type="button"
                        className="block w-full rounded-md border border-[hsl(var(--memory-border)/0.52)] px-3 py-2 text-left hover:bg-[hsl(var(--memory-panel-subtle)/0.6)]"
                        onClick={() => { void organizeExperience(choice); }}
                      >
                        <span className="block text-sm font-medium">{choice.preview}</span>
                        <span className="mt-1 block text-xs text-[hsl(var(--memory-muted))]">
                          {new Intl.DateTimeFormat(i18n.language, { dateStyle: 'medium' }).format(new Date(choice.time_start * 1000))}
                          {' · '}{t('memory.episodes.eventCount', { count: choice.event_count })}
                        </span>
                      </button>
                    ))}
                  </div>
                ) : null}
                {createNotice ? (
                  <div
                    role="status"
                    className="flex items-start gap-2 text-sm leading-6 text-[hsl(var(--memory-muted))]"
                  >
                    <SearchX className="mt-1 h-4 w-4 shrink-0" aria-hidden="true" />
                    <span>{createNotice}</span>
                  </div>
                ) : null}
                {createError ? (
                  <div
                    role="alert"
                    className="rounded-md bg-destructive/5 px-3 py-2 text-sm text-destructive"
                  >
                    {createError}
                  </div>
                ) : null}
                <div className="flex items-center justify-between gap-3 pt-1">
                  <DialogClose asChild>
                    <Button variant="ghost" className="px-2" disabled={createSaving}>
                      {t('common.cancel')}
                    </Button>
                  </DialogClose>
                  <Button
                    onClick={() => { void organizeExperience(); }}
                    disabled={createSaving || createPrompt.trim().length < 2}
                    className="min-w-[112px] rounded-lg disabled:bg-[hsl(var(--memory-panel-subtle)/0.86)] disabled:text-[hsl(var(--memory-muted))] disabled:opacity-100"
                  >
                    {createSaving ? t('common.saving') : t('memory.episodes.create.organize')}
                    {!createSaving ? <ArrowRight className="h-4 w-4" aria-hidden="true" /> : null}
                  </Button>
                </div>
              </div>
            </DialogContent>
          </Dialog>
        </section>
      )}
    </MemoryPageFrame>
  );
};

export default MemoryEpisodesPage;
