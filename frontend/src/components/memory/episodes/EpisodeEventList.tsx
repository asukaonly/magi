import { GitMerge } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { L2EpisodeEventPreview } from '@/api/modules/memory';

const formatEventTime = (value: number | null | undefined, locale: string): string => {
  if (typeof value !== 'number') {
    return '';
  }
  return new Intl.DateTimeFormat(locale, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value * 1000));
};

export function EpisodeEventList({
  events,
  selectable = false,
  selectedEventIds = new Set<string>(),
  onToggleEvent,
}: {
  events: L2EpisodeEventPreview[];
  selectable?: boolean;
  selectedEventIds?: Set<string>;
  onToggleEvent?: (eventId: string) => void;
}) {
  const { t, i18n } = useTranslation('app');

  return (
    <section>
      <h3 className="flex items-center gap-2 text-sm font-semibold text-[hsl(var(--memory-title))]">
        <GitMerge className="h-4 w-4 text-[hsl(var(--memory-accent))]" aria-hidden="true" />
        {t('memory.episodes.sections.whatHappened')}
      </h3>
      <div data-testid="episode-event-stream" className="mt-3 overflow-hidden rounded-xl border border-[hsl(var(--memory-border)/0.52)]">
        {events.length === 0 ? (
          <div className="px-4 py-3 text-sm text-[hsl(var(--memory-muted))]">{t('memory.episodes.noEvents')}</div>
        ) : events.map((event) => {
          const time = formatEventTime(event.timestamp ?? event.added_at, i18n.language);
          const preview = String(event.content_preview || event.event_id || '').trim();
          return (
            <article key={`${event.episode_id}-${event.event_id}`} className="border-t border-[hsl(var(--memory-divider)/0.54)] px-4 py-3 first:border-t-0">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <label className="flex items-start gap-3">
                    {selectable ? (
                      <input
                        type="checkbox"
                        checked={selectedEventIds.has(event.event_id)}
                        onChange={() => onToggleEvent?.(event.event_id)}
                        className="mt-1"
                      />
                    ) : null}
                    <span className="whitespace-pre-wrap break-words text-sm leading-6 text-[hsl(var(--memory-body))]">{preview}</span>
                  </label>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-[hsl(var(--memory-muted))]">
                    {event.source ? <span>{event.source}</span> : null}
                    {event.event_type ? <span>{event.event_type}</span> : null}
                    <span className="break-all font-mono">{event.event_id}</span>
                  </div>
                </div>
                {time ? <div className="shrink-0 text-xs text-[hsl(var(--memory-muted))]">{time}</div> : null}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

export default EpisodeEventList;
