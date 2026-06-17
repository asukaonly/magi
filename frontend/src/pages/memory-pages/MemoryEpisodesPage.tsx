import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  memoryApi,
  type EpisodeReconsolidateResult,
  type L2Episode,
  type L2EpisodeReviewDetail,
  type L2EpisodeWithSummary,
} from '@/api/modules/memory';
import EpisodeDetail from '@/components/memory/episodes/EpisodeDetail';
import EpisodeRow, { getEpisodeDisplayTitle } from '@/components/memory/episodes/EpisodeRow';
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

const CHAPTER_MIN_EVENTS = 8;
const CHAPTER_MIN_SECONDS = 45 * 60;
const CHAPTER_DENSE_EVENTS = 20;

const isReadableChapter = (episode: L2EpisodeWithSummary): boolean => {
  if (episode.user_pinned) {
    return true;
  }
  const eventCount = Number(episode.source_event_count || 0);
  const start = typeof episode.time_start === 'number' ? episode.time_start : null;
  const end = typeof episode.time_end === 'number' ? episode.time_end : null;
  const duration = start !== null && end !== null ? Math.max(0, end - start) : 0;
  return eventCount >= CHAPTER_MIN_EVENTS && (
    duration >= CHAPTER_MIN_SECONDS || eventCount >= CHAPTER_DENSE_EVENTS
  );
};

