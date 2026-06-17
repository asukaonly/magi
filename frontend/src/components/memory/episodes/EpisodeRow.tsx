import { CalendarRange, Pin } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { L2Episode, L2EpisodeWithSummary } from '@/api/modules/memory';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

interface EpisodeRowProps {
  episode: L2Episode;
  selected: boolean;
  onOpen: () => void;
}

export const formatEpisodeTimeRange = (
  start: number | null | undefined,
  end: number | null | undefined,
  locale: string
): string => {
  if (!start && !end) {
    return '';
  }
  const formatter = new Intl.DateTimeFormat(locale, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
  if (start && end) {
    return `${formatter.format(new Date(start * 1000))} - ${formatter.format(new Date(end * 1000))}`;
  }
  return formatter.format(new Date((start ?? end ?? 0) * 1000));
};

export const getEpisodeDisplayTitle = (episode: L2Episode | L2EpisodeWithSummary, fallback: string): string => {
  const values = [
    episode.user_label,
    (episode as L2EpisodeWithSummary).display_title,
    (episode as L2EpisodeWithSummary).episode_summary?.label,
    episode.label,
    episode.summary,
    episode.slice_narrative,
    episode.episode_id,
  ];
  return values.find((value) => typeof value === 'string' && value.trim())?.trim() ?? fallback;
};

const getEpisodeSummary = (episode: L2Episode | L2EpisodeWithSummary): string => {
  const summary = String(
    episode.user_note ||
    (episode as L2EpisodeWithSummary).display_description ||
    (episode as L2EpisodeWithSummary).episode_summary?.content ||
    episode.summary ||
    episode.slice_narrative ||
    ''
  ).trim();
  return summary.length > 180 ? `${summary.slice(0, 177)}...` : summary;
};

export const EpisodeRow = ({ episode, selected, onOpen }: EpisodeRowProps) => {
  const { t, i18n } = useTranslation('app');
  const title = getEpisodeDisplayTitle(episode, t('memory.episodes.awaitingLabel'));
  const summary = getEpisodeSummary(episode);
  const range = formatEpisodeTimeRange(episode.time_start, episode.time_end, i18n.language);
  const typeLabel = t(`memory.episodes.filters.${episode.episode_type || 'activity'}`, {
    defaultValue: episode.episode_type || '',
  });

  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label={`${t('memory.episodes.actions.open')}: ${title}`}
      className={cn(
        'group w-full rounded-xl border px-4 py-3 text-left transition-colors duration-200',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--memory-accent)/0.24)]',
        selected
          ? 'border-[hsl(var(--memory-accent)/0.46)] bg-[hsl(var(--memory-accent-soft)/0.64)]'
          : 'border-[hsl(var(--memory-border)/0.54)] bg-[hsl(var(--memory-panel-elevated)/0.72)] hover:border-[hsl(var(--memory-accent)/0.26)] hover:bg-[hsl(var(--memory-panel-elevated)/0.9)]'
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="break-words text-sm font-semibold leading-5 text-[hsl(var(--memory-title))]">{title}</span>
            {episode.user_pinned ? (
              <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-[hsl(var(--memory-panel-elevated)/0.86)] text-[hsl(var(--memory-accent))]">
                <Pin className="h-3.5 w-3.5" aria-hidden="true" />
              </span>
            ) : null}
          </div>
          {summary ? (
            <p className="mt-1 line-clamp-2 text-sm leading-5 text-[hsl(var(--memory-body))]">{summary}</p>
          ) : null}
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-[hsl(var(--memory-muted))]">
            {typeLabel ? (
              <Badge variant="outline" className="rounded-md border-[hsl(var(--memory-tag-border))] bg-[hsl(var(--memory-tag-bg)/0.74)] font-normal text-[hsl(var(--memory-body))]">
                {typeLabel}
              </Badge>
            ) : null}
            {range ? (
              <span className="inline-flex min-w-0 items-center gap-1">
                <CalendarRange className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                <span className="truncate">{range}</span>
              </span>
            ) : null}
          </div>
        </div>
        <div className="shrink-0 text-xs tabular-nums text-[hsl(var(--memory-muted))]">
          {episode.source_event_count ?? 0}
        </div>
      </div>
    </button>
  );
};

export default EpisodeRow;
