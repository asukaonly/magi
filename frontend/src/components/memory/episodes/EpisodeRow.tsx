import { useTranslation } from 'react-i18next';
import { Pin, PinOff, Pencil, MessageSquare, Trash2 } from 'lucide-react';
import type { L2EpisodeWithSummary } from '@/api/modules/memory';
import { Button } from '@/components/ui/button';

interface EpisodeRowProps {
  episode: L2EpisodeWithSummary;
  onTogglePin: () => void;
  onRename: () => void;
  onAnnotate: () => void;
  onForget: () => void;
}

const formatTimeRange = (start: number | null | undefined, end: number | null | undefined, locale: string): string => {
  if (!start || !end) return '';
  const s = new Date(start * 1000);
  const e = new Date(end * 1000);
  const startStr = s.toLocaleString(locale, { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  const endStr = e.toLocaleString(locale, { hour: '2-digit', minute: '2-digit' });
  return `${startStr} – ${endStr}`;
};

const formatEntityList = (ids: string[] | null | undefined, limit: number = 3): string => {
  if (!ids || ids.length === 0) return '';
  const labels = ids
    .slice(0, limit)
    .map((id) => id.split(':').slice(-1)[0]);
  const extra = ids.length > limit ? ' 等' : '';
  return labels.join(' · ') + extra;
};

const buildFallbackTitle = (
  episode: L2EpisodeWithSummary,
  typeLabel: string,
  range: string,
): string => {
  const entities = formatEntityList(episode.primary_entity_ids);
  const count = `${episode.source_event_count ?? 0} 件事`;
  const parts = [typeLabel, range, entities, count].filter(Boolean);
  return parts.join(' · ');
};

export const EpisodeRow = ({ episode, onTogglePin, onRename, onAnnotate, onForget }: EpisodeRowProps) => {
  const { t, i18n } = useTranslation('app');
  const epSummary = episode.episode_summary ?? undefined;
  const range = formatTimeRange(episode.time_start, episode.time_end, i18n.language);
  const typeLabel = t(`memory.episodes.filters.${episode.episode_type}`, { defaultValue: episode.episode_type });

  // Title priority: user_label > L3 summary label > derived structured title
  const title = episode.user_label
    || epSummary?.label
    || buildFallbackTitle(episode, typeLabel, range);

  // Body priority: L3 summary content > nothing (just show meta line)
  const body = epSummary?.content ?? '';

  return (
    <div className="rounded-2xl border border-[hsl(var(--memory-border)/0.5)] bg-[hsl(var(--memory-panel-elevated)/0.7)] px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold text-[hsl(var(--memory-title))]">{title}</div>
          {body ? (
            <p className="mt-1 text-sm leading-5 text-[hsl(var(--memory-body))]">{body}</p>
          ) : (
            <div className="mt-1 text-xs text-[hsl(var(--memory-muted))]">
              {range || t('memory.episodes.awaitingLabel', { defaultValue: '等 Magi 起草标题...' })}
            </div>
          )}
          {body && range ? (
            <div className="mt-1 text-xs text-[hsl(var(--memory-muted))]">{range}</div>
          ) : null}
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
    </div>
  );
};

export default EpisodeRow;
