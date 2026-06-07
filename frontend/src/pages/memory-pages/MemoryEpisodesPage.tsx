import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { memoryApi, type L2EpisodeWithSummary } from '@/api/modules/memory';
import EpisodeRow from '@/components/memory/episodes/EpisodeRow';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import MemoryPageFrame, { MEMORY_EMPTY_PANEL_CLASS } from './MemoryPageFrame';

type DialogState = { episode: L2EpisodeWithSummary; field: 'user_label' | 'user_note'; value: string } | null;

export const MemoryEpisodesPage = () => {
  const { t } = useTranslation('app');
  const [episodes, setEpisodes] = useState<L2EpisodeWithSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogState, setDialogState] = useState<DialogState>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await memoryApi.listEpisodes({ surface: 'standout', limit: 100, offset: 0 });
      setEpisodes(payload.items);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const pinned = useMemo(() => episodes.filter((e) => e.user_pinned), [episodes]);
  const recent = useMemo(() => episodes.filter((e) => !e.user_pinned), [episodes]);

  const togglePin = async (ep: L2EpisodeWithSummary) => {
    await memoryApi.annotateEpisode(ep.episode_id, { user_pinned: !ep.user_pinned });
    setEpisodes((prev) => prev.map((it) => (it.episode_id === ep.episode_id ? { ...it, user_pinned: !ep.user_pinned } : it)));
  };

  const forget = async (ep: L2EpisodeWithSummary) => {
    await memoryApi.forgetEpisode(ep.episode_id, false);
    setEpisodes((prev) => prev.filter((it) => it.episode_id !== ep.episode_id));
  };

  const openRename = (ep: L2EpisodeWithSummary) => setDialogState({
    episode: ep, field: 'user_label', value: ep.user_label ?? '',
  });

  const openAnnotate = (ep: L2EpisodeWithSummary) => setDialogState({
    episode: ep, field: 'user_note', value: ep.user_note ?? '',
  });

  const handleDialogSave = async () => {
    if (!dialogState) return;
    const { episode, field, value } = dialogState;
    await memoryApi.annotateEpisode(episode.episode_id, { [field]: value });
    setEpisodes((prev) => prev.map((it) =>
      it.episode_id === episode.episode_id ? ({ ...it, [field]: value } as L2EpisodeWithSummary) : it
    ));
    setDialogState(null);
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
                  onRename={() => openRename(ep)}
                  onAnnotate={() => openAnnotate(ep)}
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
                onRename={() => openRename(ep)}
                onAnnotate={() => openAnnotate(ep)}
                onForget={() => void forget(ep)}
              />
            ))}
          </section>
        </>
      )}

      <Dialog open={dialogState !== null} onOpenChange={(open) => { if (!open) setDialogState(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {dialogState?.field === 'user_label'
                ? t('memory.episodes.actions.rename')
                : t('memory.episodes.actions.annotate')}
            </DialogTitle>
          </DialogHeader>
          {dialogState?.field === 'user_label' ? (
            <Input
              value={dialogState.value}
              onChange={(event) => setDialogState({ ...dialogState, value: event.target.value })}
              autoFocus
            />
          ) : (
            <textarea
              value={dialogState?.value ?? ''}
              onChange={(event) => dialogState && setDialogState({ ...dialogState, value: event.target.value })}
              rows={4}
              autoFocus
              className="w-full rounded-sm border border-[hsl(var(--memory-input-border)/0.7)] bg-[hsl(var(--memory-input-bg))] px-3 py-2 text-sm"
            />
          )}
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDialogState(null)}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button onClick={() => void handleDialogSave()}>
              {t('common.save', { defaultValue: 'Save' })}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </MemoryPageFrame>
  );
};

export default MemoryEpisodesPage;
