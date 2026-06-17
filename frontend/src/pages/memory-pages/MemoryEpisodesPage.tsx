import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  memoryApi,
  type EpisodeReconsolidateResult,
  type L2ExperienceReviewDetail,
  type L2ExperienceWithReview,
} from '@/api/modules/memory';
import ExperienceDetail from '@/components/memory/experiences/ExperienceDetail';
import ExperienceRow, { getExperienceDisplayTitle } from '@/components/memory/experiences/ExperienceRow';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import MemoryPageFrame, { MEMORY_EMPTY_PANEL_CLASS, MEMORY_INFO_PANEL_CLASS } from './MemoryPageFrame';

const getExperienceReviewTimestamp = (experience: L2ExperienceWithReview): number => Math.max(
  Number(experience.updated_at ?? 0),
  Number(experience.experience_review?.updated_at ?? 0),
  Number(experience.time_end ?? 0),
  Number(experience.time_start ?? 0),
  0
);

export const sortExperiencesForReview = (
  items: L2ExperienceWithReview[]
): L2ExperienceWithReview[] => [...items].sort((a, b) => {
  if (Boolean(a.user_pinned) !== Boolean(b.user_pinned)) {
    return a.user_pinned ? -1 : 1;
  }
  const updatedDiff = getExperienceReviewTimestamp(b) - getExperienceReviewTimestamp(a);
  if (updatedDiff !== 0) {
    return updatedDiff;
  }
  return Number(b.narrative_score ?? 0) - Number(a.narrative_score ?? 0);
});

