import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { memoryApi, type L2Episode } from '@/api/modules/memory';
import EpisodeRow from '@/components/memory/episodes/EpisodeRow';
import MemoryPageFrame, { MEMORY_EMPTY_PANEL_CLASS } from './MemoryPageFrame';

export const MemoryEpisodesPage = () => {
  const { t } = useTranslation('app');
  const [episodes, setEpisodes] = useState<L2Episode[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await memoryApi.listEpisodes({ status: 'active', limit: 100, offset: 0 });
      setEpisodes(payload.items);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const pinned = useMemo(() => episodes.filter((e) => e.user_pinned), [episodes]);
  const recent = useMemo(() => episodes.filter((e) => !e.user_pinned), [episodes]);

  const togglePin = async (ep: L2Episode) => {
    await memoryApi.annotateEpisode(ep.episode_id, { user_pinned: !ep.user_pinned });
    setEpisodes((prev) => prev.map((it) => (it.episode_id === ep.episode_id ? { ...it, user_pinned: !ep.user_pinned } : it)));
  };

  const forget = async (ep: L2Episode) => {
    await memoryApi.forgetEpisode(ep.episode_id, false);
    setEpisodes((prev) => prev.filter((it) => it.episode_id !== ep.episode_id));
  };

  const renameOrAnnotate = async (ep: L2Episode, field: 'user_label' | 'user_note') => {
    const initial = (ep[field] as string | null) ?? '';
    const next = window.prompt(t(`memory.episodes.actions.${field === 'user_label' ? 'rename' : 'annotate'}`), initial);
    if (next === null) return;
    await memoryApi.annotateEpisode(ep.episode_id, { [field]: next });
    setEpisodes((prev) => prev.map((it) => (it.episode_id === ep.episode_id ? { ...it, [field]: next } as L2Episode : it)));
  };

  return (
    <MemoryPageFrame title={t('memory.episodes.title')} description={t('memory.episodes.subtitle')}>
      {loading ? null : episodes.length === 0 ? (
        <div className={MEMORY_EMPTY_PANEL_CLASS}>
          <div className="font-semibold text-[hsl(var(--memory-title))]">{t('memory.episodes.emptyTitle')}</div>
          <p className="mt-1 text-sm">{t('memory.episodes.emptyBody')}</p>
        </div>
      ) : (
        <>
          <section data-testid="episodes-pinned" className="space-y-2">
            <h2 className="text-sm font-medium text-[hsl(var(--memory-muted))]">{t('memory.episodes.pinnedSection')}</h2>
            {pinned.length === 0 ? (
              <div className="text-xs text-[hsl(var(--memory-muted))]">—</div>
            ) : (
              pinned.map((ep) => (
                <EpisodeRow
                  key={ep.episode_id}
                  episode={ep}
                  onTogglePin={() => void togglePin(ep)}
                  onRename={() => void renameOrAnnotate(ep, 'user_label')}
                  onAnnotate={() => void renameOrAnnotate(ep, 'user_note')}
                  onForget={() => void forget(ep)}
                />
              ))
            )}
          </section>

          <section data-testid="episodes-recent" className="mt-6 space-y-2">
            <h2 className="text-sm font-medium text-[hsl(var(--memory-muted))]">{t('memory.episodes.recentSection')}</h2>
            {recent.map((ep) => (
              <EpisodeRow
                key={ep.episode_id}
                episode={ep}
                onTogglePin={() => void togglePin(ep)}
                onRename={() => void renameOrAnnotate(ep, 'user_label')}
                onAnnotate={() => void renameOrAnnotate(ep, 'user_note')}
                onForget={() => void forget(ep)}
              />
            ))}
          </section>
        </>
      )}
    </MemoryPageFrame>
  );
};

export default MemoryEpisodesPage;
