import { useCallback, useEffect, useMemo, useState } from 'react';
import { Loader2, Plus } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import {
  memoryApi,
  type L2EpisodeWithSummary,
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
import { Input } from '@/components/ui/input';
import MemoryPageFrame, { MEMORY_EMPTY_PANEL_CLASS, MEMORY_INFO_PANEL_CLASS } from './MemoryPageFrame';
import { ExperienceTimeline } from './episodes/ExperienceTimeline';
import { PendingExperienceShelf } from './episodes/PendingExperienceShelf';
import { groupExperiencesByMonth, sortExperiencesForReview } from './episodes/experienceIndexModel';
import { formatEpisodeTimeRange, getEpisodeDisplayTitle } from '@/components/memory/episodes/EpisodeRow';

export { sortExperiencesForReview } from './episodes/experienceIndexModel';
export { MemoryExperienceDetailPage } from './episodes/MemoryExperienceDetailPage';

const getEpisodeCandidateDescription = (episode: L2EpisodeWithSummary): string => (
  String(
    episode.display_description ||
    episode.episode_summary?.content ||
    episode.summary ||
    episode.slice_narrative ||
    ''
  ).trim()
);

export const MemoryEpisodesPage = () => {
  const { t, i18n } = useTranslation('app');
  const navigate = useNavigate();
  const [experiences, setExperiences] = useState<L2ExperienceWithReview[]>([]);
  const [experienceSeeds, setExperienceSeeds] = useState<L2ExperienceSeed[]>([]);
  const [loading, setLoading] = useState(true);
  const [seedActionId, setSeedActionId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [createCandidates, setCreateCandidates] = useState<L2EpisodeWithSummary[]>([]);
  const [selectedEpisodeIds, setSelectedEpisodeIds] = useState<Set<string>>(new Set());
  const [createTitleDraft, setCreateTitleDraft] = useState('');
  const [createLoading, setCreateLoading] = useState(false);
  const [createSaving, setCreateSaving] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [experiencePayload, seedPayload] = await Promise.all([
        memoryApi.listExperiences({ status: 'active', limit: 100, offset: 0 }),
        memoryApi.listExperienceSeeds({ status: 'candidate', limit: 6, offset: 0 }),
      ]);
      setExperiences(experiencePayload.items);
      setExperienceSeeds(seedPayload.items);
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

  const openCreateExperience = async () => {
    setCreateOpen(true);
    setCreateError(null);
    setSelectedEpisodeIds(new Set());
    setCreateTitleDraft('');
    setCreateLoading(true);
    try {
      const payload = await memoryApi.listEpisodes({ status: 'active', limit: 50, offset: 0 });
      setCreateCandidates(payload.items || []);
    } finally {
      setCreateLoading(false);
    }
  };

  const toggleCreateCandidate = (episodeId: string) => {
    setSelectedEpisodeIds((current) => {
      const next = new Set(current);
      if (next.has(episodeId)) {
        next.delete(episodeId);
      } else {
        next.add(episodeId);
      }
      return next;
    });
  };

  const createExperience = async () => {
    const episodeIds = Array.from(selectedEpisodeIds);
    if (episodeIds.length === 0) {
      return;
    }
    setCreateSaving(true);
    setCreateError(null);
    try {
      const response = await memoryApi.createExperienceSeed({
        episode_ids: episodeIds,
        title_hint: createTitleDraft.trim() || undefined,
        promote_now: true,
      });
      if (!response.promoted_experience_id) {
        setCreateError(t('memory.episodes.create.noPromotion'));
        await refresh();
        return;
      }
      setCreateOpen(false);
      await refresh();
      navigate(`/memory/episodes/${response.promoted_experience_id}`);
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
              onClick={() => { void openCreateExperience(); }}
            >
              <Plus className="h-4 w-4" aria-hidden="true" />
              {t('memory.episodes.actions.createExperience')}
            </Button>
          </div>
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
            <DialogContent className="max-w-3xl">
              <DialogHeader>
                <DialogTitle>{t('memory.episodes.create.title')}</DialogTitle>
                <DialogDescription>{t('memory.episodes.create.description')}</DialogDescription>
              </DialogHeader>
              <div className="space-y-4 px-6 pb-2">
                <label className="block space-y-2">
                  <span className="text-sm font-medium text-[hsl(var(--memory-title))]">{t('memory.episodes.fields.title')}</span>
                  <Input
                    aria-label={t('memory.episodes.fields.title')}
                    value={createTitleDraft}
                    onChange={(event) => setCreateTitleDraft(event.target.value)}
                    className="border-[hsl(var(--memory-input-border)/0.68)] bg-[hsl(var(--memory-input-bg))]"
                  />
                </label>

                <div className="flex items-center justify-between gap-2 text-xs text-[hsl(var(--memory-muted))]">
                  <span>{t('memory.episodes.create.sourceCount', { count: createCandidates.length })}</span>
                  <span>{t('memory.episodes.create.selectedCount', { count: selectedEpisodeIds.size })}</span>
                </div>

                {createLoading ? (
                  <div className={MEMORY_INFO_PANEL_CLASS}>
                    <Loader2 className="mr-2 inline h-4 w-4 animate-spin" aria-hidden="true" />
                    {t('memory.episodes.create.loading')}
                  </div>
                ) : createCandidates.length === 0 ? (
                  <div className={MEMORY_EMPTY_PANEL_CLASS}>{t('memory.episodes.create.empty')}</div>
                ) : (
                  <div className="max-h-[22rem] space-y-2 overflow-y-auto pr-1">
                    {createCandidates.map((episode, index) => {
                      const title = getEpisodeDisplayTitle(episode, t('memory.episodes.sourceEpisodeFallback', { index: index + 1 }));
                      const description = getEpisodeCandidateDescription(episode);
                      const checked = selectedEpisodeIds.has(episode.episode_id);
                      const range = formatEpisodeTimeRange(episode.time_start, episode.time_end, i18n.language);
                      return (
                        <label
                          key={episode.episode_id}
                          className="flex cursor-pointer gap-3 rounded-lg border border-[hsl(var(--memory-border)/0.48)] bg-[hsl(var(--memory-panel-elevated)/0.62)] px-3 py-3 transition-colors hover:bg-[hsl(var(--memory-panel-subtle)/0.5)]"
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => toggleCreateCandidate(episode.episode_id)}
                            className="mt-1 h-4 w-4 rounded border-[hsl(var(--memory-input-border))]"
                          />
                          <span className="min-w-0 flex-1">
                            <span className="block break-words text-sm font-medium text-[hsl(var(--memory-title))]">{title}</span>
                            {description ? (
                              <span className="mt-1 line-clamp-2 block text-sm leading-6 text-[hsl(var(--memory-body))]">{description}</span>
                            ) : null}
                            <span className="mt-1 block text-xs text-[hsl(var(--memory-muted))]">
                              {[range, t('memory.episodes.eventCount', { count: episode.source_event_count ?? 0 })].filter(Boolean).join(' · ')}
                            </span>
                          </span>
                        </label>
                      );
                    })}
                  </div>
                )}
                {createError ? (
                  <div className="rounded-md border border-destructive/20 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                    {createError}
                  </div>
                ) : null}
              </div>
              <DialogFooter>
                <Button variant="ghost" onClick={() => setCreateOpen(false)} disabled={createSaving}>
                  {t('common.cancel')}
                </Button>
                <Button onClick={() => { void createExperience(); }} disabled={createSaving || selectedEpisodeIds.size === 0}>
                  {createSaving ? t('common.saving') : t('memory.episodes.actions.createExperienceSubmit')}
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
