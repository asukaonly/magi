import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import {
  memoryApi,
  type L2ExperienceSeed,
  type L2ExperienceWithReview,
} from '@/api/modules/memory';
import { Badge } from '@/components/ui/badge';
import MemoryPageFrame, { MEMORY_EMPTY_PANEL_CLASS, MEMORY_INFO_PANEL_CLASS } from './MemoryPageFrame';
import { ExperienceTimeline } from './episodes/ExperienceTimeline';
import { PendingExperienceShelf } from './episodes/PendingExperienceShelf';
import { groupExperiencesByMonth, sortExperiencesForReview } from './episodes/experienceIndexModel';

export { sortExperiencesForReview } from './episodes/experienceIndexModel';
export { MemoryExperienceDetailPage } from './episodes/MemoryExperienceDetailPage';

export const MemoryEpisodesPage = () => {
  const { t, i18n } = useTranslation('app');
  const navigate = useNavigate();
  const [experiences, setExperiences] = useState<L2ExperienceWithReview[]>([]);
  const [experienceSeeds, setExperienceSeeds] = useState<L2ExperienceSeed[]>([]);
  const [loading, setLoading] = useState(true);
  const [seedActionId, setSeedActionId] = useState<string | null>(null);

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
        </section>
      )}
    </MemoryPageFrame>
  );
};

export default MemoryEpisodesPage;