export const MemoryEpisodesPage = () => {
  const { t } = useTranslation('app');
  const [episodes, setEpisodes] = useState<L2EpisodeWithSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detail, setDetail] = useState<L2EpisodeReviewDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [reconsolidating, setReconsolidating] = useState(false);
  const [reconsolidateResult, setReconsolidateResult] = useState<EpisodeReconsolidateResult | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await memoryApi.listEpisodes({ surface: 'standout', limit: 100, offset: 0 });
      setEpisodes(payload.items);
      setSelectedId((current) => {
        if (current && payload.items.some((item) => item.episode_id === current)) {
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
    void memoryApi.getEpisode(selectedId)
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

  const selectedListEpisode = useMemo(
    () => episodes.find((episode) => episode.episode_id === selectedId) ?? null,
    [episodes, selectedId]
  );
  const visibleEpisodes = useMemo(() => {
    const chapters = episodes.filter(isReadableChapter);
    return chapters.length > 0 ? chapters : episodes;
  }, [episodes]);
  const selectedEpisode = detail ?? selectedListEpisode;
  const selectedTitle = selectedEpisode
    ? getEpisodeDisplayTitle(selectedEpisode, t('memory.episodes.awaitingLabel'))
    : '';

  const applyEpisodeUpdate = useCallback((updated: L2Episode | L2EpisodeReviewDetail) => {
    setEpisodes((prev) => prev.map((item) => (
      item.episode_id === updated.episode_id
        ? { ...item, ...updated }
        : item
    )));
    setDetail((prev) => (
      prev && prev.episode_id === updated.episode_id
        ? { ...prev, ...updated }
        : prev
    ));
  }, []);

  const applyReviewDetail = useCallback((updated: L2EpisodeReviewDetail) => {
    setEpisodes((prev) => {
      const exists = prev.some((item) => item.episode_id === updated.episode_id);
      if (exists) {
        return prev.map((item) => (
          item.episode_id === updated.episode_id ? { ...item, ...updated } : item
        ));
      }
      return [updated, ...prev];
    });
    setSelectedId(updated.episode_id);
    setDetail(updated);
    setDetailOpen(true);
  }, []);

  const applySplitResult = useCallback((items: L2EpisodeReviewDetail[]) => {
    const first = items[0];
    if (!first || !selectedEpisode) {
      return;
    }
    setEpisodes((prev) => [
      ...items,
      ...prev.filter((item) => item.episode_id !== selectedEpisode.episode_id),
    ]);
    setSelectedId(first.episode_id);
    setDetail(first);
    setDetailOpen(true);
  }, [selectedEpisode]);

  const openEpisode = (episodeId: string) => {
    setSelectedId(episodeId);
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

  const renameSelectedEpisode = async (title: string) => {
    if (!selectedEpisode) {
      return;
    }
    const updated = await memoryApi.annotateEpisode(selectedEpisode.episode_id, {
      user_label: title,
    });
    applyEpisodeUpdate({
      ...updated,
      display_title: updated.user_label || title,
    } as L2EpisodeReviewDetail);
  };

  const editSelectedDescription = async (description: string) => {
    if (!selectedEpisode) {
      return;
    }
    const updated = await memoryApi.annotateEpisode(selectedEpisode.episode_id, {
      user_note: description,
    });
    applyEpisodeUpdate({
      ...updated,
      display_description: updated.user_note || description,
    } as L2EpisodeReviewDetail);
  };

  const regenerateSelectedDescription = async () => {
    if (!selectedEpisode) {
      return;
    }
    const updated = await memoryApi.regenerateEpisode(selectedEpisode.episode_id);
    applyEpisodeUpdate(updated);
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
      contentClassName="min-h-0"
    >
      {loading ? (
        <div className={MEMORY_INFO_PANEL_CLASS}>{t('common.loading')}</div>
      ) : episodes.length === 0 ? (
        <div className={MEMORY_EMPTY_PANEL_CLASS}>
          <div className="font-semibold text-[hsl(var(--memory-title))]">{t('memory.episodes.emptyTitle')}</div>
          <p className="mt-1 text-sm">{t('memory.episodes.emptyBody')}</p>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <Button onClick={reconsolidateEpisodes} disabled={reconsolidating}>
              {reconsolidating
                ? t('memory.episodes.actions.reconsolidating')
                : t('memory.episodes.actions.reconsolidate')}
            </Button>
            {reconsolidateResult ? (
              <span className="text-xs text-[hsl(var(--memory-muted))]">
                {t('memory.episodes.reconsolidateResult', {
                  promoted: reconsolidateResult.promoted,
                  standouts: reconsolidateResult.standouts,
                  summaries: reconsolidateResult.summaries_generated,
                })}
              </span>
            ) : null}
          </div>
        </div>
      ) : (
        <>
          <section className="min-w-0 space-y-3">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-sm font-semibold text-[hsl(var(--memory-title))]">
                {t('memory.episodes.sections.list')}
              </h2>
              <Badge variant="outline" className="rounded-md border-[hsl(var(--memory-tag-border))] bg-[hsl(var(--memory-tag-bg)/0.76)] text-[hsl(var(--memory-muted))]">
                {t('memory.episodes.count', { count: visibleEpisodes.length })}
              </Badge>
            </div>
            <div className="grid auto-rows-fr gap-3 md:grid-cols-2 xl:grid-cols-3">
              {visibleEpisodes.map((episode) => (
                <EpisodeRow
                  key={episode.episode_id}
                  episode={episode}
                  selected={episode.episode_id === selectedId}
                  onOpen={() => openEpisode(episode.episode_id)}
                />
              ))}
            </div>
          </section>

          <Sheet open={detailOpen} onOpenChange={handleDetailOpenChange}>
            <SheetContent
              side="right"
              className="w-[min(96vw,880px)] max-w-[880px] overflow-y-auto border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-elevated))] p-0"
            >
              <SheetHeader className="sr-only">
                <SheetTitle>{selectedTitle || t('memory.episodes.sections.detail')}</SheetTitle>
                <SheetDescription>{t('memory.episodes.detailEmptyBody')}</SheetDescription>
              </SheetHeader>
              {selectedEpisode ? (
                <EpisodeDetail
                  episode={selectedEpisode}
                  title={selectedTitle}
                  detailLoading={detailLoading}
                  onRenameTitle={renameSelectedEpisode}
                  onEditDescription={editSelectedDescription}
                  onRegenerate={regenerateSelectedDescription}
                  onEpisodeUpdated={applyReviewDetail}
                  onEpisodeSplit={applySplitResult}
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
