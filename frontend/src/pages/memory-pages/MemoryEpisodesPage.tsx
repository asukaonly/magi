import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  memoryApi,
  type L2Episode,
  type L2EpisodeReviewDetail,
  type L2EpisodeWithSummary,
} from '@/api/modules/memory';
import EpisodeDetail from '@/components/memory/episodes/EpisodeDetail';
import EpisodeRow, { getEpisodeDisplayTitle } from '@/components/memory/episodes/EpisodeRow';
import { Badge } from '@/components/ui/badge';
import MemoryPageFrame, { MEMORY_EMPTY_PANEL_CLASS, MEMORY_INFO_PANEL_CLASS } from './MemoryPageFrame';

export const MemoryEpisodesPage = () => {
  const { t } = useTranslation('app');
  const [episodes, setEpisodes] = useState<L2EpisodeWithSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<L2EpisodeReviewDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await memoryApi.listEpisodes({ limit: 100, offset: 0 });
      setEpisodes(payload.items);
      setSelectedId((current) => {
        if (current && payload.items.some((item) => item.episode_id === current)) {
          return current;
        }
        return payload.items[0]?.episode_id ?? null;
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
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
  }, [selectedId]);

  const selectedListEpisode = useMemo(
    () => episodes.find((episode) => episode.episode_id === selectedId) ?? null,
    [episodes, selectedId]
  );
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
  }, [selectedEpisode]);

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
        </div>
      ) : (
        <div className="grid min-h-0 gap-4 lg:grid-cols-[minmax(280px,420px)_minmax(0,1fr)]">
          <section className="min-w-0 space-y-3">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-sm font-semibold text-[hsl(var(--memory-title))]">
                {t('memory.episodes.sections.list')}
              </h2>
              <Badge variant="outline" className="rounded-md border-[hsl(var(--memory-tag-border))] bg-[hsl(var(--memory-tag-bg)/0.76)] text-[hsl(var(--memory-muted))]">
                {t('memory.episodes.count', { count: episodes.length })}
              </Badge>
            </div>
            <div className="space-y-2">
              {episodes.map((episode) => (
                <EpisodeRow
                  key={episode.episode_id}
                  episode={episode}
                  selected={episode.episode_id === selectedId}
                  onOpen={() => setSelectedId(episode.episode_id)}
                />
              ))}
            </div>
          </section>

          <section className="min-w-0 rounded-2xl border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-elevated)/0.7)]">
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
              <div className={MEMORY_EMPTY_PANEL_CLASS}>
                <div className="font-semibold text-[hsl(var(--memory-title))]">{t('memory.episodes.detailEmptyTitle')}</div>
                <p className="mt-1 text-sm">{t('memory.episodes.detailEmptyBody')}</p>
              </div>
            )}
          </section>
        </div>
      )}
    </MemoryPageFrame>
  );
};

export default MemoryEpisodesPage;
