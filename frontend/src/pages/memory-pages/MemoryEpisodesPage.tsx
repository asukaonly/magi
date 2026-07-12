import { useCallback, useEffect, useMemo, useState } from 'react';
import { Loader2, Plus, SearchX } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
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
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import MemoryPageFrame, { MEMORY_EMPTY_PANEL_CLASS, MEMORY_INFO_PANEL_CLASS } from './MemoryPageFrame';
import { ExperienceTimeline } from './episodes/ExperienceTimeline';
import { PendingExperienceShelf } from './episodes/PendingExperienceShelf';
import { groupExperiencesByMonth, sortExperiencesForReview } from './episodes/experienceIndexModel';

export { sortExperiencesForReview } from './episodes/experienceIndexModel';
export { MemoryExperienceDetailPage } from './episodes/MemoryExperienceDetailPage';
export { MemoryExperienceDraftPage } from './episodes/MemoryExperienceDraftPage';

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
          <div className="flex justify-end">
            <Button
              type="button"
              size="sm"
              className="h-8 rounded-md px-3 text-xs"
              onClick={openCreateExperience}
            >
              <Plus className="h-4 w-4" aria-hidden="true" />
              {t('memory.episodes.actions.createExperience')}
            </Button>
          </div>
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
            <div className={MEMORY_EMPTY_PANEL_CLASS}>
              <div className="font-semibold text-[hsl(var(--memory-title))]">{t('memory.episodes.emptyTitle')}</div>
              <p className="mt-1 text-sm">{t('memory.episodes.emptyBody')}</p>
            </div>
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
            <DialogContent className="max-w-xl">
              <DialogHeader>
                <DialogTitle>{t('memory.episodes.create.title')}</DialogTitle>
                <DialogDescription>{t('memory.episodes.create.description')}</DialogDescription>
              </DialogHeader>
              <div className="space-y-4 px-6 pb-2">
                <label className="block space-y-2">
                  <span className="text-sm font-medium text-[hsl(var(--memory-title))]">{t('memory.episodes.create.promptLabel')}</span>
                  <Textarea
                    aria-label={t('memory.episodes.create.promptLabel')}
                    placeholder={t('memory.episodes.create.promptPlaceholder')}
                    value={createPrompt}
                    onChange={(event) => {
                      setCreatePrompt(event.target.value);
                      setOrganizeChoices([]);
                      setCreateNotice(null);
                      setCreateError(null);
                    }}
                    className="min-h-28 resize-none border-[hsl(var(--memory-input-border)/0.68)] bg-[hsl(var(--memory-input-bg))] text-base leading-7"
                  />
                </label>
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
                    className="rounded-md border border-destructive/20 bg-destructive/5 px-3 py-2 text-sm text-destructive"
                  >
                    {createError}
                  </div>
                ) : null}
              </div>
              <DialogFooter>
                <Button variant="ghost" onClick={() => setCreateOpen(false)} disabled={createSaving}>
                  {t('common.cancel')}
                </Button>
                <Button onClick={() => { void organizeExperience(); }} disabled={createSaving || createPrompt.trim().length < 2}>
                  {createSaving ? t('common.saving') : t('memory.episodes.create.organize')}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </section>
      )}
    </MemoryPageFrame>
  );
};

export default MemoryEpisodesPage;
