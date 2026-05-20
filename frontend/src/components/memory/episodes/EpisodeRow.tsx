import { useTranslation } from 'react-i18next';
import { Pin, PinOff, Pencil, MessageSquare, Trash2 } from 'lucide-react';
import type { L2Episode } from '@/api/modules/memory';
import { Button } from '@/components/ui/button';

interface EpisodeRowProps {
  episode: L2Episode;
  onTogglePin: () => void;
  onRename: () => void;
  onAnnotate: () => void;
  onForget: () => void;
}

export const EpisodeRow = ({ episode, onTogglePin, onRename, onAnnotate, onForget }: EpisodeRowProps) => {
  const { t, i18n } = useTranslation('app');
  const title = episode.user_label || episode.label || (episode.summary ? episode.summary.slice(0, 80) : episode.episode_id);
  const range = episode.time_start && episode.time_end
    ? `${new Date(episode.time_start * 1000).toLocaleDateString(i18n.language)} → ${new Date(episode.time_end * 1000).toLocaleDateString(i18n.language)}`
    : '';

  return (
    <div className="flex items-center justify-between gap-3 rounded-2xl border border-[hsl(var(--memory-border)/0.5)] bg-[hsl(var(--memory-panel-elevated)/0.7)] px-4 py-3">
      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold text-[hsl(var(--memory-title))]">{title}</div>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-[hsl(var(--memory-muted))]">
          <span>{t(`memory.episodes.filters.${episode.episode_type}`, { defaultValue: episode.episode_type })}</span>
          {range ? <span>{range}</span> : null}
          {episode.user_note ? <span>· {t('memory.episodes.actions.annotate')}</span> : null}
        </div>
      </div>
      <div className="flex items-center gap-1">
        <Button variant="ghost" size="sm" onClick={onTogglePin}
          aria-label={t(episode.user_pinned ? 'memory.episodes.actions.unpin' : 'memory.episodes.actions.pin')}>
          {episode.user_pinned ? <PinOff className="h-4 w-4" /> : <Pin className="h-4 w-4" />}
        </Button>
        <Button variant="ghost" size="sm" onClick={onRename} aria-label={t('memory.episodes.actions.rename')}>
          <Pencil className="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="sm" onClick={onAnnotate} aria-label={t('memory.episodes.actions.annotate')}>
          <MessageSquare className="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="sm" onClick={onForget} aria-label={t('memory.episodes.actions.forget')}>
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
};

export default EpisodeRow;
