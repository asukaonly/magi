import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, ChevronUp, RotateCcw } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import {
  memoryApi,
  type ExperienceDraftChapter,
  type L2EpisodeEventPreview,
} from '@/api/modules/memory';
import { Button } from '@/components/ui/button';
import { formatEpisodeTimeRange } from '@/components/memory/episodes/EpisodeRow';

type ContentState = 'idle' | 'loading' | 'loaded' | 'failed';

interface EpisodeContentSnapshot {
  episodeIdsKey: string;
  state: ContentState;
  events: L2EpisodeEventPreview[];
}

interface ExperienceDraftSegmentCardProps {
  chapter: ExperienceDraftChapter;
  checkboxRef: (node: HTMLInputElement | null) => void;
  onRemove: () => void;
}

const formatEventTime = (timestamp: number | null | undefined, locale: string): string => {
  if (!timestamp) return '';
  return new Intl.DateTimeFormat(locale, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(timestamp * 1000));
};

const dedupeEpisodeEvents = (events: L2EpisodeEventPreview[]): L2EpisodeEventPreview[] => {
  const seen = new Set<string>();
  return events.filter((event) => {
    if (seen.has(event.event_id)) return false;
    seen.add(event.event_id);
    return true;
  });
};

export function ExperienceDraftSegmentCard({
  chapter,
  checkboxRef,
  onRemove,
}: ExperienceDraftSegmentCardProps) {
  const { t, i18n } = useTranslation('app');
  const [contentOpen, setContentOpen] = useState(false);
  const episodeIdsKey = chapter.episode_ids.join('\u0000');
  const requestGenerationRef = useRef(0);
  const [content, setContent] = useState<EpisodeContentSnapshot>({
    episodeIdsKey,
    state: episodeIdsKey ? 'loading' : 'idle',
    events: [],
  });
  const contentState = content.episodeIdsKey === episodeIdsKey
    ? content.state
    : episodeIdsKey ? 'loading' : 'idle';
  const events = content.episodeIdsKey === episodeIdsKey ? content.events : [];
  const timeRange = formatEpisodeTimeRange(chapter.time_start, chapter.time_end, i18n.language);
  const readableEvents = useMemo(
    () => events.filter((event) => String(event.content_preview || '').trim()),
    [events],
  );
  const eventCount = new Set([
    ...chapter.event_ids,
    ...events.map((event) => event.event_id),
  ]).size;

  const loadContent = useCallback(async () => {
    if (!episodeIdsKey) return;
    const episodeIds = episodeIdsKey.split('\u0000');
    const requestGeneration = requestGenerationRef.current + 1;
    requestGenerationRef.current = requestGeneration;
    setContent({ episodeIdsKey, state: 'loading', events: [] });
    try {
      const episodes = await Promise.all(episodeIds.map((episodeId) => memoryApi.getEpisode(episodeId)));
      if (requestGenerationRef.current !== requestGeneration) return;
      setContent({
        episodeIdsKey,
        state: 'loaded',
        events: dedupeEpisodeEvents(episodes.flatMap((episode) => episode.events ?? [])),
      });
    } catch {
      if (requestGenerationRef.current !== requestGeneration) return;
      setContent({ episodeIdsKey, state: 'failed', events: [] });
    }
  }, [episodeIdsKey]);

  useEffect(() => {
    if (episodeIdsKey) void loadContent();
    return () => {
      requestGenerationRef.current += 1;
    };
  }, [episodeIdsKey, loadContent]);

  const toggleContent = () => {
    setContentOpen((open) => !open);
  };

  return (
    <article className="overflow-hidden rounded-md border border-[hsl(var(--memory-accent)/0.34)] bg-[hsl(var(--memory-accent-soft)/0.22)] transition-colors focus-within:border-[hsl(var(--memory-accent)/0.58)]">
      <div className="flex items-start gap-3 px-4 py-4 sm:px-5">
        <input
          ref={checkboxRef}
          type="checkbox"
          checked
          aria-label={chapter.title}
          onChange={(event) => {
            if (!event.target.checked) onRemove();
          }}
          className="mt-0.5 h-[18px] w-[18px] shrink-0 accent-[hsl(var(--memory-accent))]"
        />
        <div className="min-w-0 flex-1">
          <h3 className="break-words text-sm font-semibold leading-5 text-[hsl(var(--memory-title))] sm:text-base">
            {chapter.title}
          </h3>
          {chapter.summary ? (
            <p className="mt-1.5 text-sm leading-6 text-[hsl(var(--memory-body))]">{chapter.summary}</p>
          ) : null}
          <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[hsl(var(--memory-muted))]">
            {timeRange ? <span>{timeRange}</span> : null}
            {chapter.episode_ids.length > 0 ? (
              <span>{t('memory.episodes.draft.sourceCount', { count: chapter.episode_ids.length })}</span>
            ) : null}
            {eventCount > 0 ? (
              <span>{t('memory.episodes.draft.eventCount', { count: eventCount })}</span>
            ) : null}
          </div>
        </div>
        {chapter.episode_ids.length > 0 ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-expanded={contentOpen}
            onClick={toggleContent}
            className="h-8 shrink-0 px-2 text-xs font-medium text-[hsl(var(--memory-accent))] hover:bg-[hsl(var(--memory-accent-soft)/0.58)]"
          >
            {contentOpen ? t('memory.episodes.draft.hideContent') : t('memory.episodes.draft.viewContent')}
            {contentOpen ? <ChevronUp className="h-3.5 w-3.5" aria-hidden="true" /> : <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />}
          </Button>
        ) : null}
      </div>

      {contentOpen ? (
        <div className="border-t border-[hsl(var(--memory-border)/0.42)] bg-[hsl(var(--memory-panel-elevated)/0.54)] px-4 py-4 sm:px-5">
          {contentState === 'loading' ? (
            <p className="text-sm text-[hsl(var(--memory-muted))]">{t('memory.episodes.draft.contentLoading')}</p>
          ) : null}
          {contentState === 'failed' ? (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm text-[hsl(var(--memory-muted))]">{t('memory.episodes.draft.contentFailed')}</p>
              <Button type="button" variant="ghost" size="sm" onClick={() => { void loadContent(); }} className="h-8 px-2 text-xs">
                <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                {t('memory.episodes.draft.retryContent')}
              </Button>
            </div>
          ) : null}
          {contentState === 'loaded' && readableEvents.length === 0 ? (
            <p className="text-sm text-[hsl(var(--memory-muted))]">{t('memory.episodes.draft.contentEmpty')}</p>
          ) : null}
          {contentState === 'loaded' && readableEvents.length > 0 ? (
            <ol className="space-y-3">
              {readableEvents.map((event, index) => {
                const eventTime = formatEventTime(event.timestamp, i18n.language);
                return (
                  <li key={`${event.event_id}-${index}`} className="border-l-2 border-[hsl(var(--memory-divider)/0.72)] pl-3">
                    <p className="text-sm leading-6 text-[hsl(var(--memory-body))]">{event.content_preview}</p>
                    {event.source || eventTime ? (
                      <div className="mt-1 flex flex-wrap gap-x-2 text-xs text-[hsl(var(--memory-muted))]">
                        {event.source ? <span>{event.source}</span> : null}
                        {eventTime ? <time dateTime={new Date((event.timestamp ?? 0) * 1000).toISOString()}>{eventTime}</time> : null}
                      </div>
                    ) : null}
                  </li>
                );
              })}
            </ol>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

export default ExperienceDraftSegmentCard;