export const MemoryEpisodesPage = () => {
  const { t } = useTranslation('app');
  const [experiences, setExperiences] = useState<L2ExperienceWithReview[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detail, setDetail] = useState<L2ExperienceReviewDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [reconsolidating, setReconsolidating] = useState(false);
  const [reconsolidateResult, setReconsolidateResult] = useState<EpisodeReconsolidateResult | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await memoryApi.listExperiences({ status: 'active', limit: 100, offset: 0 });
      setExperiences(payload.items);
      setSelectedId((current) => {
        if (current && payload.items.some((item) => item.experience_id === current)) {
          return current;
        }
        return null;
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!detailOpen || !selectedId) {
      setDetail(null);
      setDetailLoading(false);
      return;
    }
    let cancelled = false;
    setDetail(null);
    setDetailLoading(true);
    void memoryApi.getExperience(selectedId)
      .then((payload) => {
        if (!cancelled) {
          setDetail(payload);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setDetailLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [detailOpen, selectedId]);

  const selectedListExperience = useMemo(
    () => experiences.find((experience) => experience.experience_id === selectedId) ?? null,
    [experiences, selectedId]
  );
  const sortedExperiences = useMemo(() => sortExperiencesForReview(experiences), [experiences]);
  const selectedExperience = detail ?? selectedListExperience;
  const selectedTitle = selectedExperience
    ? getExperienceDisplayTitle(selectedExperience, t('memory.episodes.awaitingLabel'))
    : '';

  const applyExperienceUpdate = useCallback((updated: L2ExperienceReviewDetail) => {
    setExperiences((prev) => prev.map((item) => (
      item.experience_id === updated.experience_id
        ? { ...item, ...updated }
        : item
    )));
    setDetail((prev) => (
      prev && prev.experience_id === updated.experience_id
        ? { ...prev, ...updated }
        : prev
    ));
  }, []);

  const openExperience = (experienceId: string) => {
    setSelectedId(experienceId);
    setDetailOpen(true);
  };

  const handleDetailOpenChange = (open: boolean) => {
    setDetailOpen(open);
    if (!open) {
      setSelectedId(null);
      setDetail(null);
      setDetailLoading(false);
    }
  };

  const renameSelectedExperience = async (title: string) => {
    if (!selectedExperience) {
      return;
    }
    const updated = await memoryApi.annotateExperience(selectedExperience.experience_id, {
      user_label: title,
    });
    applyExperienceUpdate({
      ...updated,
      display_title: updated.user_label || title,
    });
  };

  const editSelectedDescription = async (description: string) => {
    if (!selectedExperience) {
      return;
    }
    const updated = await memoryApi.annotateExperience(selectedExperience.experience_id, {
      user_note: description,
    });
    applyExperienceUpdate({
      ...updated,
      display_description: updated.user_note || description,
    });
  };

  const regenerateSelectedDescription = async () => {
    if (!selectedExperience) {
      return;
    }
    const updated = await memoryApi.regenerateExperienceReview(selectedExperience.experience_id);
    applyExperienceUpdate(updated);
  };

  const hideSelectedExperience = async () => {
    if (!selectedExperience) {
      return;
    }
    const hiddenId = selectedExperience.experience_id;
    await memoryApi.hideExperience(hiddenId);
    setExperiences((prev) => prev.filter((item) => item.experience_id !== hiddenId));
    setDetailOpen(false);
    setSelectedId(null);
    setDetail(null);
  };

  const reconsolidateEpisodes = async () => {
    setReconsolidating(true);
    try {
      const result = await memoryApi.reconsolidateEpisodes();
      setReconsolidateResult(result);
      await refresh();
    } finally {
      setReconsolidating(false);
    }
  };

  return (
    <MemoryPageFrame
      title={t('memory.episodes.title')}
      description={t('memory.episodes.subtitle')}
      actions={(
        <Button variant="outline" onClick={reconsolidateEpisodes} disabled={reconsolidating}>
          {reconsolidating
            ? t('memory.episodes.actions.reconsolidating')
            : t('memory.episodes.actions.reconsolidate')}
        </Button>
      )}
      headerMeta={reconsolidateResult ? (
        <span className="text-xs text-[hsl(var(--memory-muted))]">
          {t('memory.episodes.reconsolidateResult', {
            promoted: reconsolidateResult.promoted,
            standouts: reconsolidateResult.standouts,
            summaries: reconsolidateResult.summaries_generated,
          })}
        </span>
      ) : null}
      contentClassName="min-h-0"
    >
      {loading ? (
        <div className={MEMORY_INFO_PANEL_CLASS}>{t('common.loading')}</div>
      ) : experiences.length === 0 ? (
        <div className={MEMORY_EMPTY_PANEL_CLASS}>
          <div className="font-semibold text-[hsl(var(--memory-title))]">{t('memory.episodes.emptyTitle')}</div>
          <p className="mt-1 text-sm">{t('memory.episodes.emptyBody')}</p>
        </div>
      ) : (
        <>
          <section className="min-w-0 space-y-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
              <div className="space-y-1">
                <h2 className="text-sm font-semibold text-[hsl(var(--memory-title))]">
                  {t('memory.episodes.sections.list')}
                </h2>
                <p className="text-xs text-[hsl(var(--memory-muted))]">
                  {t('memory.episodes.sortNote')}
                </p>
              </div>
              <Badge variant="outline" className="w-fit rounded-md border-[hsl(var(--memory-tag-border))] bg-[hsl(var(--memory-tag-bg)/0.76)] text-[hsl(var(--memory-muted))]">
                {t('memory.episodes.count', { count: sortedExperiences.length })}
              </Badge>
            </div>
            <div className="grid auto-rows-fr gap-4 md:grid-cols-2 xl:grid-cols-3">
              {sortedExperiences.map((experience) => (
                <ExperienceRow
                  key={experience.experience_id}
                  experience={experience}
                  selected={experience.experience_id === selectedId}
                  onOpen={() => openExperience(experience.experience_id)}
                />
              ))}
            </div>
          </section>

          <Sheet open={detailOpen} onOpenChange={handleDetailOpenChange}>
            <SheetContent
              side="right"
              className="w-[100vw] max-w-[1120px] overflow-y-auto rounded-l-2xl border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-elevated))] p-0 sm:w-[min(94vw,1120px)]"
            >
              <SheetHeader className="sr-only">
                <SheetTitle>{selectedTitle || t('memory.episodes.sections.detail')}</SheetTitle>
                <SheetDescription>{t('memory.episodes.detailEmptyBody')}</SheetDescription>
              </SheetHeader>
              {selectedExperience ? (
                <ExperienceDetail
                  experience={selectedExperience}
                  title={selectedTitle}
                  detailLoading={detailLoading}
                  onRenameTitle={renameSelectedExperience}
                  onEditDescription={editSelectedDescription}
                  onRegenerate={regenerateSelectedDescription}
                  onHide={hideSelectedExperience}
                />
              ) : (
                <div className={MEMORY_INFO_PANEL_CLASS}>{t('common.loading')}</div>
              )}
            </SheetContent>
          </Sheet>
        </>
      )}
    </MemoryPageFrame>
  );
};

export default MemoryEpisodesPage;
