import { GitMerge, Layers } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type {
  ExperienceDraftChapter,
  L2EpisodeEventPreview,
  L2EpisodeWithSummary,
} from '@/api/modules/memory';
import { formatEpisodeTimeRange } from '../episodes/EpisodeRow';
import {
  formatEventTime,
  formatSourceLabel,
  getReadableSourceEpisodeSummary,
  getReadableSourceEpisodeTitle,
} from './ExperienceDetailModel';

export function SourceEpisodeList({
  episodes,
  eventsByEpisode,
  chapters = [],
}: {
  episodes: L2EpisodeWithSummary[];
  eventsByEpisode: Map<string, L2EpisodeEventPreview[]>;
  chapters?: ExperienceDraftChapter[];
}) {
  const { t, i18n } = useTranslation('app');
  if (chapters.length > 0) {
    return (
      <section data-testid="episode-event-stream">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-[hsl(var(--memory-title))]">
          <Layers className="h-4 w-4 text-[hsl(var(--memory-accent))]" aria-hidden="true" />
          {t('memory.episodes.sections.sourceEpisodes')}
        </h3>
        <div data-testid="experience-source-episodes" className="mt-3 grid gap-3">
          {chapters.map((chapter) => {
            const chapterEvents = chapter.episode_ids.flatMap((episodeId) => eventsByEpisode.get(episodeId) ?? []);
            const range = formatEpisodeTimeRange(chapter.time_start, chapter.time_end, i18n.language);
            return (
              <article key={chapter.chapter_id} className="rounded-lg border border-[hsl(var(--memory-border)/0.52)] bg-[hsl(var(--memory-panel-elevated)/0.74)] px-5 py-5">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <h4 className="break-words text-base font-semibold leading-6 text-[hsl(var(--memory-title))]">{chapter.title}</h4>
                    {chapter.summary ? <p className="mt-2 text-sm leading-6 text-[hsl(var(--memory-body))]">{chapter.summary}</p> : null}
                  </div>
                  <div className="shrink-0 text-xs text-[hsl(var(--memory-muted))]">{range}</div>
                </div>
                <SourceEpisodeEventTrail events={chapterEvents} />
              </article>
            );
          })}
        </div>
      </section>
    );
  }
  return (
    <section data-testid="episode-event-stream">
      <h3 className="flex items-center gap-2 text-sm font-semibold text-[hsl(var(--memory-title))]">
        <Layers className="h-4 w-4 text-[hsl(var(--memory-accent))]" aria-hidden="true" />
        {t('memory.episodes.sections.sourceEpisodes')}
      </h3>
      <div data-testid="experience-source-episodes" className="mt-3 grid gap-3">
        {episodes.length === 0 ? (
          <div className="rounded-lg border border-[hsl(var(--memory-border)/0.52)] px-4 py-3 text-sm text-[hsl(var(--memory-muted))]">
            {t('memory.episodes.noSourceEpisodes')}
          </div>
        ) : episodes.map((episode, index) => {
          const title = getReadableSourceEpisodeTitle(
            episode,
            index,
            t('memory.episodes.sourceEpisodeFallback', { index: index + 1 }),
            eventsByEpisode
          );
          const rawSummary = getReadableSourceEpisodeSummary(episode, eventsByEpisode);
          const summary = rawSummary === title ? '' : rawSummary;
          const range = formatEpisodeTimeRange(episode.time_start, episode.time_end, i18n.language);
          const episodeEvents = eventsByEpisode.get(episode.episode_id) ?? [];
          return (
            <article key={episode.episode_id} className="rounded-lg border border-[hsl(var(--memory-border)/0.52)] bg-[hsl(var(--memory-panel-elevated)/0.74)] px-5 py-5">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <h4 className="break-words text-base font-semibold leading-6 text-[hsl(var(--memory-title))]">{title}</h4>
                  {summary ? (
                    <p className="mt-2 line-clamp-3 text-sm leading-6 text-[hsl(var(--memory-body))]">{summary}</p>
                  ) : null}
                </div>
                <div className="shrink-0 text-xs text-[hsl(var(--memory-muted))]">
                  {range}
                </div>
              </div>
              <SourceEpisodeEventTrail events={episodeEvents} />
            </article>
          );
        })}
      </div>
    </section>
  );
}

function SourceEpisodeEventTrail({ events }: { events: L2EpisodeEventPreview[] }) {
  const { t, i18n } = useTranslation('app');
  if (events.length === 0) {
    return null;
  }

  return (
    <div className="mt-4 border-t border-[hsl(var(--memory-divider)/0.58)] pt-4">
      <div className="flex items-center gap-2 text-xs font-semibold text-[hsl(var(--memory-muted))]">
        <GitMerge className="h-4 w-4 text-[hsl(var(--memory-accent))]" aria-hidden="true" />
        {t('memory.episodes.sections.whatHappened')}
      </div>
      <div className="mt-3 grid gap-2">
        {events.map((event) => {
          const time = formatEventTime(event.timestamp ?? event.added_at, i18n.language);
          const preview = String(event.content_preview || '').trim();
          const source = formatSourceLabel(event.source);
          return (
            <article
              key={`${event.episode_id}-${event.event_id}`}
              className="rounded-md bg-[hsl(var(--memory-panel-subtle)/0.5)] px-3 py-2"
            >
              <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between sm:gap-3">
                <p className="min-w-0 whitespace-pre-wrap break-words text-sm leading-6 text-[hsl(var(--memory-body))]">
                  {preview || t('memory.episodes.eventPreviewUnavailable')}
                </p>
                {time ? <span className="shrink-0 text-xs text-[hsl(var(--memory-muted))]">{time}</span> : null}
              </div>
              {source ? (
                <div className="mt-1 text-xs text-[hsl(var(--memory-muted))]">{source}</div>
              ) : null}
            </article>
          );
        })}
      </div>
    </div>
  );
}
